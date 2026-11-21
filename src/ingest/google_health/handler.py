"""Lambda: pull one day of every in-scope Google Health type into raw S3. Invoked by hand for now.

Event: {"date": "YYYY-MM-DD"}, default yesterday (UTC). Each type-day is one gzipped JSON Lines
object, one API page per line: raw/google_health/<type>/dt=<date>/pages.jsonl.gz. Pages stream
into the gzip buffer, so memory holds one page at a time (gzip shrinks this data about 50x).
A rerun for the same date overwrites the same keys. Logs counts only, never tokens."""

import gzip
import io
import json
import os
import urllib.error
from datetime import UTC, date, datetime, timedelta

import boto3

from ingest.google_health import client

PARAMS = "/phdi/google/"  # created by hand (D15)


def credentials(ssm) -> dict[str, str]:
    names = [PARAMS + n for n in ("client_id", "client_secret", "refresh_token")]
    resp = ssm.get_parameters(Names=names, WithDecryption=True)
    if resp["InvalidParameters"]:
        raise RuntimeError(f"Missing SSM parameters: {resp['InvalidParameters']}")
    return {p["Name"].removeprefix(PARAMS): p["Value"] for p in resp["Parameters"]}


def key(kind: str, day: date) -> str:
    return f"raw/google_health/{kind}/dt={day}/pages.jsonl.gz"


def handler(event: dict, context: object, ssm=None, s3=None) -> dict[str, int]:
    """Returns points per type. ssm/s3 can be passed in by tests; Lambda passes only two args."""
    ssm, s3 = ssm or boto3.client("ssm"), s3 or boto3.client("s3")
    day = date.fromisoformat(event.get("date") or str(datetime.now(UTC).date() - timedelta(1)))
    token = client.access_token(**credentials(ssm))

    counts, failed = {}, []
    for kind in client.TYPES:
        buf, points, n_pages = io.BytesIO(), 0, 0
        try:
            with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
                for page in client.pages(kind, day, token):
                    gz.write(json.dumps(page).encode() + b"\n")
                    points, n_pages = points + client.count(page), n_pages + 1
        except urllib.error.HTTPError as e:  # Google's error body has no tokens in it
            print(f"{kind}: HTTP {e.code} {e.read().decode()[:300]}")
            failed.append(kind)
            continue
        s3.put_object(Bucket=os.environ["RAW_BUCKET"], Key=key(kind, day), Body=buf.getvalue())
        counts[kind] = points
        print(f"{kind}: {points} points in {n_pages} pages")
    if failed:
        raise RuntimeError(f"Failed types: {failed}")  # marks the invocation as failed
    return counts
