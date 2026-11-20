# Decisions

All accepted 2026-11-20. Add new ones at the end; mark replaced ones "Superseded by Dn".

## D1: Minimal-cost serverless
SSM Parameter Store, Lambda function URLs, Terraform state in S3 with native locking, serverless only, one environment tested via PRs. Target: whole project under $1/month. Function URLs need their own auth; flag anything that adds cost.

## D2: Rolling-window ingestion
The device can sync days late, so each run re-fetches the last 72h (configurable per data type) and `MERGE INTO` on a natural key removes duplicates. The DynamoDB watermark records last run and newest data point, for backfill and freshness checks.

## D3: UTC plus local date
Timestamps in UTC; curated tables add `local_date` from a time zone in config (never in the repo). Sleep belongs to the date it ends. Raw `dt=` partitions stay UTC.

## D4: Interim dashboard auth
From step 08, a CloudFront Function checks a simple credential (from SSM, injected at deploy) until Cognito replaces it in step 09.

## D5: DuckDB writes, Athena maintenance
DuckDB `MERGE INTO` for transforms, proven by a spike at the start of step 05; PyIceberg `upsert` is the fallback (needs dependency approval). Weekly Athena `OPTIMIZE` and `VACUUM` (fractions of a cent).

## D6: Terraform bootstrap from CloudShell
`infra/bootstrap/` (state bucket, GitHub OIDC role trusting only this repo) is applied once from AWS CloudShell, then its state moves into the bucket. Everything after runs in GitHub Actions; the role ARN lives in a GitHub secret.

## D7: Monitoring
Error alarms on Lambdas and Step Functions, a daily 24h no-new-data check, all emailed via SNS (address in config). $1/month AWS Budgets alert (free). 14-day log retention.

## D8: Region
`ap-southeast-2`, with `us-east-1` only where AWS requires it (CloudFront, Lambda@Edge).

## D9: Data retention
Keep raw and curated data indefinitely. Athena results, old S3 versions, Iceberg snapshots and logs expire. Document how to delete everything.

## D10: Lambda packaging
One zip per function, built by `uv` in CI, plus a shared layer with DuckDB and pre-downloaded extensions (Lambda can't download them at runtime).

## D11: Fitbit history, then phone, then Fitbit Air
Google Health holds years of history from my old Fitbit, which stopped about a month ago when I lost it. Until I buy a Fitbit Air (after the project is built), only phone-recorded types keep updating (steps, distance, activity); device-only types (heart rate, HRV, SpO2, sleep, resting HR, skin temperature) have a gap. History starts October 2024. Steps and distance are recorded by both phone and Fitbit, so curated tables must keep one source per interval to avoid double counting. Ingestion backfills the full history once, and the pipeline, dashboard and metrics must handle missing device data rather than treat it as an error. Type IDs that return data: `steps`, `distance`, `active-minutes`, `active-zone-minutes`, `activity-level`, `sedentary-period`, `exercise`, `heart-rate`, `daily-resting-heart-rate`, `heart-rate-variability`, `daily-heart-rate-variability`, `oxygen-saturation`, `daily-oxygen-saturation`, `daily-respiratory-rate`, `daily-sleep-temperature-derivations` (skin temperature), `sleep`, `time-in-heart-rate-zone`, `daily-heart-rate-zones`, `weight`, `height`, `vo2-max`, `run-vo2-max`.

## D12: RollUp for interval types
Interval types such as steps come back from `list` and `reconcile` chopped into different intervals on each call, so there's no stable key to dedupe on. They're ingested with `rollUp` in fixed 60-second windows instead, which returns identical windows every run; the window start is the natural key for `MERGE INTO` (D2). Sample, daily and session types (heart rate, HRV, sleep) stay on `list`, which was stable. Details in [google-health-api.md](google-health-api.md).

## D13: Core metrics only
Only core metrics are in scope: heart rate (`heart-rate`, `daily-resting-heart-rate`), HRV (`heart-rate-variability`, `daily-heart-rate-variability`), sleep (`sleep`), SpO2 (`oxygen-saturation`, `daily-oxygen-saturation`), skin temperature (`daily-sleep-temperature-derivations`) and steps (`steps`). These are the metrics that matter for sleep and recovery, and they all continue on the Fitbit Air. Other types (distance, activity, calories, zones, VO2 max, etc.) are left out to keep ingestion, tables and the dashboard small; adding one later is a config change. The full list is in [google-health-api.md](google-health-api.md).

## D14: Backfill and go-live after the build
The full-history backfill and the ongoing incremental load start only once the whole pipeline is built (step 10). Until then, every pipeline runs manually on short test windows, and webhook subscriptions and schedules are only switched on to test them. This avoids re-running a long backfill whenever raw layout, transforms or table design change during the build, and keeps costs near zero meanwhile.
