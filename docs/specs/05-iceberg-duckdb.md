# Step 05: Iceberg tables and DuckDB transforms

**Goal:** curated, queryable Iceberg tables built from raw data.

## Scope

- Glue database; one Iceberg table per data type, partitioned by month on event timestamp
- DuckDB (iceberg extension) packaged for Lambda, attaching the Glue catalog
- Transform Lambda: reads new raw JSON, flattens it, MERGE INTO the Iceberg table (create-then-insert, no CTAS)
- Monthly partitions; scheduled compaction Lambda (EventBridge, e.g. weekly) that rewrites small files, expires old snapshots and removes orphan files

## Done when

- Tables for heart rate, steps and sleep return correct row counts for a test day, in DuckDB and in Athena
- Re-running a day produces no duplicate rows

## Out of scope

Dashboard, AI summary.
