"""DynamoDB watermark: one item per source and data type, holding the last successful run and the
newest data point seen (D2), plus cooldown items that rate-limit triggers (D22, D37). Uses the
low-level client, so values are wrapped as {"S": ...}."""

from datetime import datetime, timedelta

from botocore.exceptions import ClientError


def _key(source: str, kind: str) -> dict:
    return {"pk": {"S": f"{source}#{kind}"}}


def get(ddb, table: str, source: str, kind: str) -> dict[str, str]:
    item = ddb.get_item(TableName=table, Key=_key(source, kind)).get("Item", {})
    return {k: v["S"] for k, v in item.items() if k != "pk"}


def put(ddb, table: str, source: str, kind: str, previous: dict, run: str, newest: str | None):
    """newest_point_utc only moves forward: a backfill of old days never pulls it back.
    ISO 8601 UTC strings sort in time order, so max() on the strings is enough."""
    best = max(filter(None, [previous.get("newest_point_utc"), newest]), default=None)
    item = {"last_run_utc": run} | ({"newest_point_utc": best} if best else {})
    ddb.put_item(TableName=table, Item=_key(source, kind) | {k: {"S": v} for k, v in item.items()})


def claim(ddb, table: str, name: str, cooldown: timedelta, now: datetime) -> bool:
    """Atomically records a trigger unless one happened within the cooldown, so parallel requests
    can't both start a run. ISO UTC strings compare in time order."""
    try:
        ddb.update_item(
            TableName=table,
            Key={"pk": {"S": name}},
            UpdateExpression="SET last_trigger_utc = :now",
            ConditionExpression="attribute_not_exists(last_trigger_utc) OR last_trigger_utc < :cut",
            ExpressionAttributeValues={
                ":now": {"S": now.strftime("%Y-%m-%dT%H:%M:%SZ")},
                ":cut": {"S": (now - cooldown).strftime("%Y-%m-%dT%H:%M:%SZ")},
            },
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def release(ddb, table: str, name: str) -> None:
    """Frees a claimed cooldown, when the run it was for couldn't be started."""
    ddb.update_item(
        TableName=table, Key={"pk": {"S": name}}, UpdateExpression="REMOVE last_trigger_utc"
    )
