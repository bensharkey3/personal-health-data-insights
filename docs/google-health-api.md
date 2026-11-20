# Google Health API: POC findings

What we learnt from `src/ingest/google_health/poc.py`, probe scripts run against my account, and the [official docs](https://developers.google.com/health) (November 2026). Use this when building step 03 ingestion. No data values are recorded here.

## Access

- Base URL: `https://health.googleapis.com/v4/users/me/dataTypes/<type>/dataPoints`
- OAuth "Desktop app" client with PKCE and a loopback redirect; three read-only scopes: `googlehealth.activity_and_fitness`, `googlehealth.health_metrics_and_measurements`, `googlehealth.sleep`.
- Consent screen is External in Testing mode, so refresh tokens may expire after 7 days. This needs solving before scheduled ingestion (step 03).
- Methods per type: `list` (GET `.../dataPoints`), `reconcile` (GET `.../dataPoints:reconcile`, merges sources), `rollUp` and `dailyRollUp` (POST, totals over fixed windows). The [data types page](https://developers.google.com/health/data-types) lists which each type supports.
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

Also in the docs and readable with our scopes, not probed yet: `active-energy-burned` (activity calories), `daily-vo2-max`, `respiratory-rate-sleep-summary`, `altitude`, `swim-lengths-data`.

- **RollUp only:** `floors` (also `reconcile`), `total-calories`, `calories-in-heart-rate-zone`. No `list`.
- **Not available in any API:** Fitbit's sleep score, readiness, stress, cardio load and energy score. They're calculated in the Fitbit app (several are Premium) and were never in the legacy Fitbit Web API either ([sleep docs](https://dev.fitbit.com/build/reference/web-api/sleep/get-sleep-log-by-date/), [forum](https://community.fitbit.com/t5/Web-API-Development/Web-API-for-Readiness-Score-and-Stress-data/m-p/5579874)). A Fitbit data export (Google Takeout) may include them; unverified. A sleep score could be approximated from the sleep, heart rate and HRV fields.
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

## Consistency: list vs rollUp

- **Interval types (e.g. steps) are unstable with `list` and `reconcile`:** repeated identical requests for the same past day returned the same step total chopped into different intervals (one day ranged from about 500 to 1,700 Fitbit records). There's no stable record to key on. Google doesn't document this.
- **`rollUp` is stable:** fixed windows (60 s, 15 min, 1 h) returned identical windows and totals on every run. Windows with no data are omitted. Response: `rollupDataPoints[]` with `startTime`, `endTime` and e.g. `steps.countSum`. So interval types are ingested with `rollUp` (D12).
- **Samples, daily and session types were stable with `list`** (e.g. `heart-rate` returned the same 35,230 readings every run).
- `rollUp` body: `{"range": {"startTime", "endTime"}, "windowSize": "60s", "pageSize": 10000}`; `dailyRollUp` uses civil dates and `windowSizeDays`. Both take an optional `dataSourceFamily`.
- Not yet checked: whether `rollUp` adds phone and Fitbit steps together for the overlap period (D11). Compare totals with and without `dataSourceFamily` in step 03.
- Range limits per request: 14 days for `heart-rate`, `active-minutes`, `total-calories`, `calories-in-heart-rate-zone`; 90 days for everything else.

## Pagination and performance

- `list` page size: docs say default 1,440 and max 10,000, but we saw a default of **50**, and requests above 5,000 returned **5,000**. Always set it. `sleep` and `exercise` are capped at 25 per page.
- Results are newest first. Follow `nextPageToken` until it's absent.
- A page takes about 1–2 seconds regardless of size (1,000 or 5,000 records).
- One day of `heart-rate` is about 35,000 readings: 8 pages at 5,000, about 15 s. With the default size the POC ran for 10+ minutes without finishing.

## Memory and storage (for Lambda)

Measured on one day of `heart-rate`:

| Held in memory | Response | Parsed in Python | Gzipped |
| --- | --- | --- | --- |
| 1 page (5,000) | 1.8 MB | 9 MB | 0.04 MB |
| Whole day (35k) | 12 MB | 64 MB | 0.25 MB |

- Write each page to S3 as its own gzipped file as it arrives, rather than collecting a day first (the POC's approach). Memory stays around 10–20 MB, so a 128–256 MB Lambda is enough; confirm from the Lambda's max-memory log line.
- Gzip shrinks this data about 50x, so the full history is a few hundred MB in S3. DuckDB reads `.json.gz` directly.
- Backfill one day (or one type-day) per invocation to stay well under Lambda's 15-minute limit; most time is spent waiting on the API.
- Rate limits weren't hit during probing, but haven't been measured either. Backfill should stay slow (D2).

## Errors seen

- `400 Invalid data type ID ...`: the type doesn't exist.
- `400 List is not supported for data type ...`: the type exists but needs another action.
- `400 Invalid data point filter: INVALID_DATA_POINT_FILTER_RESTRICTION_COMPARATOR`: wrong comparator for the field (e.g. `=` on a daily date).
