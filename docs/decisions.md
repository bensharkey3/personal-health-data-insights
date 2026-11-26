# Decisions

All accepted 2026-11-20. Add new ones at the end; mark replaced ones "Superseded by Dn".

## D1: Minimal-cost serverless
SSM Parameter Store, Lambda function URLs, Terraform state in S3 with native locking, serverless only, one environment tested via PRs. Target: whole project under $1/month. Function URLs need their own auth; flag anything that adds cost.

## D2: Rolling-window ingestion
The device can sync days late, so each run re-fetches a rolling window (72h superseded by D20) and the transform keeps only the latest file per type-day (D23). The DynamoDB watermark records last run and newest data point, for backfill and freshness checks.

## D3: UTC plus local date
Timestamps in UTC; curated tables add `local_date` from each record's own civil date or UTC offset; steps, whose windows are UTC, and phone events use the phone's time zone at the time (D29). Sleep belongs to the date it ends. Raw `dt=` partitions stay UTC.

## D4: Interim dashboard auth
From step 08, a CloudFront Function checks a simple credential (from SSM, injected at deploy) until Cognito replaces it in step 09.

## D5: DuckDB writes, Athena maintenance (superseded by D23)
DuckDB `MERGE INTO` for transforms, proven by a spike at the start of step 05; PyIceberg `upsert` is the fallback (needs dependency approval). Weekly Athena `OPTIMIZE` and `VACUUM` (fractions of a cent).

## D6: Terraform bootstrap from CloudShell
`infra/bootstrap/` (state bucket, GitHub OIDC role trusting only this repo) is applied once from AWS CloudShell, then its state moves into the bucket. Everything after runs in GitHub Actions; the role ARN lives in a GitHub secret.

## D7: Monitoring
Error alarms on Lambdas and Step Functions, a daily 24h no-new-data check, all emailed via SNS (address in config). $1/month AWS Budgets alert (free). 14-day log retention.

## D8: Region
`ap-southeast-2`, with `us-east-1` only where AWS requires it (CloudFront, Lambda@Edge).

## D9: Data retention
Keep raw and curated data indefinitely. Old S3 versions and logs expire. Document how to delete everything.

## D10: Lambda packaging
One zip per function, built by `uv` in CI, plus a shared DuckDB layer. The DuckDB wheel bundles the json, parquet and icu extensions, so nothing is downloaded at runtime (D23).

## D11: Fitbit history, then phone, then Fitbit Air
Google Health holds years of history from my old Fitbit, which stopped about a month ago when I lost it. Until I buy a Fitbit Air (after the project is built), only phone-recorded types keep updating (steps, distance, activity); device-only types (heart rate, HRV, SpO2, sleep, resting HR, skin temperature) have a gap. History starts October 2024. Steps and distance are recorded by both phone and Fitbit, so curated tables must keep one source per interval to avoid double counting. Ingestion backfills the full history once, and the pipeline, dashboard and metrics must handle missing device data rather than treat it as an error. Type IDs that return data: `steps`, `distance`, `active-minutes`, `active-zone-minutes`, `activity-level`, `sedentary-period`, `exercise`, `heart-rate`, `daily-resting-heart-rate`, `heart-rate-variability`, `daily-heart-rate-variability`, `oxygen-saturation`, `daily-oxygen-saturation`, `daily-respiratory-rate`, `daily-sleep-temperature-derivations` (skin temperature), `sleep`, `time-in-heart-rate-zone`, `daily-heart-rate-zones`, `weight`, `height`, `vo2-max`, `run-vo2-max`.

## D12: RollUp for interval types
Interval types such as steps come back from `list` and `reconcile` chopped into different intervals on each call, so the same day differs between runs. They're ingested with `rollUp` in fixed 60-second windows instead, which returns identical windows every run and picks one source per window. Sample, daily and session types (heart rate, HRV, sleep) stay on `list`, which was stable. Details in [google-health-api.md](google-health-api.md).

