"""Tasker receiver and transform. Synthetic events only."""

import gzip
import json
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pytest

from common import auth
from ingest.tasker import handler as receiver
from transform import handler as transform
from transform import tasker

SECRET = "Bearer test-secret"


def epoch(*args) -> int:  # UTC
    return int(datetime(*args, tzinfo=UTC).timestamp())


class FakeSSM:
    def get_parameter(self, Name, WithDecryption):
        return {"Parameter": {"Value": SECRET}}


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[Key] = Body


class FakeLambda:
    def __init__(self):
        self.invokes = []

    def invoke(self, **kw):
        self.invokes.append(kw)


@pytest.fixture
def post(monkeypatch):
    monkeypatch.setattr(auth, "_cache", {})
    monkeypatch.setenv("RAW_BUCKET", "b")
    monkeypatch.setenv("TRANSFORM_FUNCTION", "transform")
    s3, lam = FakeS3(), FakeLambda()

    def call(body, auth_header=SECRET):
        event = {"headers": {"authorization": auth_header} if auth_header else {}, "body": body}
        return receiver.handler(event, None, ssm=FakeSSM(), s3=s3, lam=lam)["statusCode"]

    return call, s3, lam


def test_rejects_missing_secret(post):
    call, s3, _ = post
    assert call("1900000000,screen_on", auth_header=None) == 401
    assert s3.objects == {}


def test_stores_batch_raw_and_starts_transform(post):
    call, s3, lam = post
    body = "1900000000,screen_on\n1900000060,screen_off\n"
    assert call(body) == 204
    [(key, data)] = s3.objects.items()
    assert key.startswith("raw/tasker/events/dt=") and key.endswith("Z.csv.gz")
    assert gzip.decompress(data).decode() == body  # stored exactly as sent
    assert json.loads(lam.invokes[0]["Payload"]) == {"source": "tasker"}


def test_empty_or_invalid_body_writes_nothing(post):
    call, s3, lam = post
    assert call("") == 204 and call("hello,world") == 204
    assert s3.objects == {} and lam.invokes == []


def rows(tmp_path, table: str, lines: list[str]) -> list[dict]:
    path = tmp_path / "batch.csv.gz"
    path.write_bytes(gzip.compress(("\n".join(lines) + "\n").encode()))
    out = str(tmp_path / "out.parquet").replace("\\", "/")
    transform.write(tasker.query(table, [str(path).replace("\\", "/")]), out)
    rel = duckdb.sql(f"SELECT * FROM '{out}'")
    return [dict(zip(rel.columns, r, strict=True)) for r in rel.fetchall()]


def test_screen_sessions_pair_dedupe_and_drop_bad_lines(tmp_path):
    on, off = epoch(2030, 1, 15, 12, 0), epoch(2030, 1, 15, 12, 30)  # 23:00 local (+11h)
    lines = [
        f"{on},screen_on",
        f"{off},screen_off",
        f"{on},screen_on",  # a re-sent batch repeats lines
        "garbage",
        f"{off + 60},screen_on",  # never switched off: dropped
        f"{off + 120},screen_on",
        f"{off + 180},screen_off",
    ]
    got = rows(tmp_path, "screen_sessions", lines)
    assert [r["minutes"] for r in got] == [30.0, 1.0]
    assert got[0]["local_date"] == date(2030, 1, 15) and got[0]["start_hour_local"] == 23


def test_places_by_label(tmp_path):
    lines = [
        f"{epoch(2030, 1, 14, 22)},office_on",
        f"{epoch(2030, 1, 15, 6)},office_off",
        f"{epoch(2030, 1, 15, 7)},home_on",
        f"{epoch(2030, 1, 15, 7, 1)},screen_on",  # other things don't interfere
        f"{epoch(2030, 1, 15, 21)},home_off",
    ]
    got = rows(tmp_path, "places", lines)
    assert [(r["place"], r["minutes"], r["local_date"]) for r in got] == [
        ("office", 480.0, date(2030, 1, 15)),
        ("home", 840.0, date(2030, 1, 15)),
    ]


# --- Tasker project file (D28) ---

PROJECT = Path(__file__).parent.parent / "src/ingest/tasker/phdi.prj.xml"


def test_tasker_project_is_wired_and_logs_what_the_receiver_accepts():
    root = ET.parse(PROJECT).getroot()
    profiles = {p.findtext("id"): p for p in root.iter("Profile")}
    tasks = {t.findtext("id"): t for t in root.iter("Task")}
    project = root.find("Project")
    assert project.findtext("pids").split(",") == list(profiles)
    assert project.findtext("tids").split(",") == list(tasks)
    for p in profiles.values():  # every entry (mid0) and exit (mid1) task exists
        assert {p.findtext(m) for m in ("mid0", "mid1") if p.find(m) is not None} <= tasks.keys()
    for a in root.iter("Action"):
        if a.findtext("code") == "410":  # Write File; %TIMES is epoch seconds on the phone
            line = a.find("Str[@sr='arg1']").text.replace("%TIMES", "1795000000")
            assert receiver.LINE.match(line), line


def test_tasker_project_holds_nothing_private():
    """Guards re-exports from the phone: no URL or secret, and Wi-Fi names back to placeholders."""
    text = PROJECT.read_text()
    for banned in ("http://", "https://", "lambda-url", "Bearer", "amazonaws"):
        assert banned not in text, banned
    wifi = [s for s in ET.parse(PROJECT).iter("State") if s.findtext("code") == "160"]
    names = {s.find("Str[@sr='arg0']").text for s in wifi}
    assert names == {"SET_HOME_SSID", "SET_OFFICE_SSID"}
