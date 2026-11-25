"""Weather (D30) at the phone's location (D29): ingest, transform and the trigger from the phone
batch. Synthetic data and coordinates only."""

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

DAY = date(2030, 1, 15)


def response(d: date, night: float, day_max: float = 30.0) -> dict:
    """An Open-Meteo-shaped reply for d and the evening before, in local time."""
    eve, iso = date.fromordinal(d.toordinal() - 1).isoformat(), d.isoformat()
    hours = [f"{x}T{h:02}:00" for x in (eve, iso) for h in range(24)]
    temps = [night if t >= f"{eve}T22:00" and t < f"{iso}T06:00" else 99.0 for t in hours]
    daily = {
        "time": [eve, iso],
        "temperature_2m_max": [0, day_max],
        "temperature_2m_min": [0, 12.5],
        "apparent_temperature_max": [0, 31.0],
        "precipitation_sum": [0, 1.2],
        "relative_humidity_2m_mean": [0, 55],
        "wind_speed_10m_max": [0, 20.0],
        "uv_index_max": [0, 9.1],
        "sunrise": [f"{eve}T06:00", f"{iso}T06:01"],
        "sunset": [f"{eve}T20:30", f"{iso}T20:31"],
        "daylight_duration": [0, 52200.0],
    }
    hourly = {"time": hours, "temperature_2m": temps}
    return {"timezone": "Etc/GMT-11", "daily": daily, "hourly": hourly}


def test_url_covers_the_date_and_its_eve_at_that_place():
    url = ingest.url({"date": "2030-01-15", "lat": -12.3456, "lon": 123.4}, today=DAY)
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    assert url.startswith(ingest.FORECAST)
    assert (q["start_date"], q["end_date"]) == ("2030-01-14", "2030-01-15")
    assert (q["latitude"], q["longitude"], q["timezone"]) == ("-12.35", "123.40", "auto")
    old = ingest.url({"date": "2029-01-15", "lat": 1, "lon": 2}, today=DAY)
    assert old.startswith(ingest.ARCHIVE)


class FakeLambda:
    def __init__(self):
        self.invokes = []

    def invoke(self, **kw):
        self.invokes.append(json.loads(kw["Payload"]))


class PutS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[Key] = Body


def test_ingest_writes_raw_per_date_and_starts_the_transform(monkeypatch, capsys):
    monkeypatch.setenv("RAW_BUCKET", "b")
    monkeypatch.setenv("TRANSFORM_FUNCTION", "transform")
    replies = [response(date(2030, 1, 14), 20), response(DAY, 18)]
    monkeypatch.setattr(
        retry, "urlopen", lambda req, timeout: io.BytesIO(json.dumps(replies.pop(0)).encode())
    )
    s3, lam = PutS3(), FakeLambda()
    days = [
        {"date": "2030-01-14", "lat": -12.34, "lon": 123.45},
        {"date": "2030-01-15", "lat": -12.34, "lon": 123.45},
    ]
    assert ingest.handler({"days": days}, None, s3=s3, lam=lam) == {"written": 2}
    keys = sorted(s3.objects)
    assert keys[0].startswith("raw/weather/daily/dt=2030-01-14/run=")
    assert json.loads(gzip.decompress(s3.objects[keys[1]])) == response(DAY, 18)
    assert lam.invokes == [{"source": "weather"}]
    assert "-12.34" not in capsys.readouterr().out  # coordinates never logged


def test_recent_days_carry_the_location_forward():
    fixes = [(date(2030, 1, 10), 1.0, 2.0), (date(2030, 1, 13), 3.0, 4.0)]
    got = weather.recent_days(fixes, days=5)
    assert [(d["date"], d["lat"]) for d in got] == [
        ("2030-01-10", 1.0),  # the 9th is before the first fix, so it's left out
        ("2030-01-11", 1.0),
        ("2030-01-12", 1.0),
        ("2030-01-13", 3.0),
    ]
    assert weather.recent_days([]) == []


def write(tmp_path, name: str, reply: dict) -> str:
    path = tmp_path / name
    path.write_bytes(gzip.compress((json.dumps(reply) + "\n").encode()))
    return str(path).replace("\\", "/")


def test_daily_row_with_the_night_that_ends_that_morning(tmp_path):
    out = str(tmp_path / "out.parquet").replace("\\", "/")
    handler.write(weather.query([write(tmp_path, "a.jsonl.gz", response(DAY, 17.5))]), out)
    rel = duckdb.sql(f"SELECT * FROM '{out}'")
    [row] = [dict(zip(rel.columns, r, strict=True)) for r in rel.fetchall()]
    assert row["local_date"] == DAY and row["time_zone"] == "Etc/GMT-11"
    assert (row["temp_max_c"], row["temp_min_c"], row["daylight_hours"]) == (30.0, 12.5, 14.5)
    assert row["night_temp_c"] == 17.5  # only 22:00 the eve to 06:00; other hours are 99


def test_weather_rebuild_takes_the_newest_run_per_date(tmp_path, monkeypatch):
    monkeypatch.setenv("RAW_BUCKET", "b")
    pre = "raw/weather/daily/dt=2030-01-15"
    s3 = FakeS3(
        {
            f"{pre}/run=20300115T000000Z.jsonl.gz": write(tmp_path, "a", response(DAY, 18, 25.0)),
            f"{pre}/run=20300116T000000Z.jsonl.gz": write(tmp_path, "b", response(DAY, 18, 31.0)),
        },
        store=tmp_path,
    )
    assert handler.handler({"source": "weather"}, None, s3=s3) == {"weather/daily": 1}
    out = str(s3.objects["curated/weather/daily/data.parquet"]).replace("\\", "/")
    assert duckdb.sql(f"SELECT temp_max_c FROM '{out}'").fetchall() == [(31.0,)]


def test_phone_batch_asks_for_the_last_week_of_weather_at_its_location(tmp_path, monkeypatch):
    monkeypatch.setenv("RAW_BUCKET", "b")
    monkeypatch.setenv("WEATHER_FUNCTION", "weather")
    batch = tmp_path / "batch.csv.gz"  # 1894708800 = 12:00 UTC on 2030-01-15, 23:00 at UTC+11
    batch.write_bytes(gzip.compress(b"1894708800,location,-12.34,123.45,Etc/GMT-11\n"))
    s3 = FakeS3({"raw/tasker/events/dt=2030-01-15/run=x.csv.gz": str(batch)}, store=tmp_path)
    lam = FakeLambda()
    handler.handler({"source": "tasker"}, None, s3=s3, lam=lam)
    [payload] = lam.invokes
    assert payload == {"days": [{"date": "2030-01-15", "lat": -12.34, "lon": 123.45}]}
