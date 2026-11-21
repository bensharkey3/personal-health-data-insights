"""Google Health API v4 client (stdlib only): token refresh, and one day of a data type fetched a
page at a time. Filter fields and page limits are from docs/google-health-api.md."""

import json
import urllib.parse
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from urllib.request import Request, urlopen

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://health.googleapis.com/v4/users/me/dataTypes"

# In-scope types (D13) fetched with `list`, by record shape; the shape decides the filter field.
LIST_TYPES = {
    "heart-rate": "sample",
    "daily-resting-heart-rate": "daily",
    "heart-rate-variability": "sample",
    "daily-heart-rate-variability": "daily",
    "sleep": "session",
    "oxygen-saturation": "sample",
    "daily-oxygen-saturation": "daily",
    "daily-respiratory-rate": "daily",
    "respiratory-rate-sleep-summary": "sample",
    "daily-sleep-temperature-derivations": "daily",
}
ROLLUP_TYPES = ("steps",)  # interval types use rollUp in fixed windows (D12)
TYPES = (*LIST_TYPES, *ROLLUP_TYPES)


def _call(req: Request) -> dict:
    with urlopen(req, timeout=60) as resp:
        return json.load(resp)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    form = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    return _call(Request(TOKEN_URL, data=urllib.parse.urlencode(form).encode()))["access_token"]


def day_filter(kind: str, day: date) -> str:
    """Filter for one local (civil) day; sleep counts toward the day it ends (D3)."""
    snake, shape, nxt = kind.replace("-", "_"), LIST_TYPES[kind], day + timedelta(days=1)
    if shape == "daily":
        field, lo, hi = f"{snake}.date", str(day), str(nxt)  # daily dates only take >= and <
    else:
        end = "sample_time.civil_time" if shape == "sample" else "interval.civil_end_time"
        field, lo, hi = f"{snake}.{end}", f"{day}T00:00:00", f"{nxt}T00:00:00"
    return f'{field} >= "{lo}" AND {field} < "{hi}"'


def list_pages(kind: str, day: date, token: str) -> Iterator[dict]:
    """Yields raw response pages. A page can be empty while more follow, so only the absence of
    nextPageToken ends the loop."""
    query = {"filter": day_filter(kind, day), "pageSize": 25 if kind == "sleep" else 5000}
    while True:
        qs = urllib.parse.urlencode(query, quote_via=urllib.parse.quote)  # spaces as %20
        body = _call(Request(f"{API}/{kind}/dataPoints?{qs}", headers=_auth(token)))
        yield body
        if not (page := body.get("nextPageToken")):  # := assigns and tests in one step
            return
        query["pageToken"] = page


def rollup_pages(kind: str, day: date, token: str) -> Iterator[dict]:
    """60-second windows over the UTC day: rollUp only takes UTC timestamps (D17)."""
    start = datetime.combine(day, time(), UTC)
    stamp = "%Y-%m-%dT%H:%M:%SZ"
    payload: dict = {
        "range": {
            "startTime": start.strftime(stamp),
            "endTime": (start + timedelta(days=1)).strftime(stamp),
        },
        "windowSize": "60s",
        "pageSize": 10000,  # a day is 1,440 windows, so normally one page
    }
    while True:
        data = json.dumps(payload).encode()
        body = _call(Request(f"{API}/{kind}/dataPoints:rollUp", data=data, headers=_auth(token)))
        yield body
        if not (page := body.get("nextPageToken")):
            return
        payload["pageToken"] = page


def pages(kind: str, day: date, token: str) -> Iterator[dict]:
    return (rollup_pages if kind in ROLLUP_TYPES else list_pages)(kind, day, token)


def count(page: dict) -> int:
    return len(page.get("dataPoints", page.get("rollupDataPoints", [])))
