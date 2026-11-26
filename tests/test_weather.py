"""Weather (D30) at the phone's location (D29): the 05:00 ingest, the transform, and the latest fix
the transform keeps for it. Synthetic data and coordinates only."""

import gzip
import io
import json
import urllib.error
import urllib.parse
from datetime import date
from email.message import Message

import duckdb
import pytest
from test_transform import FakeS3  # pytest puts tests/ on the path

from common import retry
from ingest.weather import handler as ingest
from transform import handler, weather

FIX = {"lat": -12.3456, "lon": 123.4, "time_zone": "Etc/GMT-11"}


def reply(yesterday: date, night: float, maxes=(25.0, 30.0)) -> dict:
    """An Open-Meteo-shaped reply for yesterday and today, in local time."""
    y, t = yesterday.isoformat(), date.fromordinal(yesterday.toordinal() + 1).isoformat()
    hours = [f"{d}T{h:02}:00" for d in (y, t) for h in range(24)]
    temps = [night if f"{y}T22:00" <= x < f"{t}T06:00" else 20.0 for x in hours]
    daily = {
        "time": [y, t],
        "temperature_2m_max": list(maxes),
        "temperature_2m_min": [10.0, 12.5],
        "apparent_temperature_max": [26.0, 31.0],
        "precipitation_sum": [0.0, 1.2],
        "relative_humidity_2m_mean": [50, 55],
        "wind_speed_10m_max": [15.0, 20.0],
        "uv_index_max": [8.0, 9.1],
        "sunrise": [f"{y}T06:00", f"{t}T06:01"],
        "sunset": [f"{y}T20:30", f"{t}T20:31"],
        "daylight_duration": [52000.0, 52200.0],
    }
    hourly = {"time": hours, "temperature_2m": temps}
    return {"timezone": "Etc/GMT-11", "daily": daily, "hourly": hourly}


def params(url: str) -> dict:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))


def test_daily_url_asks_for_yesterday_and_today_at_the_fix():
    url = ingest.url(FIX, {})
    assert url.startswith(ingest.FORECAST)
    q = params(url)
    assert (q["past_days"], q["forecast_days"], q["timezone"]) == ("1", "1", "auto")
    assert (q["latitude"], q["longitude"]) == ("-12.35", "123.40")
    backfill = ingest.url(FIX, {"start": "2029-01-01", "end": "2029-01-31"})
    assert backfill.startswith(ingest.ARCHIVE) and params(backfill)["end_date"] == "2029-01-31"


class IngestS3:
    """Like real S3 with ListBucket scoped to a prefix: a GetObject of a missing key is denied
    (403), not "not found", so code must list the key first."""

    def __init__(self, fix: dict | None):
        self.fix, self.objects = fix, {}

    def list_objects_v2(self, Bucket, Prefix):
        return {"KeyCount": int(self.fix is not None)}

    def get_object(self, Bucket, Key):
        if self.fix is None:
            raise PermissionError("AccessDenied")
        return {"Body": io.BytesIO(json.dumps(self.fix).encode())}

    def put_object(self, Bucket, Key, Body):
        self.objects[Key] = Body


class FakeLambda:
    def __init__(self):
        self.invokes = []

    def invoke(self, **kw):
        self.invokes.append(json.loads(kw["Payload"]))


def air_reply(yesterday: date, night_pm25: float, day_pm25: float = 5.0) -> dict:
    """An Open-Meteo air quality reply: hourly values for yesterday and today, local time."""
    y, t = yesterday.isoformat(), date.fromordinal(yesterday.toordinal() + 1).isoformat()
    hours = [f"{d}T{h:02}:00" for d in (y, t) for h in range(24)]
    pm25 = [night_pm25 if f"{y}T22:00" <= x < f"{t}T06:00" else day_pm25 for x in hours]
    n = len(hours)
    hourly = {"time": hours, "pm2_5": pm25, "pm10": [10.0] * n, "ozone": [40.0] * n}
    return {"hourly": hourly | {"nitrogen_dioxide": [3.0] * n, "us_aqi": [20] * (n - 1) + [55]}}


def fake_api(monkeypatch, weather_body: dict, air) -> list[str]:
    """Answers the weather and air quality URLs; air can be an exception to raise."""
    urls = []

    def urlopen(req, timeout):
        urls.append(req.full_url)
        if not req.full_url.startswith(ingest.AIR):
            return io.BytesIO(json.dumps(weather_body).encode())
        if isinstance(air, Exception):
            raise air
        return io.BytesIO(json.dumps(air).encode())

    monkeypatch.setattr(retry, "urlopen", urlopen)
    monkeypatch.setattr(retry.time, "sleep", lambda s: None)  # retries skip their waits
    return urls


