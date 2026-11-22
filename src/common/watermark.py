"""DynamoDB watermark: one item per source and data type, holding the last successful run and the
newest data point seen (D2). Uses the low-level client, so values are wrapped as {"S": ...}."""


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
