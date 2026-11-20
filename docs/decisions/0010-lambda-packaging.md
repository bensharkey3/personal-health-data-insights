# 0010: Lambda packaging

Accepted, 2026-11-20

**Context:** DuckDB downloads extensions at runtime, which Lambda doesn't allow.

**Decision:** One zip per function, built by `uv` in CI. A shared layer holds DuckDB and its pre-downloaded extensions. Plotly ships only with the dashboard function.

**Consequences:** No ECR cost. The layer is rebuilt when DuckDB's version changes.
