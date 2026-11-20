# Decisions

All accepted 2026-11-20. Add new ones at the end with a date; mark replaced ones "Superseded by Dn". Each entry: the decision, why, and the trade-off.

## D1: Minimal-cost serverless
Free tiers first: SSM Parameter Store (not Secrets Manager), Lambda function URLs (not API Gateway), Terraform state in S3 with native locking (no DynamoDB lock table). Serverless only; one environment, with changes tested via PRs.

**Trade-off:** function URLs have no built-in auth, so each one validates requests itself. Any change that adds cost gets flagged.

## D2: Rolling-window ingestion
The device can sync hours or days late, so a watermark on the newest timestamp would skip late records. Each run re-fetches the last 72h (configurable per data type) instead, and `MERGE INTO` on a natural key removes duplicates. The DynamoDB watermark records the last run and newest data point, for backfill and freshness checks, not to narrow the fetch.

**Trade-off:** more API calls and overlapping raw files (negligible at this volume); gaps longer than the lookback need a manual backfill.

## D3: UTC plus local date
Timestamps stay in UTC; curated tables add `local_date` from a time zone in config (never in the repo), so daily metrics match my day. Sleep belongs to the date it ends. Raw `dt=` partitions stay UTC.

**Trade-off:** travel across time zones would need the config changed.

## D4: Interim dashboard auth
From step 08, a CloudFront Function checks a simple credential (from SSM, injected at deploy) so the dashboard isn't open while Cognito is still to come.

**Trade-off:** weaker than a real login; replaced by Cognito in step 09.

## D5: DuckDB writes, Athena maintenance
DuckDB is the main engine (and the learning goal), but its Iceberg writes are new and it can't compact files or expire snapshots. So transforms use DuckDB `MERGE INTO`, proven by a spike at the start of step 05, with PyIceberg `upsert` as fallback (needs dependency approval). A weekly Lambda runs Athena `OPTIMIZE` and `VACUUM`.

**Trade-off:** adds Athena (fractions of a cent) and a results bucket; tables must stick to Iceberg features both engines support.

## D6: Terraform bootstrap from CloudShell
The state bucket and GitHub OIDC role must exist before CI can run Terraform. `infra/bootstrap/` creates them once from AWS CloudShell, then its state moves into the bucket. Everything after runs in GitHub Actions; the role ARN lives in a GitHub secret and trusts only this repo.

**Trade-off:** one manual step, documented in the step 01 spec.

## D7: Monitoring
Error alarms on Lambdas and Step Functions, plus a daily check that alerts if no new data arrived in 24h, all emailed via SNS (address in config). AWS Budgets alert at $2/month. 14-day log retention.

**Trade-off:** email only, no dashboard of pipeline health.

## D8: Region
`ap-southeast-2` (closest to me), with `us-east-1` only where AWS requires it (CloudFront certificates, Lambda@Edge).

## D9: Data retention
Keep raw and curated data indefinitely; the value is in the long history. Athena results, old S3 versions, Iceberg snapshots and logs expire to keep costs flat. Document how to delete everything.

## D10: Lambda packaging
One zip per function, built by `uv` in CI, plus a shared layer with DuckDB and its extensions pre-downloaded, since Lambda can't fetch them at runtime.

**Trade-off:** the layer must be rebuilt when DuckDB is upgraded.
