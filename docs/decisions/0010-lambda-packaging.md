# 0010: Lambda packaging with zips and a shared layer

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

Lambdas need DuckDB (and its Iceberg/httpfs/aws extensions), Plotly and boto3. DuckDB normally downloads extensions at runtime into a home directory, which Lambda doesn't allow.

## Decision

- Each function is a small zip built by `uv` in CI.
- One shared Lambda layer holds DuckDB and its pre-downloaded extensions; functions point `extension_directory` at the layer path.
- Plotly ships only with the dashboard function.

## Consequences

- No ECR storage costs; stays within the 250 MB unzipped limit.
- The layer is versioned and rebuilt when the DuckDB version changes; extensions must match the DuckDB version and Lambda's architecture.
