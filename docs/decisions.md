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

## D11: Phone data first, Fitbit later
The Fitbit Air won't arrive until after the project is built, so every step is built and tested on data the phone records in Google Health (steps today, plus any other phone types the API returns). Device-only types (heart rate, sleep, HRV, resting HR, SpO2, skin temperature) are added later by config; tests use synthetic fixtures for them until then.
