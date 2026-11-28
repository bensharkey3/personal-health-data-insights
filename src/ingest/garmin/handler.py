"""Lambda: Garmin activities from Garmin's official Personal API (D39), raw to S3.

The personal API key (made in Garmin Connect, renewed yearly) is swapped for a 24-hour bearer
token, then the activity list is paged through for a date range. Each run stores the pages as-is
in raw/garmin/activities/dt=<UTC date>/run=<ts>.jsonl.gz; the transform keeps the newest copy of
each activity. Started daily at 06:00 by the transform's tick (D31).

Event {} (incremental): from one day before the newest activity seen (watermark) to tomorrow,
at most a week back, like D20. Event {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}: backfill.
Logs counts only, never the key, token or activity details."""

import json
import os
import urllib.error
import urllib.parse
from datetime import UTC, date, datetime, timedelta
from urllib.request import Request

import boto3

from common import raw, retry, watermark

SOURCE, KIND = "garmin", "activities"
BASE = "https://personal.connectapi.garmin.com"
TOKEN_PATH = "/personalapitoken-service/personal-api/personal-api-key/token"
LIST_PATH = "/activitylist-service/activities/search/activities"
KEY_PARAM = "/phdi/garmin/api_key"  # created by hand (D15, D39)
PAGE = 100
LOOKBACK_DAYS = 7


def token(api_key: str) -> str:
    """The reply is the bare JWT, not JSON; Garmin issues no refresh tokens."""
    req = Request(BASE + TOKEN_PATH, method="POST", headers={"Authorization": f"ApiKey {api_key}"})
    return retry.call(req, text=True)


def window(event: dict, mark: dict, today: date) -> tuple[date, date]:
    if "start" in event:
        return date.fromisoformat(event["start"]), date.fromisoformat(event["end"])
    floor = today - timedelta(LOOKBACK_DAYS)
    newest = mark.get("newest_point_utc")
    start = date.fromisoformat(newest[:10]) - timedelta(1) if newest else floor
    # Tomorrow: local start dates can be a day ahead of UTC (east of Greenwich).
    return max(start, floor), today + timedelta(1)


def pages(bearer: str, start: date, end: date):
    """Pages of activities, `start` being a zero-based offset; an empty page ends the list."""
    offset = 0
    while True:
        query = {"start": offset, "limit": PAGE, "startDate": start, "endDate": end}
        url = f"{BASE}{LIST_PATH}?{urllib.parse.urlencode(query)}"
        page = retry.call(Request(url, headers={"Authorization": f"Bearer {bearer}"}))
        if not page:
            return
        yield page
        offset += len(page)


def gmt(activity: dict) -> str | None:
    """ "2030-01-14 07:00:00" (UTC) as ISO, for the watermark."""
    t = activity.get("startTimeGMT")
    return t.replace(" ", "T") + "Z" if t else None


def handler(event: dict, context: object, ssm=None, s3=None, ddb=None, lam=None) -> dict[str, int]:
    """Returns {"activities": n}. Clients can be passed in by tests; Lambda passes only two args."""
    ssm, s3 = ssm or boto3.client("ssm"), s3 or boto3.client("s3")
    ddb, lam = ddb or boto3.client("dynamodb"), lam or boto3.client("lambda")
    bucket, table = os.environ["RAW_BUCKET"], os.environ["WATERMARK_TABLE"]
    now = datetime.now(UTC)
    run = now.strftime("%Y%m%dT%H%M%SZ")
    mark = watermark.get(ddb, table, SOURCE, KIND)
    start, end = window(event, mark, now.date())
    api_key = ssm.get_parameter(Name=KEY_PARAM, WithDecryption=True)["Parameter"]["Value"]
    try:
        bearer = token(api_key)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise RuntimeError("Garmin rejected the API key: renew it (spec 11)") from None
        raise
    count, newest = 0, None
    with raw.Writer(s3, bucket, raw.key(SOURCE, KIND, now.date(), run)) as out:
        for page in pages(bearer, start, end):
            out.write({"activities": page}, len(page))
            count += len(page)
            newest = max(filter(None, [newest, *map(gmt, page)]), default=None)
    watermark.put(ddb, table, SOURCE, KIND, mark, now.strftime("%Y-%m-%dT%H:%M:%SZ"), newest)
    print(f"garmin: {count} activities {start}..{end}")
    if count:  # async: the transform rebuilds the table in its own time
        lam.invoke(
            FunctionName=os.environ["TRANSFORM_FUNCTION"],
            InvocationType="Event",
            Payload=json.dumps({"source": "garmin"}).encode(),
        )
    return {"activities": count}
