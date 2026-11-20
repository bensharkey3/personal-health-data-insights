# Step 03: Ingestion Lambda with watermark

**Goal:** reliable incremental ingestion of the core Google Health data types: heart rate, sleep, HRV, resting heart rate, SpO2, skin temperature and steps. Others can be added later by configuration.

## Scope

- DynamoDB watermark table, one item per source and data type
- Lambda fetches from watermark minus 1 hour up to now, writes raw JSON, advances watermark to newest data point received
- Exponential backoff on 429/5xx; reserved concurrency 1
- Historical backfill mode: last 30 days only, day by day, slow pace
- Shared helpers in src/common/ (S3 writer, watermark, HTTP retry) with unit tests

## Done when

- Re-running the same window creates no duplicates once deduplicated downstream
- Backfill of 30 days completes without hitting rate limits

## Out of scope

Triggering by webhook (manual or test invocation only).
