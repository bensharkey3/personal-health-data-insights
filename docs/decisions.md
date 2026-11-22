# Decisions

All accepted 2026-11-20. Add new ones at the end; mark replaced ones "Superseded by Dn".

## D1: Minimal-cost serverless
SSM Parameter Store, Lambda function URLs, Terraform state in S3 with native locking, serverless only, one environment tested via PRs. Target: whole project under $1/month. Function URLs need their own auth; flag anything that adds cost.

## D2: Rolling-window ingestion
The device can sync days late, so each run re-fetches a rolling window (72h superseded by D20) and `MERGE INTO` on a natural key removes duplicates. The DynamoDB watermark records last run and newest data point, for backfill and freshness checks.

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
Only core metrics are in scope: heart rate (`heart-rate`, `daily-resting-heart-rate`), HRV (`heart-rate-variability`, `daily-heart-rate-variability`), sleep (`sleep`), SpO2 (`oxygen-saturation`, `daily-oxygen-saturation`), sleeping respiratory rate (`daily-respiratory-rate`, `respiratory-rate-sleep-summary`), skin temperature (`daily-sleep-temperature-derivations`) and steps (`steps`). These are the metrics that matter for sleep and recovery, and they all continue on the Fitbit Air. Other types (distance, activity, calories, zones, VO2 max, etc.) are left out to keep ingestion, tables and the dashboard small; adding one later is a config change. The full list is in [google-health-api.md](google-health-api.md).

## D15: Secrets created by hand, not by Terraform
SSM SecureString parameters (e.g. Google OAuth tokens) are created once with `aws ssm put-parameter` in CloudShell, under `/phdi/`. Terraform only grants Lambdas read access to them by name. If Terraform managed them, their values would be stored in the state file and be readable by the PR plan role.

## D16: Consent screen published, not in Testing
Google expires refresh tokens after 7 days while an External consent screen is in Testing mode, which would break unattended ingestion. The app is published (In production) but never submitted for verification: as its only user, I just click past the "unverified app" warning once at sign-in.

## D17: Steps raw files cover the UTC day
`rollUp` only accepts UTC timestamps, so steps are pulled for the UTC day and `dt` is that UTC date. `list` types filter on local (civil) time, so their `dt` is the local day. The transform derives `local_date` for steps from the window times, so the dashboard still groups by local day (D3).

## D18: Local AWS access for running and inspecting
Manual runs and checks (invoking a Lambda, reading logs, listing S3) are done by Claude Code on the laptop through `aws login`, which gives short-lived credentials from the console sign-in, with no stored keys. This saves copy-pasting into CloudShell. Deploys still go only through GitHub Actions with approval. Secrets are still typed in by hand (D15). Cloud sessions don't have this access and fall back to CloudShell.

## D19: Run-stamped raw files
Each run writes new objects, `dt=<date>/run=<UTC timestamp>.jsonl.gz`, instead of overwriting one file per type-day. Overlapping runs and webhook-triggered reruns fetch the same days again, and overwriting would break the "raw is immutable" rule: old copies would only survive 30 days as S3 versions. The curated `MERGE INTO` already dedupes on natural keys (D2), so the extra copies cost only a little storage. Type-days with no records write nothing, so device-only types don't fill the bucket with empty files.

## D20: Overlap from the newest data, not from now
Supersedes D2's fixed 72h. The API has no "changed since" filter (`updateTime` is output only), so the overlap must cover how late data arrives. Data appears only once the phone uploads it, so a fixed window from now misses anything synced later than the window. Each run instead fetches from one day before the type's newest data point (watermark) to today. That covers a device that was silent for days, plus same-day revisions such as sleep stages finalised after waking. The window is capped at 7 days, so device-only types with no new data don't re-fetch months each run; longer gaps need a backfill run. The step 04 webhook will re-fetch exactly the intervals Google reports as changed, making this a safety net.
