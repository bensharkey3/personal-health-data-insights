# Step 05: Iceberg tables and DuckDB transforms

**Goal:** curated, queryable Iceberg tables built from raw data.

## Scope

- Glue database; one Iceberg table per data type, partitioned by month on event timestamp
- DuckDB (iceberg extension) packaged for Lambda, attaching the Glue catalog
- Transform Lambda: reads new raw JSON, flattens it, MERGE INTO the Iceberg table (create-then-insert, no CTAS)
- Start with a spike: confirm DuckDB MERGE INTO works against the Glue catalog with the packaged version; fall back to PyIceberg upsert if not (ADR 0005)
- Curated tables add a local_date column from the configured time zone; sleep assigned to the local date it ends (ADR 0003)
- DuckDB and its extensions packaged as a shared Lambda layer (ADR 0010)
- Monthly partitions; weekly EventBridge-scheduled Lambda running Athena OPTIMIZE and VACUUM on each table (ADR 0005)

## Done when

- Tables for heart rate, steps and sleep return correct row counts for a test day, in DuckDB and in Athena
- Re-running a day produces no duplicate rows

## Out of scope

Dashboard, AI summary.
