"""Google Health client and handler, with fake HTTP, SSM and S3. Synthetic data only."""

import gzip
import io
import json
import urllib.parse
from datetime import date

import pytest

from common import retry
from ingest.google_health import client, handler

DAY = date(2030, 1, 15)


@pytest.fixture
def api(monkeypatch):
    """Replaces urlopen: returns queued responses in order and records each request."""
    calls: list = []
    queue: list[dict] = []

    def fake_urlopen(req, timeout):
        calls.append(req)
        return io.BytesIO(json.dumps(queue.pop(0)).encode())  # BytesIO works as `with` target

    monkeypatch.setattr(retry, "urlopen", fake_urlopen)
    return calls, queue


def query(req) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(req.full_url).query))


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (
            "heart-rate",
            'heart_rate.sample_time.civil_time >= "2030-01-15T00:00:00"'
            ' AND heart_rate.sample_time.civil_time < "2030-01-16T00:00:00"',
        ),
        (
            "daily-resting-heart-rate",
            'daily_resting_heart_rate.date >= "2030-01-15"'
            ' AND daily_resting_heart_rate.date < "2030-01-16"',
        ),
        (
            "sleep",
            'sleep.interval.civil_end_time >= "2030-01-15T00:00:00"'
            ' AND sleep.interval.civil_end_time < "2030-01-16T00:00:00"',
        ),
    ],
)
def test_day_filter(kind, expected):
    assert client.day_filter(kind, DAY) == expected


def test_all_in_scope_types():
    assert len(client.TYPES) == 11 and "steps" in client.ROLLUP_TYPES


def test_list_follows_tokens_past_an_empty_page(api):
    calls, queue = api
    queue += [
        {"nextPageToken": "a"},
        {"dataPoints": [{}, {}], "nextPageToken": "b"},
        {"dataPoints": [{}]},
    ]
    got = list(client.list_pages("heart-rate", DAY, "tok"))
    assert [client.count(p) for p in got] == [0, 2, 1]
    assert [query(c).get("pageToken") for c in calls] == [None, "a", "b"]
    assert query(calls[0])["pageSize"] == "5000"
    assert calls[0].get_header("Authorization") == "Bearer tok"


def test_sleep_page_size(api):
    calls, queue = api
    queue.append({})
    list(client.list_pages("sleep", DAY, "tok"))
    assert query(calls[0])["pageSize"] == "25"


def test_rollup_covers_the_utc_day(api):
    calls, queue = api
    queue.append({"rollupDataPoints": [{}, {}, {}]})
    got = list(client.pages("steps", DAY, "tok"))
    body = json.loads(calls[0].data)
    assert calls[0].full_url.endswith("/steps/dataPoints:rollUp")
    assert body["range"] == {"startTime": "2030-01-15T00:00:00Z", "endTime": "2030-01-16T00:00:00Z"}
    assert body["windowSize"] == "60s" and client.count(got[0]) == 3


class FakeSSM:
    def get_parameters(self, Names, WithDecryption):
        assert WithDecryption
        return {
            "Parameters": [{"Name": n, "Value": f"fake-{n.rsplit('/', 1)[1]}"} for n in Names],
            "InvalidParameters": [],
        }


class FakeS3:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body):
        assert Key not in self.objects  # raw is immutable: never overwrite
        self.objects[Key] = Body


class FakeDDB:
    def __init__(self):
        self.items: dict[str, dict] = {}

    def get_item(self, TableName, Key):
        item = self.items.get(Key["pk"]["S"])
        return {"Item": item} if item else {}

    def put_item(self, TableName, Item):
        self.items[Item["pk"]["S"]] = Item


