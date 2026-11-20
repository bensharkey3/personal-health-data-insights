# Step 05: Iceberg tables and DuckDB transforms

**Goal:** curated, queryable Iceberg tables built from raw data.

## Scope

- Glue database; one Iceberg table per data type, partitioned by month on event timestamp
- DuckDB (iceberg extension) packaged for Lambda, attaching the Glue catalog
- Transform Lambda: reads new raw JSON, flattens it, MERGE INTO the Iceberg table (create-then-insert, no CTAS)
- Start with a spike: confirm DuckDB MERGE INTO works against the Glue catalog with the packaged version; fall back to PyIceberg upsert if not (D5)
- Curated tables add a local_date column from the configured time zone; sleep assigned to the local date it ends (D3)
- DuckDB and its extensions packaged as a shared Lambda layer (D10)
- Monthly partitions; weekly EventBridge-scheduled Lambda running Athena OPTIMIZE and VACUUM on each table (D5)

## Done when

- A steps table returns correct row counts for a test day, in DuckDB and in Athena; device tables follow when the Fitbit arrives (D11)
- Re-running a day produces no duplicate rows

## Out of scope

Dashboard, AI summary.