## D13: Core metrics only
Only core metrics are in scope: heart rate (`heart-rate`, `daily-resting-heart-rate`), HRV (`heart-rate-variability`, `daily-heart-rate-variability`), sleep (`sleep`), SpO2 (`oxygen-saturation`, `daily-oxygen-saturation`), skin temperature (`daily-sleep-temperature-derivations`) and steps (`steps`). These are the metrics that matter for sleep and recovery, and they all continue on the Fitbit Air. Other types (distance, activity, calories, zones, VO2 max, etc.) are left out to keep ingestion, tables and the dashboard small; adding one later is a config change. The full list is in [google-health-api.md](google-health-api.md).

## D14: Backfill and go-live after the build (ongoing loads superseded by D22)
The full-history backfill and the ongoing incremental load start only once the whole pipeline is built (step 10). Until then, every pipeline runs manually on short test windows, and webhook subscriptions and schedules are only switched on to test them. This avoids re-running a long backfill whenever raw layout, transforms or table design change during the build, and keeps costs near zero meanwhile.
Only core metrics are in scope: heart rate (`heart-rate`, `daily-resting-heart-rate`), HRV (`heart-rate-variability`, `daily-heart-rate-variability`), sleep (`sleep`), SpO2 (`oxygen-saturation`, `daily-oxygen-saturation`), sleeping respiratory rate (`daily-respiratory-rate`, `respiratory-rate-sleep-summary`), skin temperature (`daily-sleep-temperature-derivations`) and steps (`steps`). These are the metrics that matter for sleep and recovery, and they all continue on the Fitbit Air. Other types (distance, activity, calories, zones, VO2 max, etc.) are left out to keep ingestion, tables and the dashboard small; adding one later is a config change. The full list is in [google-health-api.md](google-health-api.md).

## D15: Secrets created by hand, not by Terraform
SSM SecureString parameters (e.g. Google OAuth tokens) are created once with `aws ssm put-parameter` in CloudShell, under `/phdi/`. Terraform only grants Lambdas read access to them by name. If Terraform managed them, their values would be stored in the state file and be readable by the PR plan role.

## D16: Consent screen published, not in Testing
Google expires refresh tokens after 7 days while an External consent screen is in Testing mode, which would break unattended ingestion. The app is published (In production) but never submitted for verification: as its only user, I just click past the "unverified app" warning once at sign-in.

## D17: Steps raw files cover the UTC day
`rollUp` only accepts UTC timestamps, so steps are pulled for the UTC day and `dt` is that UTC date. `list` types filter on local (civil) time, so their `dt` is the local day. The transform derives `local_date` for steps from the window times, so the dashboard still groups by local day (D3).

## D18: Local AWS access for running and inspecting
Manual runs and checks (invoking a Lambda, reading logs, listing S3) are done by Claude Code on the laptop through `aws login`, which gives short-lived credentials from the console sign-in, with no stored keys. This saves copy-pasting into CloudShell. Deploys still go only through GitHub Actions. Secrets are still typed in by hand (D15). Cloud sessions don't have this access and fall back to CloudShell.

## D19: Run-stamped raw files
Each run writes new objects, `dt=<date>/run=<UTC timestamp>.jsonl.gz`, instead of overwriting one file per type-day. Overlapping runs and webhook-triggered reruns fetch the same days again, and overwriting would break the "raw is immutable" rule: old copies would only survive 30 days as S3 versions. The transform reads only the latest file per type-day (D23), so the extra copies cost only a little storage. Type-days with no records write nothing, so device-only types don't fill the bucket with empty files.

## D20: Overlap from the newest data, not from now
Supersedes D2's fixed 72h. The API has no "changed since" filter (`updateTime` is output only), so the overlap must cover how late data arrives. Data appears only once the phone uploads it, so a fixed window from now misses anything synced later than the window. Each run instead fetches from one day before the type's newest data point (watermark) to today. That covers a device that was silent for days, plus same-day revisions such as sleep stages finalised after waking. The window is capped at 7 days, so device-only types with no new data don't re-fetch months each run; longer gaps need a backfill run. The step 04 webhook will re-fetch exactly the intervals Google reports as changed, making this a safety net.

