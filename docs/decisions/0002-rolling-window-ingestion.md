# 0002: Rolling-window ingestion

Accepted, 2026-11-20

**Context:** The device can sync days late, so fetching from "newest data point minus 1 hour" would miss data.

**Decision:** Each run re-fetches a rolling lookback (72 hours to start, configurable per data type). The DynamoDB watermark records the last run and newest data point, for backfill and freshness checks. `MERGE INTO` on a natural key removes duplicates.

**Consequences:** Overlapping raw files (negligible cost). Every curated table needs a natural key. Gaps longer than the lookback need a manual backfill.
