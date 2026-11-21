# Architecture

Single-user serverless pipeline on AWS. Data flows one way, from sources to a daily dashboard. The reasons behind each choice are in [decisions.md](decisions.md) (D1, D2, …). Nothing here may identify my location, AWS account or endpoints.

```
Fitbit (Google Health) ─webhook─┐
Tasker (phone) ──function URL───┼─▶ Ingest Lambdas ─▶ S3 raw JSON ─▶ DuckDB transform ─▶ Iceberg (Glue)
Weather ──schedule──────────────┘                                                          │
                                       Dashboard + AI summary (CloudFront) ◀─ Morning chain ┘
```

## Sources

| Source | Data | Arrives via | Spec |
| --- | --- | --- | --- |
| Google Health API | Heart rate, HRV, sleep, SpO2, respiratory rate, skin temperature, steps (D13). Old Fitbit history; only steps continue from the phone until a Fitbit Air (D11) | Webhook → ingestion Lambda | 02–04 |
| Tasker (Android) | Screen time, home/office geofence events | POST to a Lambda function URL | 06 |
| Weather API | Daily/hourly weather | EventBridge schedule | 07 |

## Ingestion and storage

- **Ingestion:** each run re-fetches the last 72h (configurable per data type), so data that syncs late isn't missed. A DynamoDB watermark records the last run and newest data point for backfill and freshness checks. Backoff on 429/5xx, concurrency 1 (D2). The full-history backfill and ongoing loads start only once everything is built, in step 10 (D14).
- **Raw:** S3 `raw/<source>/<data_type>/dt=YYYY-MM-DD/`, one gzipped JSON Lines object per type-day holding the API pages as returned. `dt` is the local day requested, or the UTC day for steps (D17). Immutable JSON; block public access, encryption and versioning on (D1).
- **Curated:** one Iceberg table per data type in Glue, partitioned by month. Each has a natural key so `MERGE INTO` removes the duplicates the overlapping fetches create; interval types use fixed rollUp windows so the key is stable (D2, D5, D12).
- **Time:** timestamps in UTC plus a `local_date` column; sleep counts toward the date it ends (D3).
- **Retention:** data kept indefinitely; operational leftovers expire (D9).

## Processing and serving

- **Transform:** a Lambda where DuckDB flattens raw JSON and merges it into Iceberg. A weekly Athena `OPTIMIZE` / `VACUUM` job compacts files and expires snapshots, which DuckDB can't do (D5).
- **Morning chain:** Step Functions, triggered when a sleep session arrives: merge the day → compare metrics to a 30-day baseline → readiness light and illness flag → Bedrock summary → build static HTML → push the readiness line to my phone. A weekly run turns a few precomputed correlations (e.g. screen time vs sleep) into plain-sentence insights.
- **Serving:** S3 + CloudFront in `ap-southeast-2` / `us-east-1` (D8). A CloudFront Function checks an interim credential until Cognito login in step 09 (D4).

## Operations

- **Infra/CI:** Terraform in `infra/`. A one-off CloudShell bootstrap creates the state bucket and GitHub OIDC role; after that, GitHub Actions plans on PRs and applies on merge to `main` after manual approval (D6). One zip per Lambda plus a shared DuckDB layer (D10).
- **Monitoring:** error alarms, a daily freshness check and a $1/month budget alert, all by email; 14-day log retention (D7).

## Open questions

- Step 08: the chain is triggered by a sleep session, and there's no new sleep data until a Fitbit Air (D11), so start on a daily schedule? Timed fallback once sleep data exists? Push channel (SNS email is free; a phone push app adds a dependency)? What data goes to Bedrock (aggregates only, or with context)?
