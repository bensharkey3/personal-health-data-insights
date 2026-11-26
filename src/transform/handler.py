"""Lambda: rebuilds curated Parquet, one file per type-month, from the latest raw file of each
type-day (D23). Each raw file is a complete day, so the newest run supersedes older ones and no
merge is needed; rebuilding the same month twice gives the same file.

Event {"days": {"<type>": ["YYYY-MM-DD", ...]}}: from ingestion, rebuilds the months touched.
Event {"start": "YYYY-MM", "end": "YYYY-MM"}: rebuilds those months for every type.
Event {"source": "tasker"}: rebuilds the Tasker tables, and the phone locations, from all their
raw files (D24, D29), plus the latest fix for the 06:00 weather run (D30).
Steps also read the location lines, for the phone's time zone (D29).
Event {"source": "weather"}: rebuilds the weather table from every run (newest wins per date).
Event {"source": "tick"}: every 15 minutes; at 06:00 in the phone's current
zone it starts the daily ingest and weather runs (D31). DuckDB has the time zone data for it.
After every rebuild (not ticks), the dashboard page is rebuilt from the curated files (D33).
Logs counts only, never values."""

import json
import os
import tempfile
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import boto3
import duckdb

from dashboard import build as dashboard
from transform import google_health, locations, tasker, weather

SOURCE = "google_health"


def months(event: dict) -> dict[str, set[str]]:
    if "days" in event:
        return {kind: {d[:7] for d in days} for kind, days in event["days"].items()}
    first, last = (
        date.fromisoformat(event["start"] + "-01"),
        date.fromisoformat(event["end"] + "-01"),
    )
    todo, m = set(), first
    while m <= last:
        todo.add(m.isoformat()[:7])
        m = date(m.year + m.month // 12, m.month % 12 + 1, 1)
    return dict.fromkeys(google_health.SELECTS, todo)


def latest_keys(s3, bucket: str, prefix: str) -> list[str]:
    """The newest object per dt= folder under prefix. Keys sort by run timestamp, and the old
    step 02 `pages.jsonl.gz` sorts before `run=...`, so it only counts when it's alone (D19)."""
    newest: dict[str, str] = {}
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
    for page in pages:
        for obj in page.get("Contents", []):
            day = obj["Key"].rsplit("/", 2)[1]
            newest[day] = max(newest.get(day, ""), obj["Key"])
    return sorted(newest.values())


def write(sql: str, out: str) -> int:
    con = duckdb.connect()
    con.execute(f"COPY ({sql}) TO '{out}' (FORMAT parquet)")
    return con.execute(f"SELECT count(*) FROM '{out}'").fetchall()[0][0]


def build(kind: str, files: list[str], out: str, fix_files: list[str] = ()) -> int:
    return write(google_health.query(kind, files, fix_files), out)


def download(s3, bucket: str, keys: list[str], tmp: str, ext: str) -> list[str]:
    files = [f"{tmp}/{i}.{ext}.gz" for i in range(len(keys))]
    for key, f in zip(keys, files, strict=True):
        s3.download_file(bucket, key, f)
    return files


def tasker_keys(s3, bucket: str) -> list[str]:
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix="raw/tasker/")
    return sorted(o["Key"] for p in pages for o in p.get("Contents", []))


def rebuild_tasker(s3, bucket: str) -> dict[str, int]:
    keys, rows = tasker_keys(s3, bucket), {}
    if keys:
        with tempfile.TemporaryDirectory() as tmp:
            files = download(s3, bucket, keys, tmp, "csv")
            queries = {t: tasker.query(t, files) for t in tasker.TABLES}
            queries["locations"] = locations.query(files)
            for table, sql in queries.items():
                out = f"{tmp}/{table}.parquet"
                rows[f"tasker/{table}"] = n = write(sql, out)
                s3.upload_file(out, bucket, f"curated/tasker/{table}/data.parquet")
                print(f"tasker {table}: {n} rows from {len(keys)} batches")
            # The phone's latest fix, for the 06:00 weather run (D30); out is the locations table.
            last = duckdb.sql(
                f"SELECT lat, lon, time_zone FROM '{out}' ORDER BY local_date DESC LIMIT 1"
            ).fetchall()
            if last:
                latest = f"{tmp}/latest.json"
                fix = dict(zip(("lat", "lon", "time_zone"), last[0], strict=True))
                Path(latest).write_text(json.dumps(fix))
                s3.upload_file(latest, bucket, "curated/tasker/locations/latest.json")
    return rows


def all_keys(s3, bucket: str, prefix: str) -> list[str]:
    """Every object under prefix, oldest run first: keys sort by dt, then run timestamp."""
    pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
    return sorted(o["Key"] for p in pages for o in p.get("Contents", []))


def rebuild_weather(s3, bucket: str) -> dict[str, int]:
    keys = all_keys(s3, bucket, "raw/weather/daily/")
    air_keys = all_keys(s3, bucket, "raw/weather/air_quality/")  # D32
    if not keys:
        return {}
    with tempfile.TemporaryDirectory() as tmp:
        out = f"{tmp}/data.parquet"
        files = download(s3, bucket, keys, tmp, "jsonl")
        air = download(s3, bucket, air_keys, tmp, "air.jsonl")
        n = write(weather.query(files, air), out)
        s3.upload_file(out, bucket, "curated/weather/daily/data.parquet")
    print(f"weather: {n} days from {len(keys)} runs, {len(air_keys)} with air quality")
    return {"weather/daily": n}


