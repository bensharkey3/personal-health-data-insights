# Step 08: Morning chain, AI summary and dashboard

**Goal:** each morning, a fresh dashboard and AI summary of last night's sleep and readiness.

## Scope

- Trigger: completed sleep session arrives via webhook (no fixed time)
- Step Functions chain: merge previous day into Iceberg → compute metrics vs 30-day baseline (sleep, HRV, resting HR, skin temperature) → Bedrock AI summary → build dashboard
- Dashboard Lambda: DuckDB queries, Plotly charts, AI summary at top, mobile-friendly static HTML
- S3 + CloudFront hosting behind an unguessable private link, with a CloudFront Function checking an interim credential (D4)
- Runs once per morning even if several sleep notifications arrive

## Done when

- After waking and syncing, the dashboard and summary update within minutes
- Monthly AWS cost for the chain stays near zero (check in Cost Explorer)

## Out of scope

Login, interactive filtering, summary delivery channel (still to decide).
