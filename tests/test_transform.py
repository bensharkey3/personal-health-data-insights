"""Transform: synthetic raw pages in, curated Parquet rows out. Synthetic data only."""

import gzip
import io
import json
import shutil
from datetime import date
from pathlib import Path

import duckdb
import pytest

from transform import google_health, handler


def civil(d: date, h: int) -> dict:
    return {"date": {"year": d.year, "month": d.month, "day": d.day}, "time": {"hours": h}}


def write(path, pages: list[dict]) -> str:
    with gzip.open(path, "wt") as f:
        f.writelines(json.dumps(p) + "\n" for p in pages)
    return str(path).replace("\\", "/")


def rows(tmp_path, kind: str, pages: list[dict]) -> list[dict]:
    out = str(tmp_path / "out.parquet").replace("\\", "/")
    n = handler.build(kind, [write(tmp_path / "in.jsonl.gz", pages)], out)
    rel = duckdb.sql(f"SELECT * FROM '{out}'")
    got = [dict(zip(rel.columns, r, strict=True)) for r in rel.fetchall()]
    assert n == len(got)
    return got


SOURCE = {"dataSource": {"platform": "FITBIT"}}


def test_heart_rate_samples(tmp_path):
    point = {
        "heartRate": {
            "sampleTime": {
                "physicalTime": "2030-01-14T22:00:00Z",
                "utcOffset": "36000s",
                "civilTime": civil(date(2030, 1, 15), 8),
            },
            "beatsPerMinute": "61",  # numbers often arrive as strings
        }
    } | SOURCE
    # two pages, as the API returns them
    got = rows(
        tmp_path,
        "heart-rate",
        [{"dataPoints": [point], "nextPageToken": "x"}, {"dataPoints": [point]}],
    )
    assert len(got) == 2
    assert got[0]["bpm"] == 61 and got[0]["local_date"] == date(2030, 1, 15)
    assert got[0]["platform"] == "FITBIT"


def test_sleep_belongs_to_the_local_day_it_ends(tmp_path):
    point = {
        "sleep": {
            "interval": {
                "startTime": "2030-01-14T12:00:00Z",
                "endTime": "2030-01-14T20:00:00Z",  # 06:00 on the 15th at +10h
                "endUtcOffset": "36000s",
            },
            "type": "STAGES",
            "metadata": {"mainSleep": True},
            "summary": {
                "minutesAsleep": "420",
                "stagesSummary": [
                    {"type": "DEEP", "minutes": "60"},
                    {"type": "REM", "minutes": "90"},
                ],
            },
            "stages": [{"type": "DEEP"}],
        }
    } | SOURCE
    [got] = rows(tmp_path, "sleep", [{"dataPoints": [point]}])
    assert got["local_date"] == date(2030, 1, 15)
    assert got["minutes_asleep"] == 420 and got["main_sleep"] is True
    assert (got["deep_minutes"], got["rem_minutes"], got["light_minutes"]) == (60, 90, None)


def test_steps_drop_empty_windows_and_use_local_date(tmp_path):
    windows = [
        {"startTime": "2030-01-15T13:59:00Z", "steps": {"countSum": "12"}},  # 00:59 on the 16th
        {"startTime": "2030-01-15T14:00:00Z", "steps": {"countSum": "0"}},
        {"startTime": "2030-01-15T14:01:00Z", "steps": {}},
    ]
    [got] = rows(tmp_path, "steps", [{"rollupDataPoints": windows}])
    assert got["steps"] == 12 and got["local_date"] == date(2030, 1, 16)


def test_steps_take_the_phone_zone_from_its_fixes(tmp_path):
    fixes = tmp_path / "fixes.csv.gz"  # from 12:00 UTC on the 15th the phone reports UTC-5
    fixes.write_bytes(gzip.compress(b"1894708800,location,1.00,2.00,Etc/GMT+5\n"))
    pages = [
        {"rollupDataPoints": [{"startTime": "2030-01-15T13:59:00Z", "steps": {"countSum": "5"}}]}
    ]
    out = str(tmp_path / "out.parquet").replace("\\", "/")
    handler.build(
        "steps", [write(tmp_path / "in.jsonl.gz", pages)], out, [str(fixes).replace("\\", "/")]
    )
    assert duckdb.sql(f"SELECT local_date FROM '{out}'").fetchall() == [(date(2030, 1, 15),)]


