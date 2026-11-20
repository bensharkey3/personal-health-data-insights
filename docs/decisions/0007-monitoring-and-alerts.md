# 0007: Error, freshness and cost alerts

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

Without alerts, an expired token or failing Lambda fails silently and is only noticed as a stale dashboard.

## Decision

- CloudWatch alarms on errors for every Lambda and on failed Step Functions executions.
- A daily freshness check that alarms if any source has no new data for 24 hours (read from the watermark table).
- Alarms publish to one SNS topic with an email subscription. The email address is configuration, never committed.
- An AWS Budgets alert at about $2/month.
- All log groups get a retention period (start with 14 days).

## Consequences

- Problems surface within a day, at no cost within free tiers (10 alarms, 1,000 SNS emails, 2 budgets).
- Expected gaps (device not worn) will trigger freshness alerts; tune thresholds per source if that becomes noisy.
