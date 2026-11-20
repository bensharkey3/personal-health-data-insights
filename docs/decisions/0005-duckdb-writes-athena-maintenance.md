# 0005: DuckDB for transforms, Athena for Iceberg maintenance

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

DuckDB's Iceberg write support (including `MERGE INTO` against the Glue catalog) is recent and partial, and DuckDB cannot compact files, expire snapshots or remove orphan files.

## Decision

- Transform Lambdas use DuckDB to flatten raw JSON and write Iceberg tables with `MERGE INTO`.
- Step 05 starts with a spike proving `MERGE INTO` works with the packaged DuckDB version and the Glue catalog. If it doesn't, fall back to PyIceberg `upsert` for writes (a new dependency, which needs approval at that point).
- A weekly EventBridge-scheduled Lambda runs Athena `OPTIMIZE` (compaction) and `VACUUM` (snapshot expiry and orphan-file removal) on each table.

## Consequences

- Keeps DuckDB as the main engine for learning, with a mature managed tool for maintenance.
- Adds Athena (pay per data scanned, fractions of a cent at this volume) and an Athena results bucket with a lifecycle expiry.
- Tables must be readable by both DuckDB and Athena, so stick to Iceberg features both support.
