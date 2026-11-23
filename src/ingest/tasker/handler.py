"""Lambda behind a function URL: receives the phone's nightly Tasker batch (D24) and stores it raw.

The body is CSV, one `<UTC epoch seconds>,<event>` line per screen on/off or home/office Wi-Fi
change. It's stored gzipped exactly as sent, then the transform rebuilds the Tasker tables. A
body with no valid lines writes nothing. Logs line counts only."""

import base64
import gzip
import json
import os
import re
from datetime import UTC, datetime

import boto3

from common import auth, raw

SECRET_PARAM = "/phdi/tasker/secret"  # created by hand (D15), e.g. "Bearer <random>"
LINE = re.compile(r"^\d{9,11},(screen|home|office)_(on|off)$")


def handler(event: dict, context: object, ssm=None, s3=None, lam=None) -> dict:
    """Clients can be passed in by tests; Lambda passes only two args."""
    ssm = ssm or boto3.client("ssm")
    if not auth.authorised(event.get("headers") or {}, ssm, SECRET_PARAM):
        print("Rejected: bad or missing secret")
        return {"statusCode": 401}
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode()
    lines = body.strip().splitlines()
    valid = sum(bool(LINE.match(line.strip())) for line in lines)
    print(f"{len(lines)} lines, {valid} valid")
    if not valid:
        return {"statusCode": 204}

    now = datetime.now(UTC)
    s3, lam = s3 or boto3.client("s3"), lam or boto3.client("lambda")
    key = raw.key("tasker", "events", now.date(), now.strftime("%Y%m%dT%H%M%SZ"), ext="csv")
    s3.put_object(Bucket=os.environ["RAW_BUCKET"], Key=key, Body=gzip.compress(body.encode()))
    lam.invoke(  # async: the phone only needs to know the batch is stored
        FunctionName=os.environ["TRANSFORM_FUNCTION"],
        InvocationType="Event",
        Payload=json.dumps({"source": "tasker"}).encode(),
    )
    return {"statusCode": 204}
