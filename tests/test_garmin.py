"""Garmin activities (D39): ingest, transform and the dashboard's Training section.
Synthetic activities only."""

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
from dashboard import build
from ingest.garmin import handler as ingest
from transform import garmin, handler

KEY = "test-api-key"


def activity(n: int, local: str, kind: str = "running", minutes: float = 30) -> dict:
    return {
        "activityId": n,
        "activityName": f"Session {n}",
        "activityType": {"typeKey": kind},
        "startTimeLocal": local,
        "startTimeGMT": local,  # tests don't need a real offset
        "duration": minutes * 60,
        "distance": 5000.0,
        "averageHR": 150.0,
        "maxHR": 175.0,
        "calories": 400.0,
    }


class FakeSSM:
    def get_parameter(self, Name, WithDecryption):
        assert Name == ingest.KEY_PARAM and WithDecryption
        return {"Parameter": {"Value": KEY}}


class FakeDDB:
    def __init__(self, item=None):
        self.item, self.puts = item or {}, []

    def get_item(self, TableName, Key):
        return {"Item": self.item}

    def put_item(self, TableName, Item):
        self.puts.append(Item)


class FakeS3Put:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[Key] = Body


class FakeLambda:
    def __init__(self):
        self.invokes = []

    def invoke(self, **kw):
        self.invokes.append(json.loads(kw["Payload"]))


def fake_api(monkeypatch, activities: list[dict], token_error: int | None = None) -> list:
    """Answers the token POST, then pages of the activity list by offset."""
    calls = []

    def urlopen(req, timeout):
        calls.append(req)
        if req.full_url.endswith(ingest.TOKEN_PATH):
            if token_error:
                raise urllib.error.HTTPError(req.full_url, token_error, "no", Message(), None)
            return io.BytesIO(b"jwt-token\n")
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(req.full_url).query))
        start, limit = int(q["start"]), int(q["limit"])
        return io.BytesIO(json.dumps(activities[start : start + limit]).encode())

    monkeypatch.setattr(retry, "urlopen", urlopen)
    monkeypatch.setattr(retry.time, "sleep", lambda s: None)
    return calls


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("RAW_BUCKET", "b")
    monkeypatch.setenv("WATERMARK_TABLE", "wm")
    monkeypatch.setenv("TRANSFORM_FUNCTION", "transform")


def test_ingest_pages_through_activities_and_starts_the_transform(env, monkeypatch, capsys):
    monkeypatch.setattr(ingest, "PAGE", 2)  # three pages: 2, 1, then an empty one
    acts = [activity(i, f"2030-01-1{i} 07:00:00") for i in range(1, 4)]
    calls = fake_api(monkeypatch, acts)
    s3, ddb, lam = FakeS3Put(), FakeDDB(), FakeLambda()
    assert ingest.handler({}, None, ssm=FakeSSM(), s3=s3, ddb=ddb, lam=lam) == {"activities": 3}
    token, *lists = calls
    assert token.get_method() == "POST" and token.headers["Authorization"] == f"ApiKey {KEY}"
    assert all(c.headers["Authorization"] == "Bearer jwt-token" for c in lists)
    [(key, body)] = s3.objects.items()
    assert key.startswith("raw/garmin/activities/dt=")
    pages = [json.loads(line) for line in gzip.decompress(body).splitlines()]
    assert [len(p["activities"]) for p in pages] == [2, 1]
    assert ddb.puts[0]["newest_point_utc"] == {"S": "2030-01-13T07:00:00Z"}
    assert lam.invokes == [{"source": "garmin"}]
    assert KEY not in capsys.readouterr().out  # the key is never logged


def test_incremental_window_starts_a_day_before_the_newest_activity_at_most_a_week_back():
    today = date(2030, 1, 20)
    mark = {"newest_point_utc": "2030-01-18T07:00:00Z"}
    assert ingest.window({}, mark, today) == (date(2030, 1, 17), date(2030, 1, 21))
    old = {"newest_point_utc": "2029-06-01T07:00:00Z"}
    assert ingest.window({}, old, today)[0] == date(2030, 1, 13)  # capped at 7 days back
    backfill = {"start": "2029-01-01", "end": "2029-03-31"}
    assert ingest.window(backfill, {}, today) == (date(2029, 1, 1), date(2029, 3, 31))


