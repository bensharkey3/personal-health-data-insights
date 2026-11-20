# 0007: Monitoring and alerts

Accepted, 2026-11-20

**Context:** Failures would otherwise only show up as a stale dashboard.

**Decision:** Error alarms on every Lambda and on Step Functions. A daily check alarms if any source has no new data for 24 hours. All alarms email via SNS (address in config). An AWS Budgets alert at about $2/month. 14-day log retention.

**Consequences:** Free tier. Days without the device worn will alert; tune thresholds if that gets noisy.
