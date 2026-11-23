# Step 03: Ingestion Lambda with watermark

**Goal:** reliable incremental ingestion of Google Health data. Data types are a config list: the in-scope core metrics (D13); device-only types have no new data until a Fitbit Air, which isn't an error.

## Scope

- DynamoDB watermark table, one item per source and data type
- Lambda re-fetches from one day before each type's newest data point (configurable per data type, capped at 7 days) up to now (D20), writes raw JSON, and records the run time and newest data point in the watermark (D2)
- Exponential backoff on 429/5xx; reserved concurrency 1
- Historical backfill mode: any date range, day by day, slow pace. Built and tested here on a short window; the full-history run happens in step 10 (D14)
- Error alarm for the Lambda and a daily 24-hour freshness check, to SNS email; 14-day log retention (D7)
- Shared helpers in src/common/ (S3 writer, watermark, HTTP retry) with unit tests

## Events and manual steps

- `{}`: incremental. Per type, from one day before its newest data point to today, capped at 7 days (D20).
- `{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}`: backfill of up to 14 days, with a 1 s pause between type-days.
- Raw files: `raw/google_health/<type>/dt=<date>/run=<UTC timestamp>.jsonl.gz` (D19). Watermark items: `pk = google_health#<type>` in `phdi-watermark`.
- After the first deploy, click the confirmation link AWS emails for the `phdi-alerts` topic.
- Check, from CloudShell or the laptop (D18):
  ```
  aws lambda invoke --function-name phdi-google-health-ingest --payload '{}' --cli-binary-format raw-in-base64-out out.json && cat out.json
  aws dynamodb scan --table-name phdi-watermark
  ```

## Done when

- Re-running the same window creates no duplicates once deduplicated downstream
- A 3-day backfill completes without hitting rate limits (cut from 7 days: full history waits for step 10)

## Out of scope

Triggering by webhook (manual or test invocation only).