def test_daily_type(tmp_path):
    point = {
        "dailyRestingHeartRate": {
            "date": {"year": 2030, "month": 1, "day": 15},
            "beatsPerMinute": "55",
        }
    } | SOURCE
    [got] = rows(tmp_path, "daily-resting-heart-rate", [{"dataPoints": [point]}])
    assert (got["local_date"], got["bpm"]) == (date(2030, 1, 15), 55)


def test_every_type_has_a_select():
    assert set(google_health.SELECTS) == {
        "heart-rate", "daily-resting-heart-rate", "heart-rate-variability",
        "daily-heart-rate-variability", "sleep", "oxygen-saturation", "daily-oxygen-saturation",
        "daily-respiratory-rate", "respiratory-rate-sleep-summary",
        "daily-sleep-temperature-derivations", "steps",
    }  # fmt: skip


def test_months_from_days_and_from_a_range():
    assert handler.months({"days": {"steps": ["2030-01-31", "2030-02-01"]}}) == {
        "steps": {"2030-01", "2030-02"}
    }
    span = handler.months({"start": "2029-11", "end": "2030-02"})
    assert span["sleep"] == {"2029-11", "2029-12", "2030-01", "2030-02"}


class FakeS3:
    """Lists, downloads from and uploads to an in-memory bucket of local files."""

    def __init__(self, objects: dict[str, str], store=None):
        self.objects, self.store = objects, store  # key -> local path; where uploads land

    def get_paginator(self, name):
        objects = self.objects

        class Paginator:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [{"Key": k} for k in objects if k.startswith(Prefix)]}

        return Paginator()

    def download_file(self, bucket, key, path):
        shutil.copy(self.objects[key], path)

    def upload_file(self, path, bucket, key):
        self.objects[key] = shutil.copy(path, self.store / key.replace("/", "_"))

    def list_objects_v2(self, Bucket, Prefix):
        return {"KeyCount": sum(k.startswith(Prefix) for k in self.objects)}

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(Path(self.objects[Key]).read_bytes())}

    def put_object(self, Bucket, Key, Body, **kw):  # the dashboard page, kept as bytes
        self.objects[f"{Bucket}/{Key}"] = Body


def test_latest_file_per_day_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("RAW_BUCKET", "b")

    def day(n, bpm, name):
        point = {
            "dailyRestingHeartRate": {
                "date": {"year": 2030, "month": 1, "day": n},
                "beatsPerMinute": str(bpm),
            }
        }
        return write(tmp_path / name, [{"dataPoints": [point]}])

    prefix = "raw/google_health/daily-resting-heart-rate"
    s3 = FakeS3(
        {
            f"{prefix}/dt=2030-01-15/pages.jsonl.gz": day(15, 70, "a"),  # old step 02 layout
            f"{prefix}/dt=2030-01-15/run=20300116T000000Z.jsonl.gz": day(15, 60, "b"),
            f"{prefix}/dt=2030-01-15/run=20300117T000000Z.jsonl.gz": day(15, 55, "c"),  # newest
            f"{prefix}/dt=2030-01-16/pages.jsonl.gz": day(16, 58, "d"),  # only file that day
            f"{prefix}/dt=2030-02-01/run=20300202T000000Z.jsonl.gz": day(1, 50, "e"),  # other month
        },
        store=tmp_path,
    )
    event = {"days": {"daily-resting-heart-rate": ["2030-01-16"]}}
    assert handler.handler(event, None, s3=s3) == {"daily-resting-heart-rate/2030-01": 2}
    # the same raw files always give the same result
    assert handler.handler(event, None, s3=s3) == {"daily-resting-heart-rate/2030-01": 2}

    out = s3.objects["curated/google_health/daily-resting-heart-rate/month=2030-01/data.parquet"]
    got = duckdb.sql(f"SELECT local_date, bpm FROM '{str(out).replace(chr(92), '/')}'").fetchall()
    assert got == [(date(2030, 1, 15), 55), (date(2030, 1, 16), 58)]


@pytest.mark.parametrize("event", [{"days": {"sleep": ["2030-05-01"]}}])
def test_month_without_raw_files_is_skipped(event, monkeypatch):
    monkeypatch.setenv("RAW_BUCKET", "b")
    assert handler.handler(event, None, s3=FakeS3({})) == {}
