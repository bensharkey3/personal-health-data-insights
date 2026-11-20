# Architecture

> Living document. Read before any design or infrastructure change; update it whenever an ADR in [decisions/](decisions/) changes the design. Nothing here may identify the owner's location, AWS account or endpoints (see the hard rule in CLAUDE.md).

## Overview

Single-user, serverless pipeline on AWS. Data flows one way:

```
Sources ──▶ Ingest Lambdas ──▶ S3 raw (immutable JSON) ──▶ Transform Lambda ──▶ Iceberg tables (Glue catalog)
                                                                                      │
                                       Static dashboard + AI summary  ◀── Morning chain ┘
```

## Sources

| Source | Data | How it arrives | Spec |
| --- | --- | --- | --- |
| Google Health API (Fitbit Air) | Heart rate, sleep, HRV, resting HR, SpO2, skin temperature, steps | Webhook → ingestion Lambda (pull with watermark) | 02, 03, 04 |
| Tasker (Android phone) | Screen time, home/office geofence events | HTTPS POST to Lambda function URL | 06 |
| Weather and pollen APIs | Daily/hourly weather, pollen | EventBridge schedule | 07 |

## Storage

- **Raw:** S3, immutable JSON, `raw/<source>/<data_type>/dt=YYYY-MM-DD/` (UTC date). Block public access, encryption, versioning.
- **Curated:** Iceberg tables in a Glue database, one per data type, partitioned by month on event timestamp. Written by DuckDB in Lambda.
- **State:** DynamoDB watermark table (one item per source and data type).
- **Secrets:** SSM Parameter Store SecureString.

## Processing

- Ingestion Lambdas: idempotent, exponential backoff on 429/5xx, reserved concurrency 1.
- Transform Lambda: raw JSON → flatten → `MERGE INTO` Iceberg.
- Compaction: scheduled weekly (rewrite small files, expire snapshots, remove orphans).
- Morning chain (Step Functions): merge previous day → metrics vs 30-day baseline → Bedrock summary → build static HTML dashboard.

## Serving

- Static HTML on S3 + CloudFront; Cognito login via Lambda@Edge (step 09).

## Cross-cutting

- Timestamps stored in UTC.
- Infrastructure in Terraform (`infra/`), remote state in S3 with native locking.
- CI/CD via GitHub Actions with OIDC; apply gated by manual approval.
- Cost: free tiers first, serverless only, no always-on compute.

## Open questions

- Local-date handling (daylight saving) for sleep and daily metrics.
- Watermark strategy for late-synced device data.
- Interim protection for the dashboard before step 09.
- Pollen data source for the home location.
