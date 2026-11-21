# Step 08: Morning chain, AI summary and dashboard

**Goal:** each morning, a fresh dashboard and AI summary of last night's sleep and readiness.

## Scope

- Trigger: completed sleep session arrives via webhook (no fixed time). Until a Fitbit Air there is no new sleep data, so start on a daily schedule, and show device metrics as missing rather than failing (D11)
- Step Functions chain: merge previous day into Iceberg → compute metrics vs 30-day baseline (sleep, HRV, resting HR, respiratory rate, skin temperature) → Bedrock AI summary → build dashboard
- Dashboard Lambda: DuckDB queries, Plotly charts, AI summary at top, mobile-friendly static HTML
- S3 + CloudFront hosting behind an unguessable private link, with a CloudFront Function checking an interim credential (D4)
- Runs once per morning even if several sleep notifications arrive
- Readiness: a green/amber/red light with a one-sentence reason, from HRV, resting HR and sleep vs baseline, at the top of the dashboard. Every metric is shown with its usual range, not as a bare number, so a glance says whether today is normal
- Illness warning: flagged in the summary when skin temperature, resting HR and respiratory rate are all above baseline together, which often shows a day or two before feeling ill
- Push the readiness line and any illness flag to my phone, so I don't have to open the dashboard
- Personal correlations in plain sentences (weekly insights): a weekly EventBridge run precomputes a few correlations (screen time vs sleep, office vs home days, steps vs deep sleep, weather vs sleep) and Bedrock writes them as sentences, e.g. "After nights with over an hour of screen time after 10 pm, you slept 25 minutes less." Shown on the dashboard below the readiness light. Only pairs whose data exists are included, and only differences big enough to mean something

## Done when

- After waking and syncing, the dashboard and summary update within minutes
- The readiness line reaches my phone each morning, and weekly insights update on Sundays
- Monthly AWS cost for the chain stays near zero (check in Cost Explorer)

## Out of scope

Login, interactive filtering.