## D21: No deploy approval while in development
Merging a PR to `main` is the approval: the Deploy workflow applies straight away, with no required reviewer on the `production` environment. The project isn't in use yet, and the extra click left deploys waiting unnoticed. The environment stays, limited to `main`. Re-add a required reviewer once real data flows (step 10).

## D22: Fitbit by webhook, phone by daily schedule
Phone steps upload to Google many times a day, and a run per upload would be noisy, so the webhook subscribes only to Fitbit device types and phone steps are picked up by one daily run at 06:00 phone-local (D31). Fitbit background sync can't be switched off, so webhook runs are limited to one per 3 hours by a conditional DynamoDB update. Skipped notifications lose nothing, because each run fetches from the watermark (D20). The receiver checks a shared secret only; signature checking would add a crypto dependency. This switches ongoing incremental loads on now rather than in step 10 (supersedes that part of D14); the full-history backfill still waits for step 10.

## D23: Curated Parquet rebuilt from the latest raw files, not Iceberg
Supersedes D5. Each raw file holds one complete type-day as the API returned it, and files never overlap across days, so the newest `run=` file of each day is the truth and no key-based merge is needed. The transform rebuilds one Parquet file per type-month from those files and overwrites it, which is idempotent by construction. Iceberg, Glue, Athena and compaction were heavy for a few hundred MB, and DuckDB's Iceberg writes through Glue were still experimental. Query with DuckDB on the laptop or in the dashboard Lambda; Glue tables for Athena can be added later. Known gap: if data is deleted in the app and a later fetch returns nothing, no file is written (D19), so the older file stays latest; accepted, as deletions are rare.

## D24: Tasker sends screen and Wi-Fi events in one nightly batch
Screen time is logged as screen on/off events, which gives total and late-night use without the fiddly per-app usage API. Home and office come from Wi-Fi connected/disconnected, which uses no battery and works indoors, and only the labels leave the phone. Tasker appends `<epoch seconds>,<event>` lines to a local file, which is plain CSV so there's no JSON building in Tasker, and sends it once a night, keeping it until the reply is a success. That's one Lambda run a night instead of 100+, and an offline night is retried. The data is tiny (about 70k lines a year), so the transform rebuilds both Tasker tables from all raw batches each time, de-duplicating repeated lines, instead of partitioning by month like D23.

## D25: Tasker batch sent when bedtime mode ends
Changes D24's send time. A fixed 03:30 send is unreliable: the phone lies still in bedtime mode, so Android's Doze delays timed profiles and cuts the network. Sending when bedtime mode ends (its Do Not Disturb switching off) means the phone is awake and online, and the night's events reach the morning summary. Events carry their own timestamps and stay on the phone until a send succeeds, so a late or missed send loses nothing. Turning Do Not Disturb off at other times just sends an extra small batch, which the transform de-duplicates.

## D26: Automate instead of Tasker on the phone
The phone logger is Automate (LlamaLab): flowcharts are easier to follow and export than Tasker's profiles, and it covers every trigger needed (display, Wi-Fi, Do Not Disturb, file write, HTTP). The receiver only sees CSV lines, so nothing on the AWS side changes. The internal "tasker" names (`phdi-tasker`, `raw/tasker/`, `curated/tasker/`, `/phdi/tasker/secret`, `src/ingest/tasker/`) stay as the source name: renaming would replace the Lambda and its function URL, and move raw files, for no functional gain.

## D27: Time zone only in config
Now only the fallback before the first phone fix (D29, D31). The local time zone is the `TIME_ZONE` GitHub secret, passed by Terraform to the scheduler and to the transform Lambda as an environment variable, instead of being written in the code. A time zone narrows down where I live, and the repo is public. Tests use a fixed `Etc/GMT-11` zone. Older commits still contain it; rewriting public history isn't worth it for this.

## D28: Tasker from a committed project file
Supersedes D26. Building Automate flows by hand was too fiddly, and Automate's `.flo` files are binary, so they can't be written as code. Tasker imports a readable XML project, so the whole phone setup lives in the repo (`src/ingest/tasker/phdi.prj.xml`): import it, set two variables, type two network names. Logging uses native Write File actions; only the daily send is JavaScript. A test keeps URLs, the secret and real network names out of the file, since the repo is public.