@pytest.mark.parametrize(
    ("kind", "point", "expected"),
    [
        (
            "heart-rate",
            {"heartRate": {"sampleTime": {"physicalTime": "2030-01-15T08:00:00Z"}}},
            "2030-01-15T08:00:00Z",
        ),
        (
            "sleep",
            {"sleep": {"interval": {"endTime": "2030-01-15T20:30:00Z"}}},
            "2030-01-15T20:30:00Z",
        ),
        (
            "daily-resting-heart-rate",
            {"dailyRestingHeartRate": {"date": {"year": 2030, "month": 1, "day": 5}}},
            "2030-01-05T00:00:00Z",
        ),
        (
            "daily-oxygen-saturation",
            {"dailyOxygenSaturation": {"date": "2030-01-05"}},
            "2030-01-05T00:00:00Z",
        ),
        ("heart-rate", {"somethingElse": {}}, None),
    ],
)
def test_newest_by_shape(kind, point, expected):
    assert client.newest(kind, {"dataPoints": [point]}) == expected


def test_newest_rollup_takes_the_latest_window():
    page = {
        "rollupDataPoints": [
            {"endTime": "2030-01-15T00:02:00Z"},
            {"endTime": "2030-01-15T00:01:00Z"},
        ]
    }
    assert client.newest("steps", page) == "2030-01-15T00:02:00Z"


TODAY = date(2030, 1, 20)


def test_incremental_overlaps_one_day_before_newest_data():
    mark = {"newest_point_utc": "2030-01-17T09:00:00Z"}
    assert handler.incremental_days("steps", mark, TODAY) == [
        date(2030, 1, d) for d in (16, 17, 18, 19, 20)
    ]
    # list types run to tomorrow, since local days can be ahead of UTC
    assert handler.incremental_days("sleep", mark, TODAY)[-1] == date(2030, 1, 21)


def test_incremental_is_capped_and_starts_capped_without_a_watermark():
    stale = {"newest_point_utc": "2029-06-01T00:00:00Z"}  # device-only type, silent for months
    assert handler.incremental_days("steps", stale, TODAY)[0] == date(2030, 1, 13)
    assert handler.incremental_days("steps", {}, TODAY)[0] == date(2030, 1, 13)


def test_backfill_range_is_limited():
    assert len(handler.backfill_days({"start": "2030-01-01", "end": "2030-01-14"})) == 14
    for end in ("2030-01-15", "2029-12-31"):
        with pytest.raises(ValueError):
            handler.backfill_days({"start": "2030-01-01", "end": end})


def test_backfill_writes_run_objects_and_moves_watermark_forward_only(monkeypatch):
    monkeypatch.setenv("RAW_BUCKET", "test-bucket")
    monkeypatch.setenv("WATERMARK_TABLE", "test-table")
    monkeypatch.setattr(client, "access_token", lambda **creds: f"tok-{len(creds)}")
    monkeypatch.setattr(handler.time, "sleep", lambda s: None)
    point = {"heartRate": {"sampleTime": {"physicalTime": "2030-01-15T08:00:00Z"}}}
    pages = [{"dataPoints": [point], "nextPageToken": "x"}, {"dataPoints": []}]

    def fake_pages(kind, day, token):  # data on the 15th only; the 16th is empty
        return iter(pages if day == DAY else [{}])

    monkeypatch.setattr(client, "pages", fake_pages)
    s3, ddb = FakeS3(), FakeDDB()
    ddb.items["google_health#heart-rate"] = {
        "pk": {"S": "google_health#heart-rate"},
        "newest_point_utc": {"S": "2030-03-01T00:00:00Z"},  # newer than anything backfilled
    }

    event = {"start": "2030-01-15", "end": "2030-01-16"}
    counts = handler.handler(event, None, ssm=FakeSSM(), s3=s3, ddb=ddb)

    assert counts == dict.fromkeys(client.TYPES, 1)
    assert len(s3.objects) == 11  # one per type for the 15th; the empty 16th writes nothing
    key = next(
        k for k in s3.objects if k.startswith("raw/google_health/heart-rate/dt=2030-01-15/run=")
    )
    assert key.endswith("Z.jsonl.gz")
    assert [json.loads(line) for line in gzip.decompress(s3.objects[key]).splitlines()] == pages
    assert ddb.items["google_health#heart-rate"]["newest_point_utc"] == {
        "S": "2030-03-01T00:00:00Z"
    }
    assert ddb.items["google_health#sleep"]["last_run_utc"]["S"].endswith("Z")
