# 0002: Rolling-window ingestion with downstream dedupe

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

The device can sync hours or days after data was recorded. A watermark based on the newest data timestamp (minus 1 hour) would skip records that arrive late with older timestamps.

## Decision

- Every ingestion run re-fetches a fixed rolling lookback (start with 72 hours, configurable per data type), regardless of the watermark.
- The watermark (DynamoDB, one item per source and data type) records the last successful run and the newest data point seen; it is used for backfill and monitoring, not to narrow the fetch window.
- Raw writes stay immutable; duplicates are removed by `MERGE INTO` on a natural key in the transform step.

## Consequences

- Late-synced data is picked up as long as it arrives within the lookback.
- More API calls and overlapping raw files than a precise watermark; volumes are tiny, so cost is negligible.
- Every curated table needs a well-defined natural key for dedupe.
- Gaps longer than the lookback need a manual backfill run.