## D29: Local time and location follow the phone
Local dates and weather should match where I actually am, including when travelling, not a fixed home. The daily Tasker send adds one coarse network location fix (no GPS, about 1 km after rounding) with the phone's IANA time zone: `<epoch>,location,<lat>,<lon>,<zone>`. Every timestamp without its own local time (steps, phone events) takes the zone of the latest fix at or before it, through a DuckDB ASOF JOIN, so a trip switches zone at the next morning's fix. Other Google Health types already carry the device's local time. `TIME_ZONE` remains only as the fallback before the first fix and as the zone for the daily runs until the first fix (D31). Fixes are kept in the private bucket, and `curated/tasker/locations` holds one per local date for the weather step.

## D30: Weather from Open-Meteo at the phone's location, daily at 06:00
Open-Meteo is free with no key or account, uses Bureau of Meteorology models for Australia, can resolve a place's time zone itself, and has an archive for the backfill. A run at 06:00 phone-local (D31) fetches yesterday's actuals and today's forecast in one request, so the morning summary has both; the next day's run replaces the forecast with actuals. It uses the phone's latest location fix (D29), not a fixed home, so no location secret is needed and travel is handled, a day late at most. The night's temperature, from hourly data, matters most for sleep. Its CC BY 4.0 licence means the dashboard must credit it.

## D31: Daily runs at 06:00 where the phone is (moved from 05:00)
The daily Google Health ingest and the weather run start at 06:00 in the phone's current time zone, so mornings line up when travelling. EventBridge Scheduler only takes one fixed zone, so a single schedule ticks every 15 minutes in UTC and invokes the transform, which already has DuckDB's time zone data: when it's 06:00-06:15 in the zone of the phone's latest fix (or `TIME_ZONE` before the first), it starts both runs. Every 15 minutes, not hourly, so zones with :30 or :45 offsets still hit 06:00. The tick checks the time it runs: EventBridge Scheduler doesn't fill in its scheduled-time placeholder for a Lambda target. A tick delayed over 15 minutes behind a rebuild would miss a day; the next day's runs catch the data up (D20). About 3,000 tiny invocations a month, all in the free tier. Replaces the fixed 05:15 schedule.

## D32: Air quality from Open-Meteo, alongside the weather
Smoke and particles can affect sleep, so the 06:00 weather run also asks Open-Meteo's Air Quality API for hourly PM2.5, PM10, ozone, nitrogen dioxide and US AQI at the same place and days, and the weather table gains daily summaries plus overnight PM2.5. It's free, needs no key and follows the phone like the weather. Outside Europe it's modelled (CAMS global, about 40 km), not measured: fine for trends and smoke events. EPA Victoria's measured AirWatch data was the alternative, but it needs a key and only covers Victoria. US AQI because it's widely known and Australia has no single national index.

## D33: Dashboard rebuilt by the transform, no Step Functions yet
The page is a few small DuckDB queries over the curated files, so the transform rebuilds it at the end of every data rebuild (ingest, webhook, phone batch, weather) and it's always fresh within minutes of a sync. The Deploy workflow also triggers a rebuild after each apply, so code changes show without waiting for new data. A Step Functions chain adds cost and moving parts for no gain yet; it can come with step 08b if the morning work grows. Charts are inline SVG drawn in Python, so there's no chart library or JavaScript.

## D34: Dashboard login by a Terraform-made password
Until Cognito (step 09), a CloudFront Function asks for a password with HTTP Basic auth (user `me`) and compares the SHA-256 of the `Authorization` header with a hash Terraform computes. Terraform generates the random password and keeps it in SSM, where I read it in the console, so setup works from a phone with no laptop. It's also in the private, encrypted Terraform state: a deliberate exception to D15 for this low-stakes, read-only page that Cognito will replace. The browser remembers the login; the CloudFront address is masked in the Actions logs and never output. A new password is a `terraform taint` of the resource.
