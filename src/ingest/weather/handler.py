"""Lambda: yesterday's actual weather and today's forecast at the phone's location, plus hourly air
quality for the same days, from Open-Meteo (D30, D32), and the place's name from OpenStreetMap
Nominatim (D35), raw to S3. Runs daily at 06:00 local time.

The location is the phone's latest fix (D29), which the transform keeps in
curated/tasker/locations/latest.json. `past_days=1&forecast_days=1` with `timezone=auto` returns
yesterday and today in that place's local time, so no date maths is needed here. The response is
stored as-is in raw/weather/daily/dt=<UTC date>/run=<ts>.jsonl.gz and the air quality reply in
raw/weather/air_quality/..., then the transform rebuilds the weather table. Before the
first fix there's nothing to fetch. Logs never include coordinates.

Event {} (daily) or {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} (backfill from the archive API at
the latest fix, for step 10)."""

import json
import os
import urllib.error
import urllib.parse
from datetime import UTC, datetime
from urllib.request import Request

import boto3

from common import raw, retry

FORECAST = "https://api.open-meteo.com/v1/forecast"
ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"  # history, a few days' delay
AIR = "https://air-quality-api.open-meteo.com/v1/air-quality"  # modelled (CAMS) outside Europe
AIR_HOURLY = ["pm2_5", "pm10", "ozone", "nitrogen_dioxide", "us_aqi"]
PLACE = "https://nominatim.openstreetmap.org/reverse"  # OpenStreetMap, free, fair use (D35)
USER_AGENT = "phdi-weather/1.0"  # Nominatim asks apps to identify themselves; nothing personal
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


def _dates(event: dict) -> dict:
    if "start" in event:
        return {"start_date": event["start"], "end_date": event["end"]}
    return {"past_days": 1, "forecast_days": 1}  # yesterday and today


def _place(fix: dict) -> dict:
    return {"latitude": f"{fix['lat']:.2f}", "longitude": f"{fix['lon']:.2f}", "timezone": "auto"}


def url(fix: dict, event: dict) -> str:
    query = (
        _place(fix)
        | _dates(event)
        | {
            "daily": ",".join(DAILY),
            "hourly": "temperature_2m",  # for the night's temperature
        }
    )
    base = ARCHIVE if "start" in event else FORECAST
    return f"{base}?{urllib.parse.urlencode(query)}"


def air_url(fix: dict, event: dict) -> str:
    query = _place(fix) | _dates(event) | {"hourly": ",".join(AIR_HOURLY)}
    return f"{AIR}?{urllib.parse.urlencode(query)}"


def place_url(fix: dict) -> str:
    """Reverse geocoding at suburb level (zoom 14), in English, for the dashboard's heading."""
    query = {"lat": f"{fix['lat']:.2f}", "lon": f"{fix['lon']:.2f}", "zoom": 14}
    return (
        f"{PLACE}?{urllib.parse.urlencode(query | {'format': 'jsonv2', 'accept-language': 'en'})}"
    )


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
    now = datetime.now(UTC)
    run = now.strftime("%Y%m%dT%H%M%SZ")

    def store(kind: str, body: dict, records: int) -> None:
        with raw.Writer(s3, bucket, raw.key("weather", kind, now.date(), run)) as out:
            out.write(body, records)

    body = retry.call(Request(url(fix, event)))  # an error after retries fails the invocation
    days = len(body.get("daily", {}).get("time", []))
    store("daily", body, days)
    air_error = None
    try:  # after the weather is safely stored, so an air quality outage doesn't lose it
        air = retry.call(Request(air_url(fix, event)))
        store("air_quality", air, len(air.get("hourly", {}).get("time", [])))
    except urllib.error.HTTPError as e:
        air_error = f"HTTP {e.code} {e.read().decode()[:300]}"
    try:  # the place name is only a label, so a failure is logged, not raised (D35)
        place = retry.call(Request(place_url(fix), headers={"User-Agent": USER_AGENT}))
        store("place", place, 1 if place.get("address") else 0)
    except urllib.error.HTTPError as e:
        print(f"place: HTTP {e.code}")  # the reply body could name the place, so it's not logged
    print(f"weather: {days} days written; air quality {air_error or 'written'}")
    if days:  # async: the transform rebuilds the weather table in its own time
        lam.invoke(
            FunctionName=os.environ["TRANSFORM_FUNCTION"],
            InvocationType="Event",
            Payload=json.dumps({"source": "weather"}).encode(),
        )
    if air_error:
        raise RuntimeError(f"Air quality failed: {air_error}")  # fails the run, so it alarms
    return {"days": days}
