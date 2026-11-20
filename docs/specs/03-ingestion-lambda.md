# Step 03: Ingestion Lambda with watermark

**Goal:** reliable incremental ingestion of the core Google Health data types: heart rate, sleep, HRV, resting heart rate, SpO2, skin temperature and steps. Others can be added later by configuration.

## Scope

- DynamoDB watermark table, one item per source and data type
- Lambda re-fetches a rolling lookback (72 hours to start, configurable per data type) up to now, writes raw JSON, and records the run time and newest data point in the watermark (D2)
- Exponential backoff on 429/5xx; reserved concurrency 1
- Historical backfill mode: last 30 days only, day by day, slow pace
- Error alarm for the Lambda and a daily 24-hour freshness check, to SNS email; 14-day log retention (D7)
- Shared helpers in src/common/ (S3 writer, watermark, HTTP retry) with unit tests

## Done when

- Re-running the same window creates no duplicates once deduplicated downstream
- Backfill of 30 days completes without hitting rate limits

## Out of scope

Triggering by webhook (manual or test invocation only).
