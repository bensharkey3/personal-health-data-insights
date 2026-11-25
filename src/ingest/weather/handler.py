"""Lambda: yesterday's actual weather and today's forecast at the phone's location, from Open-Meteo
(D30), raw to S3. Runs daily at 05:00 local time.

The location is the phone's latest fix (D29), which the transform keeps in
curated/tasker/locations/latest.json. `past_days=1&forecast_days=1` with `timezone=auto` returns
yesterday and today in that place's local time, so no date maths is needed here. The response is
stored as-is in raw/weather/daily/dt=<UTC date>/run=<ts>.jsonl.gz, then the transform rebuilds
the weather table. Before the first fix there's nothing to fetch. Logs never include coordinates.

Event {} (daily) or {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} (backfill from the archive API at
the latest fix, for step 10)."""

import json
import os
import urllib.parse
from datetime import UTC, datetime
from urllib.request import Request

import boto3

from common import raw, retry

FORECAST = "https://api.open-meteo.com/v1/forecast"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"  # history, a few days' delay
LATEST_FIX = "curated/tasker/locations/latest.json"
DAILY = [
    "temperature_2m_max",
    "temperature_2m_min",
    "apparent_temperature_max",
    "precipitation_sum",
    "relative_humidity_2m_mean",
    "wind_speed_10m_max",
    "uv_index_max",
    "sunrise",
    "sunset",
    "daylight_duration",
]


def url(fix: dict, event: dict) -> str:
    query = {
        "latitude": f"{fix['lat']:.2f}",
        "longitude": f"{fix['lon']:.2f}",
        "daily": ",".join(DAILY),
        "hourly": "temperature_2m",  # for the night's temperature
        "timezone": "auto",
    }
    if "start" in event:
        base, dates = ARCHIVE, {"start_date": event["start"], "end_date": event["end"]}
    else:
        base, dates = FORECAST, {"past_days": 1, "forecast_days": 1}  # yesterday and today
    return f"{base}?{urllib.parse.urlencode(query | dates)}"


def latest_fix(s3, bucket: str) -> dict | None:
    """None before the first fix. Listed first: with ListBucket scoped to a prefix, S3 answers a
    read of a missing key with 403, not 404, so a read can't tell "missing" from "forbidden"."""
    if not s3.list_objects_v2(Bucket=bucket, Prefix=LATEST_FIX).get("KeyCount"):
        return None
    return json.loads(s3.get_object(Bucket=bucket, Key=LATEST_FIX)["Body"].read())


def handler(event: dict, context: object, s3=None, lam=None) -> dict[str, int]:
    """Returns {"days": n}. Clients can be passed in by tests; Lambda passes only two args."""
    s3, lam = s3 or boto3.client("s3"), lam or boto3.client("lambda")
    bucket = os.environ["RAW_BUCKET"]
    fix = latest_fix(s3, bucket)
    if not fix:
        print("weather: no phone location fix yet, nothing to fetch")
        return {"days": 0}
    body = retry.call(Request(url(fix, event)))  # an error after retries fails the invocation
    days = len(body.get("daily", {}).get("time", []))
    now = datetime.now(UTC)
    key = raw.key("weather", "daily", now.date(), now.strftime("%Y%m%dT%H%M%SZ"))
    with raw.Writer(s3, bucket, key) as out:
        out.write(body, days)
    print(f"weather: {days} days written")
    if days:  # async: the transform rebuilds the weather table in its own time
        lam.invoke(
            FunctionName=os.environ["TRANSFORM_FUNCTION"],
            InvocationType="Event",
            Payload=json.dumps({"source": "weather"}).encode(),
        )
    return {"days": days}
