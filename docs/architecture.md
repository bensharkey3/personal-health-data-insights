# Architecture

> Living document. Read before any design or infrastructure change; update it whenever an ADR in [decisions/](decisions/) changes the design. Nothing here may identify the owner's location, AWS account or endpoints (see the hard rule in CLAUDE.md).

## Overview

Single-user, serverless pipeline on AWS in `ap-southeast-2`, with global resources in `us-east-1` ([ADR 0008](decisions/0008-aws-region.md)). Data flows one way:

```
Sources ──▶ Ingest Lambdas ──▶ S3 raw (immutable JSON) ──▶ Transform Lambda ──▶ Iceberg tables (Glue catalog)
                                                                                      │
                                       Static dashboard + AI summary  ◀── Morning chain ┘
```

## Sources

| Source | Data | How it arrives | Spec |
| --- | --- | --- | --- |
| Google Health API (Fitbit Air) | Heart rate, sleep, HRV, resting HR, SpO2, skin temperature, steps | Webhook → ingestion Lambda (rolling-window pull) | 02, 03, 04 |
| Tasker (Android phone) | Screen time, home/office geofence events | HTTPS POST to Lambda function URL | 06 |
| Weather and pollen APIs | Daily/hourly weather, pollen | EventBridge schedule | 07 |

## Ingestion

- Each run re-fetches a rolling lookback (72 hours to start, configurable per data type) so late-synced data isn't missed; duplicates are removed downstream ([ADR 0002](decisions/0002-rolling-window-ingestion.md)).
- DynamoDB watermark table (one item per source and data type) records the last successful run and the newest data point; it drives backfill and freshness checks.
- Idempotent, exponential backoff on 429/5xx, reserved concurrency 1.

## Storage

- **Raw:** S3, immutable JSON, `raw/<source>/<data_type>/dt=YYYY-MM-DD/` (UTC date). Block public access, SSE-S3 encryption, versioning.
- **Curated:** Iceberg tables in a Glue database, one per data type, partitioned by month on event timestamp. Each table has a natural key for `MERGE INTO` dedupe.
- **Time:** event timestamps in UTC, plus a `local_date` column derived from a configured IANA time zone; sleep is assigned to the local date it ends ([ADR 0003](decisions/0003-utc-plus-local-date.md)).
- **Secrets:** SSM Parameter Store SecureString.
- **Retention:** raw and curated data kept indefinitely; operational data expires; delete-everything runbook ([ADR 0009](decisions/0009-data-retention.md)).

## Processing

- Transform Lambda: DuckDB reads raw JSON, flattens it and writes with `MERGE INTO`. Step 05 begins with a spike to confirm this works; the fallback is PyIceberg `upsert` ([ADR 0005](decisions/0005-duckdb-writes-athena-maintenance.md)).
- Maintenance: a weekly Lambda runs Athena `OPTIMIZE` and `VACUUM` on each table.
- Morning chain (Step Functions): merge previous day → metrics vs 30-day baseline → Bedrock summary → build static HTML dashboard.

## Serving

- Static HTML on S3 + CloudFront.
- Step 08: a CloudFront Function checks an interim credential before serving ([ADR 0004](decisions/0004-interim-dashboard-auth.md)).
- Step 09: Cognito login via Lambda@Edge replaces it.

## Operations

- **Infrastructure:** Terraform in `infra/`; remote state in S3 with native locking. The state bucket and OIDC role come from `infra/bootstrap/`, applied once from AWS CloudShell; everything after runs in GitHub Actions ([ADR 0006](decisions/0006-terraform-bootstrap-cloudshell.md)).
- **CI/CD:** GitHub Actions with OIDC. PRs run ruff, pytest and Terraform plan; merge to `main` applies after manual approval. `main` is protected by a ruleset and a Claude Code hook.
- **Packaging:** per-function zips built by `uv`, plus a shared layer with DuckDB and pre-downloaded extensions ([ADR 0010](decisions/0010-lambda-packaging.md)).
- **Monitoring:** Lambda and Step Functions error alarms, a daily 24-hour freshness check, an AWS Budgets alert at about $2/month, all to SNS email; 14-day log retention ([ADR 0007](decisions/0007-monitoring-and-alerts.md)).
- **Cost:** free tiers first, serverless only, no always-on compute ([ADR 0001](decisions/0001-minimal-cost-serverless.md)).

## Open questions

To settle when planning step 08:

- Morning chain trigger: sleep webhook only, or with a timed fallback when no sleep data arrives?
- AI summary delivery: dashboard only, or also email or phone push?
- Bedrock input: aggregates only, or with screen time, location hours and weather context?

To settle in step 07:

- Pollen data source for the home location (Open-Meteo pollen covers Europe only).