def test_ingest_stores_weather_and_air_quality_then_starts_the_transform(monkeypatch, capsys):
    monkeypatch.setenv("RAW_BUCKET", "b")
    monkeypatch.setenv("TRANSFORM_FUNCTION", "transform")
    body, air = reply(date(2030, 1, 14), 18), air_reply(date(2030, 1, 14), 30)
    urls = fake_api(monkeypatch, body, air)
    s3, lam = IngestS3(FIX), FakeLambda()
    assert ingest.handler({}, None, s3=s3, lam=lam) == {"days": 2}
    stored = {k.split("/")[2]: json.loads(gzip.decompress(v)) for k, v in s3.objects.items()}
    assert stored == {"daily": body, "air_quality": air}
    q = params(urls[1])
    assert q["hourly"] == "pm2_5,pm10,ozone,nitrogen_dioxide,us_aqi" and q["past_days"] == "1"
    assert lam.invokes == [{"source": "weather"}]
    assert "-12.3" not in capsys.readouterr().out  # coordinates never logged


def test_air_quality_outage_keeps_the_weather_but_fails_the_run(monkeypatch):
    monkeypatch.setenv("RAW_BUCKET", "b")
    monkeypatch.setenv("TRANSFORM_FUNCTION", "transform")
    down = urllib.error.HTTPError(ingest.AIR, 503, "down", Message(), io.BytesIO(b"down"))
    fake_api(monkeypatch, reply(date(2030, 1, 14), 18), down)
    s3, lam = IngestS3(FIX), FakeLambda()
    with pytest.raises(RuntimeError, match="Air quality"):
        ingest.handler({}, None, s3=s3, lam=lam)
    assert [k.split("/")[2] for k in s3.objects] == ["daily"]  # the weather is kept
    assert lam.invokes == [{"source": "weather"}]


def test_ingest_waits_for_the_first_fix(monkeypatch):
    monkeypatch.setenv("RAW_BUCKET", "b")
    s3, lam = IngestS3(None), FakeLambda()
    assert ingest.handler({}, None, s3=s3, lam=lam) == {"days": 0}
    assert s3.objects == {} and lam.invokes == []


def write(tmp_path, name: str, body: dict) -> str:
    path = tmp_path / name
    path.write_bytes(gzip.compress((json.dumps(body) + "\n").encode()))
    return str(path).replace("\\", "/")


def table(tmp_path, files: list[str], air: list[str] = ()) -> list[dict]:
    out = str(tmp_path / "out.parquet").replace("\\", "/")
    handler.write(weather.query(files, air), out)
    rel = duckdb.sql(f"SELECT * FROM '{out}'")
    return [dict(zip(rel.columns, r, strict=True)) for r in rel.fetchall()]


def test_newest_run_replaces_the_forecast_and_flags_today(tmp_path):
    runs = [  # oldest first: the 15th's run, then the 16th's
        write(tmp_path, "a.jsonl.gz", reply(date(2030, 1, 14), 18.0, maxes=(25.0, 30.0))),
        write(tmp_path, "b.jsonl.gz", reply(date(2030, 1, 15), 16.0, maxes=(28.0, 33.0))),
    ]
    got = {r["local_date"]: r for r in table(tmp_path, runs)}
    assert [(d.day, r["temp_max_c"], r["is_forecast"]) for d, r in sorted(got.items())] == [
        (14, 25.0, False),
        (15, 28.0, False),  # the 16th's run replaced the forecast of 30.0 with actuals
        (16, 33.0, True),
    ]
    assert got[date(2030, 1, 16)]["night_temp_c"] == 16.0  # 22:00 on the 15th to 06:00
    # 22:00-24:00 on the 14th only in the older run (18.0); 00:00-06:00 on the 15th from the newer
    # run, which reports 20.0 for those hours: (2 * 18 + 6 * 20) / 8
    assert got[date(2030, 1, 15)]["night_temp_c"] == 19.5
    assert got[date(2030, 1, 16)]["daylight_hours"] == 14.5


def test_tasker_rebuild_keeps_the_latest_fix_for_weather(tmp_path, monkeypatch):
    monkeypatch.setenv("RAW_BUCKET", "b")
    batch = tmp_path / "batch.csv.gz"
    batch.write_bytes(
        gzip.compress(
            b"1894622400,location,1.00,2.00,Etc/GMT-11\n"  # the 14th
            b"1894708800,location,-12.34,123.45,Etc/GMT-11\n"  # the 15th: latest
        )
    )
    s3 = FakeS3({"raw/tasker/events/dt=2030-01-15/run=x.csv.gz": str(batch)}, store=tmp_path)
    handler.handler({"source": "tasker"}, None, s3=s3)
    latest = json.loads(open(s3.objects["curated/tasker/locations/latest.json"]).read())
    assert latest == {"lat": -12.34, "lon": 123.45, "time_zone": "Etc/GMT-11"}


