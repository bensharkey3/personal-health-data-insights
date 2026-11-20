# 0003: UTC timestamps plus a derived local date

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

Timestamps are stored in UTC, but "last night's sleep", daily totals and 30-day baselines depend on the local day, which shifts with daylight saving.

## Decision

- All event timestamps are stored in UTC.
- Curated tables add a `local_date` column, computed at transform time from a configured IANA time zone. The time zone is configuration (SSM/Terraform variable), never hard-coded in the repo.
- A sleep session is assigned to the local date of its end (the day you woke up).
- Raw S3 partitions (`dt=YYYY-MM-DD`) stay UTC dates.

## Consequences

- Daily metrics line up with the local day, including across DST changes.
- Travel to other time zones is not modelled; records use the home time zone. Revisit if that matters.
- Changing the configured time zone requires recomputing `local_date` (rerun transforms from raw).
