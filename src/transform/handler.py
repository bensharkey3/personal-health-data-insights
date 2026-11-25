"""Lambda: rebuilds curated Parquet, one file per type-month, from the latest raw file of each
type-day (D23). Each raw file is a complete day, so the newest run supersedes older ones and no
merge is needed; rebuilding the same month twice gives the same file.

Event {"days": {"<type>": ["YYYY-MM-DD", ...]}}: from ingestion, rebuilds the months touched.
Event {"start": "YYYY-MM", "end": "YYYY-MM"}: rebuilds those months for every type.
Event {"source": "tasker"}: rebuilds the Tasker tables, and the phone locations, from all their
raw files (D24, D29). Steps also read the location lines, for the phone's time zone (D29).
Logs counts only, never values."""

import os
import tempfile
from datetime import date

import boto3
import duckdb

from transform import google_health, locations, tasker

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


def latest_keys(s3, bucket: str, kind: str, month: str) -> list[str]:
    """The newest object per dt= folder. Keys sort by run timestamp, and the old step 02
    `pages.jsonl.gz` sorts before `run=...`, so it only counts when it's the only file (D19)."""
    newest: dict[str, str] = {}
    pages = s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=f"raw/{SOURCE}/{kind}/dt={month}-"
    )
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
    return rows


def handler(event: dict, context: object, s3=None) -> dict[str, int]:
    """Returns rows written per type-month. Tests pass a fake S3; Lambda passes two args."""
    s3 = s3 or boto3.client("s3")
    bucket = os.environ["RAW_BUCKET"]
    if event.get("source") == "tasker":
        return rebuild_tasker(s3, bucket)
    rows = {}
    for kind, todo in months(event).items():
        for month in sorted(todo):
            keys = latest_keys(s3, bucket, kind, month)
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
