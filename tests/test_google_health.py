"""Google Health client and handler, with fake HTTP, SSM and S3. Synthetic data only."""

import gzip
import io
import json
import urllib.parse
from datetime import date

import pytest

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

    monkeypatch.setattr(client, "urlopen", fake_urlopen)
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
        self.objects[Key] = Body


def test_handler_writes_one_object_per_type(monkeypatch):
    monkeypatch.setenv("RAW_BUCKET", "test-bucket")
    monkeypatch.setattr(client, "access_token", lambda **creds: f"tok-{len(creds)}")
    pages = [{"dataPoints": [{"n": 1}], "nextPageToken": "x"}, {"dataPoints": [{"n": 2}]}]
    monkeypatch.setattr(client, "pages", lambda kind, day, token: iter(pages))
    s3 = FakeS3()

    counts = handler.handler({"date": "2030-01-15"}, None, ssm=FakeSSM(), s3=s3)

    assert counts == {kind: 2 for kind in client.TYPES}
    body = s3.objects["raw/google_health/heart-rate/dt=2030-01-15/pages.jsonl.gz"]
    assert [json.loads(line) for line in gzip.decompress(body).splitlines()] == pages
    assert len(s3.objects) == 11