# --- The 15-minute tick that starts the daily runs at 05:00 phone-local (D31) ---


class TickLambda:
    def __init__(self):
        self.started = []

    def invoke(self, FunctionName, InvocationType, Payload):
        self.started.append(FunctionName)


def tick(monkeypatch, at: str, fix: dict | None) -> list[str]:
    monkeypatch.setenv("RAW_BUCKET", "b")
    monkeypatch.setenv("INGEST_FUNCTION", "ingest")
    monkeypatch.setenv("WEATHER_FUNCTION", "weather")
    lam = TickLambda()
    handler.handler({"source": "tick", "at": at}, None, s3=IngestS3(fix), lam=lam)
    return lam.started


def test_tick_starts_the_daily_runs_only_at_0500_in_the_phone_zone(monkeypatch):
    # Etc/GMT-11 is UTC+11, so 05:00 local is 18:00 UTC the day before
    assert tick(monkeypatch, "2030-01-14T18:00:00Z", FIX) == ["ingest", "weather"]
    assert tick(monkeypatch, "2030-01-14T17:45:00Z", FIX) == []  # 04:45
    assert tick(monkeypatch, "2030-01-14T18:15:00Z", FIX) == []  # 05:15


def test_tick_follows_a_half_hour_zone_and_falls_back_before_the_first_fix(monkeypatch):
    india = FIX | {"time_zone": "Asia/Kolkata"}  # UTC+05:30: 05:00 local is 23:30 UTC
    assert tick(monkeypatch, "2030-01-14T23:30:00Z", india) == ["ingest", "weather"]
    # no fix yet: TIME_ZONE (Etc/GMT-11 in tests, tests/conftest.py)
    assert tick(monkeypatch, "2030-01-14T18:00:00Z", None) == ["ingest", "weather"]


def test_air_quality_by_day_with_the_night_and_the_newest_run_per_hour(tmp_path):
    runs = [write(tmp_path, "a.jsonl.gz", reply(date(2030, 1, 14), 18.0))]
    air = [  # the newer run reports 8.0 for the 15th's daytime hours, replacing the older 5.0
        write(tmp_path, "x.jsonl.gz", air_reply(date(2030, 1, 14), 30.0)),
        write(tmp_path, "y.jsonl.gz", air_reply(date(2030, 1, 15), 12.0, day_pm25=8.0)),
    ]
    got = {r["local_date"]: r for r in table(tmp_path, runs, air)}
    day = got[date(2030, 1, 15)]
    # 22:00-24:00 on the 14th: 30.0 (older run); 00:00-06:00 on the 15th: 30.0 (older run's night
    # hours are also the newer run's day hours, so the newer 8.0 wins): (2 * 30 + 6 * 8) / 8
    assert day["night_pm25"] == 13.5
    assert (day["pm10_mean"], day["ozone_max"], day["no2_mean"]) == (10.0, 40.0, 3.0)
    assert day["pm25_max"] == 12.0 and day["aqi_max"] == 20
    assert got[date(2030, 1, 14)]["pm25_mean"] == 7.1  # (22 * 5 + 2 * 30) / 24


def test_weather_without_air_quality_still_builds(tmp_path):
    [row] = [
        r
        for r in table(tmp_path, [write(tmp_path, "a.jsonl.gz", reply(date(2030, 1, 14), 18.0))])
        if r["is_forecast"]
    ]
    assert row["pm25_mean"] is None and row["night_pm25"] is None


def test_tick_without_a_time_uses_the_clock(monkeypatch):
    """The real schedule sends only {"source": "tick"}, so the tick reads the clock."""

    class Clock(handler.datetime):
        @classmethod
        def now(cls, tz=None):
            return handler.datetime(2030, 1, 14, 18, 7, tzinfo=tz)  # 05:07 at UTC+11

    monkeypatch.setattr(handler, "datetime", Clock)
    monkeypatch.setenv("RAW_BUCKET", "b")
    monkeypatch.setenv("INGEST_FUNCTION", "ingest")
    monkeypatch.setenv("WEATHER_FUNCTION", "weather")
    lam = TickLambda()
    handler.handler({"source": "tick"}, None, s3=IngestS3(FIX), lam=lam)
    assert lam.started == ["ingest", "weather"]
