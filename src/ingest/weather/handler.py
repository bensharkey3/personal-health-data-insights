"""Lambda: weather at the phone's location for each date, from Open-Meteo (D30), raw to S3.

Event {"days": [{"date": "YYYY-MM-DD", "lat": ..., "lon": ...}, ...]}: sent by the transform
after each phone batch, with each date's location (D29); a backfill can send the same shape. One
request per date covers that date and the evening before, for the night's temperature, with
`timezone=auto` so hours are local to that place. Each response is stored as-is in
raw/weather/daily/dt=<date>/run=<ts>.jsonl.gz, then the transform rebuilds the weather table.
Logs counts only, never coordinates."""

import json
import os
import urllib.error
import urllib.parse
from datetime import UTC, date, datetime, timedelta
from urllib.request import Request

import boto3

from common import raw, retry

FORECAST = "https://api.open-meteo.com/v1/forecast"  # recent days, incl. today
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"  # older history, a few days' delay
ARCHIVE_AFTER_DAYS = 60  # the forecast API only reaches a few months back
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


def url(day: dict, today: date) -> str:
    d = date.fromisoformat(day["date"])
    query = {
        "latitude": f"{day['lat']:.2f}",
        "longitude": f"{day['lon']:.2f}",
        "start_date": (d - timedelta(1)).isoformat(),
        "end_date": d.isoformat(),
        "daily": ",".join(DAILY),
        "hourly": "temperature_2m",
        "timezone": "auto",
    }
    base = ARCHIVE if (today - d).days > ARCHIVE_AFTER_DAYS else FORECAST
    return f"{base}?{urllib.parse.urlencode(query)}"


def handler(event: dict, context: object, s3=None, lam=None) -> dict[str, int]:
    """Returns {"written": n}. Clients can be passed in by tests; Lambda passes only two args."""
    s3, lam = s3 or boto3.client("s3"), lam or boto3.client("lambda")
    now = datetime.now(UTC)
    run = now.strftime("%Y%m%dT%H%M%SZ")
    written, failed = 0, []
    for day in event.get("days", []):
        try:
            body = retry.call(Request(url(day, now.date())))
        except urllib.error.HTTPError as e:  # after retries; the body has no secrets
            print(f"{day['date']}: HTTP {e.code} {e.read().decode()[:300]}")
            failed.append(day["date"])
            continue
        key = raw.key("weather", "daily", date.fromisoformat(day["date"]), run)
        with raw.Writer(s3, os.environ["RAW_BUCKET"], key) as out:
            out.write(body, len(body.get("daily", {}).get("time", [])))
        written += 1
    print(f"weather: {written} days written, {len(failed)} failed")
    if written:  # async: the transform rebuilds the weather table in its own time
        lam.invoke(
            FunctionName=os.environ["TRANSFORM_FUNCTION"],
            InvocationType="Event",
            Payload=json.dumps({"source": "weather"}).encode(),
        )
    if failed:
        raise RuntimeError(f"Failed dates: {failed}")  # marks the invocation as failed
    return {"written": written}
