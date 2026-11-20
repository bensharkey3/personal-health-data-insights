# 0009: Data retention

Accepted, 2026-11-20

**Decision:** Keep raw and curated data indefinitely; volumes are tiny. Operational data expires: Athena results, old S3 versions and Iceberg snapshots, and logs. A runbook covers deleting everything.

**Consequences:** Curated tables can always be rebuilt from raw.
