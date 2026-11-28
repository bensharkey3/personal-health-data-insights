"""Lambda behind the dashboard's /refresh route (D37): starts an incremental Google Health run
and a weather run, each of which rebuilds the page through the transform when it finishes.

CloudFront is its only caller (function URL with IAM auth and origin access control), behind
the dashboard's password. A 5-minute cooldown stops repeated taps or reloads from hammering
Google. Phone data can't be pulled: the phone sends it (D25). The reply is a small page that
returns to the dashboard once the rebuild should be done."""

import os
from datetime import UTC, datetime, timedelta

import boto3

from common import watermark

COOLDOWN = timedelta(minutes=5)
COOLDOWN_KEY = "dashboard#refresh"  # an item in the watermark table, separate from the webhook's
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta http-equiv="refresh" content="{wait};url=/"><title>Refresh</title>
<style>body{{margin:0;padding:16px;font:15px/1.4 system-ui,sans-serif;background:#f6f7f9;
color:#1d2330}}@media (prefers-color-scheme:dark){{body{{background:#11151c;color:#e6e9ef}}}}
a{{color:inherit}}</style></head>
<body><p>{message}</p><p><a href="/">Back now</a></p></body></html>"""


def page(message: str, wait: int) -> dict:
    return {
        "statusCode": 200,
        "headers": {"content-type": "text/html; charset=utf-8", "cache-control": "no-store"},
        "body": PAGE.format(message=message, wait=wait),
    }


def handler(event: dict, context: object, ddb=None, lam=None) -> dict:
    """Clients can be passed in by tests; Lambda passes only two args."""
    ddb = ddb or boto3.client("dynamodb")
    if not watermark.claim(
        ddb, os.environ["WATERMARK_TABLE"], COOLDOWN_KEY, COOLDOWN, datetime.now(UTC)
    ):
        print("refresh: skipped, one was started in the last 5 minutes")
        return page("Refreshed a few minutes ago, so the page is as fresh as it gets.", 5)
    lam = lam or boto3.client("lambda")
    for name in (os.environ["INGEST_FUNCTION"], os.environ["WEATHER_FUNCTION"]):
        lam.invoke(FunctionName=name, InvocationType="Event", Payload=b"{}")  # async
    print("refresh: started the Google Health and weather runs")
    return page("Refreshing Fitbit and weather… back to the dashboard in 90 seconds.", 90)
