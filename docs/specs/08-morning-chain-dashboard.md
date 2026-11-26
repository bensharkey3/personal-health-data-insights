# Step 08: Morning chain, AI summary and dashboard

**Goal:** each morning, a fresh dashboard and AI summary of last night's sleep and readiness.

Built in three parts: **8a** the dashboard (below, done first), **8b** the Bedrock summary and weekly insights, **8c** the push to my phone. The scope list after 8a covers all three.

## 8a: Dashboard

- `src/dashboard/build.py` builds one static page from the curated Parquet, phone-sized, light and dark, no JavaScript: a readiness light with its reason, an illness flag, weather and air quality (yesterday's actuals, today's forecast), and a card per metric showing the latest value against its usual range (the middle half of the previous 30 days), ▲/▼ outside it, and a 30-day SVG sparkline. Missing device data shows as "no data since …" (D11). Whole-day totals (steps, screen time, home/office) show the last complete day, since today's is still counting at 6am
- The transform rebuilds it after every data rebuild, not on ticks, and puts `index.html` in the private site bucket (D33). Today's date comes from the phone's zone (D29)
- CloudFront serves it over HTTPS from the default `*.cloudfront.net` address, with a CloudFront Function checking HTTP Basic auth against a SHA-256 hash of the expected header (D34). The address is never output or logged

### Setup (once, from the phone)

Terraform makes the password, so nothing is needed before merging (D34). After the deploy, in the AWS console in the phone's browser:
1. Systems Manager → Parameter Store → `/phdi/dashboard/password` → show the decrypted value
2. CloudFront → Distributions → the one commented `phdi-dashboard` → its distribution domain name
3. Open that address, sign in as `me` with the password, and bookmark it. The page appears after the next data update, or at once via Lambda → `phdi-transform` → Test with `{"source": "weather"}`

## Scope

- Trigger: completed sleep session arrives via webhook (no fixed time). Until a Fitbit Air there is no new sleep data, so start on a daily schedule, and show device metrics as missing rather than failing (D11)
- Step Functions chain: rebuild the previous day's curated Parquet → compute metrics vs 30-day baseline (sleep, HRV, resting HR, respiratory rate, skin temperature) → Bedrock AI summary → build dashboard
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
