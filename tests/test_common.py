"""Shared helpers: retry and raw writer. Synthetic data only."""

import gzip
import io
import json
import urllib.error
from email.message import Message
from urllib.request import Request

import pytest

from common import raw, retry


def http_error(code: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError("https://example.test", code, "err", headers, io.BytesIO())


@pytest.fixture
def responses(monkeypatch):
    """Queue of responses (dicts) or errors for urlopen; records each sleep."""
    queue: list = []
    sleeps: list[float] = []

    def fake_urlopen(req, timeout):
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return io.BytesIO(json.dumps(item).encode())

    monkeypatch.setattr(retry, "urlopen", fake_urlopen)
    monkeypatch.setattr(retry.time, "sleep", sleeps.append)
    monkeypatch.setattr(retry.random, "random", lambda: 0.5)
    return queue, sleeps


def test_retries_429_and_5xx_with_backoff(responses):
    queue, sleeps = responses
    queue += [http_error(429), http_error(503), http_error(429, "7"), {"ok": True}]
    assert retry.call(Request("https://example.test")) == {"ok": True}
    assert sleeps == [1.5, 2.5, 7.0]  # 2^0 + jitter, 2^1 + jitter, then Retry-After


def test_gives_up_after_retries(responses):
    queue, sleeps = responses
    queue += [http_error(500)] * (retry.RETRIES + 1)
    with pytest.raises(urllib.error.HTTPError):
        retry.call(Request("https://example.test"))
    assert len(sleeps) == retry.RETRIES


def test_does_not_retry_other_errors(responses):
    queue, sleeps = responses
    queue.append(http_error(400))
    with pytest.raises(urllib.error.HTTPError):
        retry.call(Request("https://example.test"))
    assert sleeps == []


class FakeS3:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[Key] = Body


def test_writer_uploads_only_successful_non_empty_blocks():
    s3 = FakeS3()
    with raw.Writer(s3, "b", "full") as out:
        out.write({"a": 1}, 1)
        out.write({}, 0)
    with raw.Writer(s3, "b", "empty") as out:
        out.write({}, 0)
    with pytest.raises(RuntimeError), raw.Writer(s3, "b", "failed") as out:
        out.write({"a": 1}, 1)
        raise RuntimeError
    assert list(s3.objects) == ["full"]
    assert gzip.decompress(s3.objects["full"]).splitlines() == [b'{"a": 1}', b"{}"]
