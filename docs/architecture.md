# Architecture

Single-user serverless pipeline on AWS. The why behind each choice is in [decisions/](decisions/).

```
Fitbit (Google Health) ─webhook─┐
Tasker (phone) ──function URL───┼─▶ Ingest Lambdas ─▶ S3 raw JSON ─▶ DuckDB transform ─▶ Iceberg (Glue)
Weather/pollen ──schedule───────┘                                                          │
                                       Dashboard + AI summary (CloudFront) ◀─ Morning chain ┘
```

| Layer | What | ADR |
| --- | --- | --- |
| Ingest | Rolling 72h re-fetch; DynamoDB watermark; backoff, concurrency 1 | 0002 |
| Raw | S3 `raw/<source>/<data_type>/dt=YYYY-MM-DD/` (UTC), immutable, encrypted, versioned | 0001 |
| Curated | Iceberg table per data type, monthly partitions, `local_date` column, `MERGE INTO` dedupe | 0003, 0005 |
| Maintenance | Weekly Athena `OPTIMIZE` / `VACUUM` | 0005 |
| Morning chain | Step Functions: merge day → metrics vs 30-day baseline → Bedrock summary → static HTML | |
| Serving | S3 + CloudFront; CloudFront Function auth, then Cognito in step 09 | 0004 |
| Infra / CI | Terraform (CloudShell bootstrap, then GitHub Actions + OIDC); zips + DuckDB layer | 0006, 0010 |
| Ops | Error + freshness alarms, $2 budget, 14-day logs; keep data indefinitely | 0007, 0009 |
| Region | `ap-southeast-2` (+ `us-east-1` for CloudFront) | 0008 |

## Open questions

- Step 07: pollen source for the home location (Open-Meteo pollen is Europe-only).
- Step 08: timed fallback if no sleep data arrives; summary delivery channel; what data goes to Bedrock.