def test_a_rejected_key_fails_the_run_and_says_to_renew_it(env, monkeypatch):
    fake_api(monkeypatch, [], token_error=401)
    with pytest.raises(RuntimeError, match="renew"):
        ingest.handler({}, None, ssm=FakeSSM(), s3=FakeS3Put(), ddb=FakeDDB(), lam=FakeLambda())


def test_no_activities_writes_nothing_and_skips_the_transform(env, monkeypatch):
    fake_api(monkeypatch, [])
    s3, lam = FakeS3Put(), FakeLambda()
    ingest.handler({}, None, ssm=FakeSSM(), s3=s3, ddb=FakeDDB(), lam=lam)
    assert s3.objects == {} and lam.invokes == []


def raw_file(tmp_path, name: str, pages: list[list[dict]]) -> str:
    path = tmp_path / f"{name}.jsonl.gz"
    lines = "".join(json.dumps({"activities": p}) + "\n" for p in pages)
    path.write_bytes(gzip.compress(lines.encode()))
    return str(path)


def test_transform_keeps_the_newest_copy_of_each_activity(tmp_path):
    older = raw_file(tmp_path, "a", [[activity(1, "2030-01-14 07:00:00", minutes=30)]])
    edited = activity(1, "2030-01-14 07:00:00", minutes=45)  # renamed or trimmed later
    newer = raw_file(tmp_path, "b", [[edited, activity(2, "2030-01-15 18:30:00", "cycling")]])
    rows = duckdb.sql(garmin.query([older, newer])).fetchall()
    cols = [c[0] for c in duckdb.sql(garmin.query([older, newer])).description]
    got = [dict(zip(cols, r, strict=True)) for r in rows]
    assert [(r["activity_id"], r["duration_s"], r["type"]) for r in got] == [
        (1, 2700.0, "running"),
        (2, 1800.0, "cycling"),
    ]
    assert got[1]["local_date"] == date(2030, 1, 15) and got[0]["training_load"] is None


def test_transform_rebuild_writes_the_curated_table(tmp_path, monkeypatch):
    monkeypatch.setenv("RAW_BUCKET", "b")
    store = tmp_path / "store"
    store.mkdir()
    f = raw_file(tmp_path, "a", [[activity(1, "2030-01-14 07:00:00")]])
    s3 = FakeS3({"raw/garmin/activities/dt=2030-01-14/run=20300114T190000Z.jsonl.gz": f}, store)
    assert handler.rebuild_garmin(s3, "b") == {"garmin/activities": 1}
    assert "curated/garmin/activities/data.parquet" in s3.objects


TODAY = date(2030, 1, 31)  # a Thursday


def curated(tmp_path, acts: list[dict]) -> None:
    out = tmp_path / build.ACTIVITIES
    out.parent.mkdir(parents=True)
    f = raw_file(tmp_path, "x", [acts])
    duckdb.sql(f"COPY ({garmin.query([f])}) TO '{out}' (FORMAT parquet)")


def test_training_section_shows_the_last_activity_and_weekly_minutes(tmp_path):
    curated(
        tmp_path,
        [
            activity(1, "2030-01-22 07:00:00", minutes=60),  # last week
            activity(2, "2030-01-28 07:00:00", minutes=30),  # this week (Mon)
            activity(3, "2030-01-29 18:00:00", "trail_running", 40),  # Tue: the last complete
            activity(4, "2030-01-31 06:30:00", minutes=20),  # today: waits until tomorrow
        ],
    )
    html = build.training(tmp_path, TODAY)
    assert "Tue 29 Jan: Trail running, 5.0 km, 40 min, avg HR 150" in html
    assert "This week 2 sessions · usual 0.2" in html  # 1 session over the previous 4 weeks
    assert "<title>28 Jan: 70 min</title>" in html and 'class="bar partial"' in html


def test_training_section_without_data(tmp_path):
    assert "No Garmin activities yet." in build.training(tmp_path, TODAY)
