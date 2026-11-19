docs/specs/
One short spec per build step. Save each section as its own file in docs/specs/. Before building, ask Claude Code to review and expand the spec in plan mode; finish each step with something working end to end, then start a fresh session.
01-repo-skeleton.md
Goal: a working repo and Terraform foundation to build on.
Scope
• Repo layout as in CLAUDE.md; uv project with Python 3.12, ruff, pytest
• Terraform in infra/ with remote state: S3 bucket with native S3 locking (bootstrap module)
• Existing AWS account, single environment (no separate dev/prod); changes tested via pull requests before deploy
    ◦ Core resources: raw data S3 bucket
   (block public access, encryption, versioning), SSM Parameter Store placeholders
• .gitignore covering secrets, .env, Terraform state
• Public GitHub repo (no personal data, account IDs, endpoint URLs or secrets ever committed; secret scanning and push protection enabled) with GitHub Actions: CI on pull requests (ruff, pytest, terraform fmt/validate/plan), deploy on merge to main with apply gated by manual approval; AWS access via OIDC role
Done when
• uv run pytest and ruff check pass on an empty test
• terraform plan runs clean against remote state; I've approved and applied it
Out of scope: any Lambda or data source.
02-google-health-oauth.md
Goal: prove I can authorise and pull one day of my Fitbit Air data.
Scope
• Google Cloud project, OAuth consent screen and client (manual steps documented in the spec)
• One-off authorisation flow to obtain a refresh token, stored in SSM Parameter Store
• Python module in src/ingest/google_health/ that refreshes the access token and pulls one day of heart rate, steps and sleep. Built before the Fitbit Air arrives: develop against whatever my Android phone already records in Google Health (e.g. steps), and use synthetic fixtures for heart rate and sleep until device data exists
• Run it in the cloud (a manually invoked Lambda), writing raw JSON to S3
Done when
• One day of phone-recorded data (e.g. steps) lands as raw JSON now; heart rate and sleep confirmed once the device is worn. Raw files go in raw/google_health/<data_type>/dt=YYYY-MM-DD/
• No tokens in code, logs or git
Out of scope: scheduling, watermarks, webhooks.
03-ingestion-lambda.md
Goal: reliable incremental ingestion of the core Google Health data types: heart rate, sleep, HRV, resting heart rate, SpO2, skin temperature and steps. Others can be added later by configuration.
Scope
• DynamoDB watermark table, one item per source and data type
• Lambda fetches from watermark minus 1 hour up to now, writes raw JSON, advances watermark to newest data point received
• Exponential backoff on 429/5xx; reserved concurrency 1
• Historical backfill mode: last 30 days only, day by day, slow pace
• Shared helpers in src/common/ (S3 writer, watermark, HTTP retry) with unit tests
Done when
• Re-running the same window creates no duplicates once deduplicated downstream
• Backfill of 30 days completes without hitting rate limits
Out of scope: triggering by webhook (manual or test invocation only).
04-webhook-trigger.md
Goal: ingestion runs automatically whenever my Fitbit Air syncs.
Scope
• Lambda function URL (no API Gateway) as the webhook endpoint
• Register a Google Health data subscription; handle subscriber verification
• Validate incoming notifications; invoke the step 3 ingestion for the affected data types
• Ignore or coalesce bursts (several notifications per sync)
Done when
• Opening the Google Health app on my phone results in new raw files in S3 within minutes, with no manual step
• Unverified requests are rejected
Out of scope: transforms, morning chain.
05-iceberg-duckdb.md
Goal: curated, queryable Iceberg tables built from raw data.
Scope
• Glue database; one Iceberg table per data type, partitioned by month on event timestamp
• DuckDB (iceberg extension) packaged for Lambda, attaching the Glue catalog
• Transform Lambda: reads new raw JSON, flattens it, MERGE INTO the Iceberg table (create-then-insert, no CTAS)
• Monthly partitions; scheduled compaction Lambda (EventBridge, e.g. weekly) that rewrites small files, expires old snapshots and removes orphan files
Done when
• Tables for heart rate, steps and sleep return correct row counts for a test day, in DuckDB and in Athena
• Re-running a day produces no duplicate rows
Out of scope: dashboard, AI summary.
06-tasker-endpoints.md
Goal: phone screen time and location land in the pipeline automatically.
Scope
• Lambda function URL accepting JSON from Tasker, protected by a shared secret header (secret in SSM Parameter Store)
• Payload schemas: nightly screen-time export (per-app usage and screen sessions), geofence enter/exit events for home and office
• Raw JSON to S3; Iceberg tables for screen time and location
• Tasker setup instructions documented (profiles, tasks, HTTP request)
Done when
• A night of screen time and a day of home/office events appear in their Iceberg tables
• Requests without the secret are rejected
Out of scope: full GPS tracking.
07-weather-pollen.md
Goal: daily environmental context alongside my health data.
Scope
• Choose free weather and pollen APIs for Croydon, Melbourne (document the choice as an ADR)
• EventBridge-scheduled Lambda, daily (or hourly for weather), raw JSON to S3
• Iceberg tables for weather and pollen
Done when
• A week of weather and pollen data is queryable and joins to health data by date
Out of scope: air-quality sensors or paid APIs.
08-morning-chain-dashboard.md
Goal: each morning, a fresh dashboard and AI summary of last night's sleep and readiness.
Scope
• Trigger: completed sleep session arrives via webhook (no fixed time)
• Step Functions chain: merge previous day into Iceberg → compute metrics vs 30-day baseline (sleep, HRV, resting HR, skin temperature) → Bedrock AI summary → build dashboard
• Dashboard Lambda: DuckDB queries, Plotly charts, AI summary at top, mobile-friendly static HTML
• S3 + CloudFront hosting behind an unguessable private link
• Runs once per morning even if several sleep notifications arrive
Done when
• After waking and syncing, the dashboard and summary update within minutes
• Monthly AWS cost for the chain stays near zero (check in Cost Explorer)
Out of scope: login, interactive filtering, summary delivery channel (still to decide).
09-cognito-login.md
Goal: the dashboard is protected by a proper login.
Scope
• Cognito user pool and hosted UI, single user, in Terraform
• Lambda@Edge on CloudFront validating the login token before serving the page
• Retire the private link
Done when
• Opening the dashboard without signing in redirects to login; signed in, it loads on my phone
• The old private link no longer works