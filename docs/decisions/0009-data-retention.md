# 0009: Keep data indefinitely, with a delete-everything runbook

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

Personal health and location data volumes are tiny (megabytes per year), and longer history improves baselines.

## Decision

- Raw and curated data are kept indefinitely; there are no expiry lifecycle rules on data.
- Operational data does expire: Athena query results, noncurrent S3 object versions and old Iceberg snapshots (via ADR 0005), and CloudWatch logs (via ADR 0007).
- A runbook documents how to delete all personal data (buckets, tables, logs, SSM parameters).

## Consequences

- Curated tables can always be rebuilt from raw.
- Storage cost stays negligible; revisit if volumes grow.
