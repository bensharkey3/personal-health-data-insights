"""Weather (D30) at the phone's location (D29): the 05:00 ingest, the transform, and the latest fix
the transform keeps for it. Synthetic data and coordinates only."""

import gzip
import io
import json
import urllib.parse
from datetime import date

import duckdb
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
    class exceptions:  # noqa: N801 - mirrors boto3's client.exceptions
        NoSuchKey = KeyError

    def __init__(self, fix: dict | None):
        self.fix, self.objects = fix, {}

    def get_object(self, Bucket, Key):
        if self.fix is None:
            raise KeyError(Key)
        return {"Body": io.BytesIO(json.dumps(self.fix).encode())}

    def put_object(self, Bucket, Key, Body):
        self.objects[Key] = Body


class FakeLambda:
    def __init__(self):
        self.invokes = []

    def invoke(self, **kw):
        self.invokes.append(json.loads(kw["Payload"]))


def test_ingest_stores_the_reply_and_starts_the_transform(monkeypatch, capsys):
    monkeypatch.setenv("RAW_BUCKET", "b")
    monkeypatch.setenv("TRANSFORM_FUNCTION", "transform")
    body = reply(date(2030, 1, 14), 18)
    monkeypatch.setattr(
        retry, "urlopen", lambda req, timeout: io.BytesIO(json.dumps(body).encode())
    )
    s3, lam = IngestS3(FIX), FakeLambda()
    assert ingest.handler({}, None, s3=s3, lam=lam) == {"days": 2}
    [(key, data)] = s3.objects.items()
    assert key.startswith("raw/weather/daily/dt=") and json.loads(gzip.decompress(data)) == body
    assert lam.invokes == [{"source": "weather"}]
    assert "-12.3" not in capsys.readouterr().out  # coordinates never logged


def test_ingest_waits_for_the_first_fix(monkeypatch):
    monkeypatch.setenv("RAW_BUCKET", "b")
    s3, lam = IngestS3(None), FakeLambda()
    assert ingest.handler({}, None, s3=s3, lam=lam) == {"days": 0}
    assert s3.objects == {} and lam.invokes == []


def write(tmp_path, name: str, body: dict) -> str:
    path = tmp_path / name
    path.write_bytes(gzip.compress((json.dumps(body) + "\n").encode()))
    return str(path).replace("\\", "/")


def table(tmp_path, files: list[str]) -> list[dict]:
    out = str(tmp_path / "out.parquet").replace("\\", "/")
    handler.write(weather.query(files), out)
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
