"""Lambda: incremental or backfill load of every in-scope Google Health type into raw S3.

Event {} (incremental): per type, from one day before its newest data point to today (D20).
Event {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} (backfill): those days inclusive, slowly.
Each type-day with data becomes one new object (common.raw), then the type's watermark is
updated. Logs counts only, never tokens or values."""

import os
import time
import urllib.error
from datetime import UTC, date, datetime, timedelta

import boto3

from common import raw, watermark
from ingest.google_health import client

SOURCE = "google_health"
PARAMS = "/phdi/google/"  # created by hand (D15)
MAX_LOOKBACK_DAYS = 7  # a device silent for longer than this needs a backfill instead
BACKFILL_MAX_DAYS = 14  # a fortnight of all types takes about 11 min of Lambda's 15
BACKFILL_PAUSE_S = 1.0  # between type-days, to stay well under rate limits (D2)


def credentials(ssm) -> dict[str, str]:
    names = [PARAMS + n for n in ("client_id", "client_secret", "refresh_token")]
    resp = ssm.get_parameters(Names=names, WithDecryption=True)
    if resp["InvalidParameters"]:
        raise RuntimeError(f"Missing SSM parameters: {resp['InvalidParameters']}")
    return {p["Name"].removeprefix(PARAMS): p["Value"] for p in resp["Parameters"]}


def days(start: date, end: date) -> list[date]:
    return [start + timedelta(n) for n in range((end - start).days + 1)]


def incremental_days(kind: str, mark: dict, today: date) -> list[date]:
    """The overlap is measured from the newest data, not from now, so data that syncs days late
    is still fetched. List types filter on local days, which can be ahead of UTC, so they run to
    tomorrow's date; steps run on UTC days (D17)."""
    floor = today - timedelta(MAX_LOOKBACK_DAYS)
    start = floor
    if newest := mark.get("newest_point_utc"):
        start = max(date.fromisoformat(newest[:10]) - timedelta(client.OVERLAP_DAYS[kind]), floor)
    end = today if kind in client.ROLLUP_TYPES else today + timedelta(1)
    return days(min(start, end), end)


def backfill_days(event: dict) -> list[date]:
    todo = days(date.fromisoformat(event["start"]), date.fromisoformat(event["end"]))
    if not 0 < len(todo) <= BACKFILL_MAX_DAYS:
        raise ValueError(f"Backfill takes 1 to {BACKFILL_MAX_DAYS} days, got {len(todo)}")
    return todo


def handler(event: dict, context: object, ssm=None, s3=None, ddb=None) -> dict[str, int]:
    """Returns points per type. Clients can be passed in by tests; Lambda passes only two args."""
    ssm, s3 = ssm or boto3.client("ssm"), s3 or boto3.client("s3")
    ddb = ddb or boto3.client("dynamodb")
    bucket, table = os.environ["RAW_BUCKET"], os.environ["WATERMARK_TABLE"]
    now = datetime.now(UTC)
    run = now.strftime("%Y%m%dT%H%M%SZ")
    backfill = backfill_days(event) if "start" in event else None
    token = client.access_token(**credentials(ssm))

    counts, failed = {}, []
    for kind in client.TYPES:
        mark = watermark.get(ddb, table, SOURCE, kind)
        todo = backfill or incremental_days(kind, mark, now.date())
        points, newest = 0, None
        try:
            for day in todo:
                with raw.Writer(s3, bucket, raw.key(SOURCE, kind, day, run)) as out:
                    for page in client.pages(kind, day, token):
                        out.write(page, n := client.count(page))  # := assigns and passes n
                        points += n
                        newest = max(
                            filter(None, [newest, client.newest(kind, page)]), default=None
                        )
                if backfill:
                    time.sleep(BACKFILL_PAUSE_S)
        except urllib.error.HTTPError as e:  # after retries; Google's error body has no tokens
            print(f"{kind}: HTTP {e.code} {e.read().decode()[:300]}")
            failed.append(kind)
            continue
        watermark.put(ddb, table, SOURCE, kind, mark, now.strftime("%Y-%m-%dT%H:%M:%SZ"), newest)
        counts[kind] = points
        print(f"{kind}: {points} points over {len(todo)} days {todo[0]}..{todo[-1]}")
    if failed:
        raise RuntimeError(f"Failed types: {failed}")  # marks the invocation as failed
    return counts
