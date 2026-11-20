# 0003: UTC plus local date

Accepted, 2026-11-20

**Context:** Daily metrics depend on the local day, which shifts with daylight saving.

**Decision:** Store timestamps in UTC. Curated tables add `local_date`, computed from a time zone held in config (never in the repo). Sleep belongs to the date it ends. Raw `dt=` partitions stay UTC.

**Consequences:** Travel isn't modelled. Changing the time zone means rerunning transforms.
