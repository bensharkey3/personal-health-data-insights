"""Lambda behind a function URL: receives Google Health webhook notifications and starts an
incremental ingestion run, at most once per 3 hours (D22).

Only Fitbit device types trigger a run; phone steps are picked up by the daily schedule instead.
Google sends our secret in the Authorization header: verification POSTs expect 201 with it and
401 without it, and notifications with a bad secret get 401 so Google discards them. Logs counts
and data types only, never headers or user IDs."""

import base64
import hmac
import json
import os
from datetime import UTC, datetime, timedelta

import boto3
from botocore.exceptions import ClientError

from ingest.google_health import client

SECRET_PARAM = "/phdi/google/webhook_secret"  # created by hand (D15), e.g. "Bearer <random>"
COOLDOWN = timedelta(hours=3)
COOLDOWN_KEY = {"pk": {"S": "google_health#webhook"}}  # lives in the watermark table
_secret: str | None = None  # cached for the life of the Lambda container


def _authorised(headers: dict, ssm) -> bool:
    global _secret
    if _secret is None:
        _secret = ssm.get_parameter(Name=SECRET_PARAM, WithDecryption=True)["Parameter"]["Value"]
    # Function URLs lower-case header names. compare_digest avoids leaking the secret by timing.
    return hmac.compare_digest(headers.get("authorization", ""), _secret)


def _claim_cooldown(ddb, table: str, now: datetime) -> bool:
    """Atomically records this trigger unless one happened in the last 3 hours, so parallel
    POSTs can't both start a run. ISO UTC strings compare in time order."""
    try:
        ddb.update_item(
            TableName=table,
            Key=COOLDOWN_KEY,
            UpdateExpression="SET last_trigger_utc = :now",
            ConditionExpression="attribute_not_exists(last_trigger_utc) OR last_trigger_utc < :cut",
            ExpressionAttributeValues={
                ":now": {"S": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
                ":cut": {"S": (now - COOLDOWN).strftime("%Y-%m-%dT%H:%M:%SZ")},
            },
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def handler(event: dict, context: object, ssm=None, ddb=None, lam=None) -> dict:
    """Clients can be passed in by tests; Lambda passes only two args."""
    ssm, ddb, lam = ssm or boto3.client("ssm"), ddb or boto3.client("dynamodb"), lam
    body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode()
    if not _authorised(event.get("headers") or {}, ssm):
        print("Rejected: bad or missing secret")
        return {"statusCode": 401}
    payload = json.loads(body or "null")
    if isinstance(payload, dict) and payload.get("type") == "verification":
        print("Verification request accepted")
        return {"statusCode": 201}

    notes = [n.get("data", {}) for n in payload if isinstance(n, dict)] if payload else []
    device = sorted({n.get("dataType") for n in notes} & set(client.LIST_TYPES))
    print(f"{len(notes)} notifications, device types: {device}")
    if not device:  # e.g. steps from the phone: left to the daily run
        return {"statusCode": 204}
    table = os.environ["WATERMARK_TABLE"]
    if not _claim_cooldown(ddb, table, datetime.now(UTC)):
        print("Skipped: a run was triggered in the last 3 hours")
        return {"statusCode": 204}
    lam = lam or boto3.client("lambda")
    try:  # async: the run takes minutes, and Google wants a quick reply
        lam.invoke(
            FunctionName=os.environ["INGEST_FUNCTION"], InvocationType="Event", Payload=b"{}"
        )
    except ClientError:  # free the cooldown so Google's retry can start the run
        ddb.update_item(
            TableName=table, Key=COOLDOWN_KEY, UpdateExpression="REMOVE last_trigger_utc"
        )
        raise  # a 5xx, so Google retries the notification
    print("Started an incremental ingestion run")
    return {"statusCode": 204}
