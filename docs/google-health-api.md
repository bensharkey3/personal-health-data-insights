# Google Health API: POC findings

What we learnt from `src/ingest/google_health/poc.py` and probe scripts run against my account (November 2026). Use this when building step 03 ingestion. No data values are recorded here.

## Access

- Base URL: `https://health.googleapis.com/v4/users/me/dataTypes/<type>/dataPoints`
- OAuth "Desktop app" client with PKCE and a loopback redirect; three read-only scopes: `googlehealth.activity_and_fitness`, `googlehealth.health_metrics_and_measurements`, `googlehealth.sleep`.
- Consent screen is External in Testing mode, so refresh tokens may expire after 7 days. This needs solving before scheduled ingestion (step 03).
- Data from both phone and old Fitbit comes through the same API; `dataSource` on each record says which (`platform` is `FITBIT` or `HEALTH_CONNECT`, plus device form factor and manufacturer).

## Data types

The history from my old Fitbit runs from October 2024 until it was lost in October 2026 (D11). "Continues" means new data still arrives from the phone.

| Type ID | Shape | Main fields | Continues? |
| --- | --- | --- | --- |
| `steps` | interval | `count` | Yes (phone) |
| `distance` | interval | distance | Yes (phone) |
| `active-minutes` | interval | active minutes | Yes |
| `activity-level` | interval | activity level | Yes |
| `active-zone-minutes` | interval | active zone minutes | No |
| `sedentary-period` | interval | sedentary period | No |
| `exercise` | session | workout details | No |
| `heart-rate` | sample (every few seconds) | bpm | No |
| `daily-resting-heart-rate` | daily | `beatsPerMinute`, calculation method | No |
| `heart-rate-variability` | sample (during sleep) | RMSSD ms, high/low-frequency power | No |
| `daily-heart-rate-variability` | daily | average HRV ms, deep-sleep RMSSD, non-REM heart rate, entropy | No |
| `time-in-heart-rate-zone` | interval | time per zone | No |
| `daily-heart-rate-zones` | daily | zone thresholds | No |
| `oxygen-saturation` | sample (overnight) | SpO2 | No |
| `daily-oxygen-saturation` | daily | SpO2 | No |
| `daily-respiratory-rate` | daily | breathing rate | No |
| `daily-sleep-temperature-derivations` | daily | nightly skin temperature °C, baseline, 30-day std dev | No |
| `sleep` | session | interval, stage timeline, stage summary (minutes and count), minutes asleep/awake/to fall asleep, short awakenings, main-sleep flag | No |
| `vo2-max`, `run-vo2-max` | occasional | cardio fitness | No |
| `weight`, `height` | manual entries | profile values | n/a |

- **Exist but can't be listed** (the API says other actions are supported, not explored yet): `floors`, `total-calories`.
- **Not available:** Fitbit's sleep score, readiness, stress, cardio load and energy score. A sleep score could be approximated from the sleep, heart rate and HRV fields.
- **Overlap:** `steps` and `distance` were recorded by both phone and Fitbit, so curated tables must keep one source per interval (D11).

## Record formats

- Every record has `dataSource` plus one object named after the type (camelCase, e.g. `dailyHeartRateVariability`).
- Times come three ways: UTC timestamp (`startTime`, `physicalTime`), `utcOffset`, and local "civil" date and time split into year/month/day/hours/minutes fields. The offset on every record means `local_date` can come from the data itself.
- Many numbers arrive as strings (e.g. `steps.count`, `beatsPerMinute`, sleep summary minutes), so transforms must cast them.

## Filtering

`filter` uses snake_case field paths, and each shape needs its own field:

| Shape | Filter field (example) | Notes |
| --- | --- | --- |
| interval | `steps.interval.civil_start_time` | local time, no offset, e.g. `"2026-10-15T00:00:00"` |
| session | `sleep.interval.civil_end_time` | sleep belongs to the day it ends (D3) |
| sample | `heart_rate.sample_time.physical_time` (UTC, with `Z`) or `heart_rate_variability.sample_time.civil_time` | |
| daily | `daily_heart_rate_variability.date` | `>=` and `<` work, `=` is rejected |

So ingestion config needs a filter field per type, not just a type ID.

## Pagination and performance

- Default page size is **50**, maximum **5,000** (larger values are capped). Always set `pageSize=5000`.
- Follow `nextPageToken` until it's absent.
- A page takes about 1–2 seconds regardless of size (1,000 or 5,000 records).
- One day of `heart-rate` is about 35,000 readings: 7 pages at 5,000. With the default size the POC ran for 10+ minutes without finishing.
- Volume: one day of `heart-rate` is about 21 MB as indented JSON, mostly the repeated `dataSource`. Store raw files gzipped (D9 keeps raw data indefinitely).
- Rate limits weren't hit during probing, but haven't been measured either. Backfill should stay slow (D2).

## Errors seen

- `400 Invalid data type ID ...`: the type doesn't exist.
- `400 List is not supported for data type ...`: the type exists but needs another action.
- `400 Invalid data point filter: INVALID_DATA_POINT_FILTER_RESTRICTION_COMPARATOR`: wrong comparator for the field (e.g. `=` on a daily date).
