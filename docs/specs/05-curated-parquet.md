# Step 05: Curated Parquet with DuckDB transforms

**Goal:** typed, deduplicated tables built from raw data, which the Step 08 dashboard and local DuckDB can query (D23).

## Scope

- Transform Lambda `phdi-transform`: for each type-month it lists the raw files, keeps the newest per `dt=` folder, flattens them with DuckDB and writes `curated/google_health/<type>/month=YYYY-MM/data.parquet`, replacing the old file
- The old Step 2 `pages.jsonl.gz` files sort before `run=…`, so they count only when they're a day's only file (D19)
- One SQL `SELECT` per type in `src/transform/google_health.py`: string numbers cast, source platform kept, `local_date` from the record's civil date (samples, daily), its end time plus UTC offset (sleep, D3), or `Australia/Melbourne` (steps, whose windows are UTC, D17). Steps drop empty windows. The sleep stage timeline is kept as JSON for a hypnogram later
- Ingestion invokes the transform asynchronously after each run with `{"days": {"<type>": [...]}}`, listing only days that had data
- DuckDB 2.0 as a Lambda layer, built by CI for arm64 (`manylinux_2_28`). Its wheel bundles the json, parquet and icu extensions
- Raw files are downloaded to `/tmp` with boto3, so DuckDB needs no S3 extension in Lambda

## Events

- `{"days": {"<type>": ["YYYY-MM-DD", ...]}}`: rebuild the months those days fall in (sent by ingestion)
- `{"start": "YYYY-MM", "end": "YYYY-MM"}`: rebuild those months for every type (manual, and Step 10)

## Querying locally

With `aws login` credentials and `uv run python`:
```python
import duckdb

duckdb.sql("CREATE SECRET (TYPE s3, PROVIDER credential_chain)")
duckdb.sql(
    "SELECT local_date, avg(bpm) FROM read_parquet('s3://<bucket>/curated/google_health/heart-rate/*/*.parquet') GROUP BY 1"
)
```
Or `aws s3 sync` the `curated/` prefix to a folder outside the repo and query the files offline. Steps partitions follow the UTC day of the raw file, so a few windows near midnight land in the neighbouring month; filter on `local_date`, not on the folder.

## Done when

- One historical day of heart rate, steps and sleep gives the same row counts in curated Parquet as in raw
- Rebuilding the same month again gives identical row counts (no duplicates)

## Out of scope

Glue/Athena tables, dashboard, AI summary.
