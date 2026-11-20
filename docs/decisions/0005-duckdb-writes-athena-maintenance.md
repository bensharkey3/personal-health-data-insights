# 0005: DuckDB writes, Athena maintenance

Accepted, 2026-11-20

**Context:** DuckDB's Iceberg writes are new, and it can't compact or expire snapshots.

**Decision:** Transforms use DuckDB `MERGE INTO`, proven by a spike at the start of step 05; PyIceberg `upsert` is the fallback (needs dependency approval). A weekly Lambda runs Athena `OPTIMIZE` and `VACUUM`.

**Consequences:** Adds Athena (fractions of a cent) and a results bucket with expiry. Use only Iceberg features both engines support.