DAILY_SLOT = (time(6, 0), time(6, 15))  # one 15-minute tick a day falls in this local window
LATEST_FIX = "curated/tasker/locations/latest.json"


def phone_zone(s3, bucket: str) -> str:
    """The zone of the phone's latest fix (D29), or the TIME_ZONE fallback before the first.
    The key is listed first: with ListBucket scoped to a prefix, S3 answers a read of a missing
    key with 403 Access Denied, not 404, so a read can't tell "missing" from "forbidden"."""
    if not s3.list_objects_v2(Bucket=bucket, Prefix=LATEST_FIX).get("KeyCount"):
        return locations.TIME_ZONE
    return json.loads(s3.get_object(Bucket=bucket, Key=LATEST_FIX)["Body"].read())["time_zone"]


def is_daily_slot(at: str, zone: str) -> bool:
    """Whether the scheduled UTC time `at` falls in the daily slot, local to `zone`. The time is
    parsed first, so only a clean ISO value reaches the SQL; zones come from our own files."""
    utc = datetime.fromisoformat(at.replace("Z", "+00:00")).isoformat()
    local = duckdb.sql(f"SELECT (TIMESTAMPTZ '{utc}' AT TIME ZONE '{zone}')::TIME").fetchall()
    return DAILY_SLOT[0] <= local[0][0] < DAILY_SLOT[1]


def tick(s3, lam, bucket: str, at: str) -> dict[str, int]:
    if not is_daily_slot(at, phone_zone(s3, bucket)):
        return {}
    for name in ("INGEST_FUNCTION", "WEATHER_FUNCTION"):  # async: each runs in its own time
        lam.invoke(FunctionName=os.environ[name], InvocationType="Event", Payload=b"{}")
    print("daily runs started")
    return {"daily_runs": 2}


DASHBOARD_MONTHS = 3  # Google Health months mirrored for the page: 30 shown + 30 for "usual"
STEPS_MONTHS = 13  # steps need a year, for the monthly chart; one small file a month


def publish(s3, bucket: str) -> None:
    """Rebuild the dashboard from the curated files and put it in the site bucket (D33)."""
    zone = phone_zone(s3, bucket)
    now = datetime.now(UTC)
    today = duckdb.sql(f"SELECT (TIMESTAMPTZ '{now.isoformat()}' AT TIME ZONE '{zone}')::DATE")
    today = today.fetchall()[0][0]

    def oldest(key: str) -> str:
        months = STEPS_MONTHS if "/steps/" in key else DASHBOARD_MONTHS
        return f"month={(today - timedelta(31 * months)):%Y-%m}"

    keys = [
        k
        for k in all_keys(s3, bucket, "curated/")
        if k.endswith(".parquet") and ("/month=" not in k or k.split("/")[-2] >= oldest(k))
    ]
    with tempfile.TemporaryDirectory() as tmp:
        for key in keys:  # mirror the layout, so the page's globs see the same paths
            Path(tmp, key).parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, key, str(Path(tmp, key)))
        page = dashboard.build(Path(tmp), today, f"{now:%Y-%m-%d %H:%M} UTC")
    s3.put_object(
        Bucket=os.environ["SITE_BUCKET"],
        Key="index.html",
        Body=page.encode(),
        ContentType="text/html; charset=utf-8",
        CacheControl="no-cache",  # always revalidate: the page changes with every rebuild
    )
    print(f"dashboard: built from {len(keys)} files")


def handler(event: dict, context: object, s3=None, lam=None) -> dict[str, int]:
    """Returns rows written per table. Tests pass fake clients; Lambda passes two args."""
    s3 = s3 or boto3.client("s3")
    bucket = os.environ["RAW_BUCKET"]
    if event.get("source") == "tick":
        # The current time: EventBridge Scheduler doesn't fill in its <aws.scheduler.*> placeholders
        # for a Lambda target. Tests pass "at" to pick the time.
        at = event.get("at") or datetime.now(UTC).isoformat()
        return tick(s3, lam or boto3.client("lambda"), bucket, at)
    rows = rebuild(event, s3, bucket)
    publish(s3, bucket)
    return rows


def rebuild(event: dict, s3, bucket: str) -> dict[str, int]:
    if event.get("source") == "tasker":
        return rebuild_tasker(s3, bucket)
    if event.get("source") == "weather":
        return rebuild_weather(s3, bucket)
    rows = {}
    for kind, todo in months(event).items():
        for month in sorted(todo):
            keys = latest_keys(s3, bucket, f"raw/{SOURCE}/{kind}/dt={month}-")
            if not keys:
                continue
            with tempfile.TemporaryDirectory() as tmp:  # Lambda's /tmp; removed afterwards
                files = download(s3, bucket, keys, tmp, "jsonl")
                fix_files = []  # steps need the phone's time zone (D29); the files are tiny
                if kind == "steps":
                    fix_files = download(s3, bucket, tasker_keys(s3, bucket), tmp, "fix.csv")
                out = f"{tmp}/data.parquet"
                rows[f"{kind}/{month}"] = n = build(kind, files, out, fix_files)
                s3.upload_file(out, bucket, f"curated/{SOURCE}/{kind}/month={month}/data.parquet")
            print(f"{kind} {month}: {n} rows from {len(keys)} days")
    return rows
