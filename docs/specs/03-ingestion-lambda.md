# Step 03: Ingestion Lambda with watermark

**Goal:** reliable incremental ingestion of Google Health data. Data types are a config list (IDs in D11); device-only types have no new data until a Fitbit Air, which isn't an error.

## Scope

- DynamoDB watermark table, one item per source and data type
- Lambda re-fetches a rolling lookback (72 hours to start, configurable per data type) up to now, writes raw JSON, and records the run time and newest data point in the watermark (D2)
- Exponential backoff on 429/5xx; reserved concurrency 1
- Historical backfill mode: full history of each type (back to the old Fitbit's first day), day by day, slow pace
- Error alarm for the Lambda and a daily 24-hour freshness check, to SNS email; 14-day log retention (D7)
- Shared helpers in src/common/ (S3 writer, watermark, HTTP retry) with unit tests

## Done when

- Re-running the same window creates no duplicates once deduplicated downstream
- Full-history backfill completes without hitting rate limits

## Out of scope

Triggering by webhook (manual or test invocation only).
