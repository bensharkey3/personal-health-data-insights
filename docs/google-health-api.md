# Google Health API: POC findings

What we learnt from `src/ingest/google_health/poc.py`, probe scripts run against my account, and the [official docs](https://developers.google.com/health) (November 2026). Use this when building step 03 ingestion. No data values are recorded here.

## Access

- Base URL: `https://health.googleapis.com/v4/users/me/dataTypes/<type>/dataPoints`
- OAuth "Desktop app" client with PKCE and a loopback redirect; three read-only scopes: `googlehealth.activity_and_fitness`, `googlehealth.health_metrics_and_measurements`, `googlehealth.sleep`.
- Consent screen is External in Testing mode, so refresh tokens may expire after 7 days. This needs solving before scheduled ingestion (step 03).
- Methods per type: `list` (GET `.../dataPoints`), `reconcile` (GET `.../dataPoints:reconcile`, merges sources), `rollUp` and `dailyRollUp` (POST, totals over fixed windows). The [data types page](https://developers.google.com/health/data-types) lists which each type supports.
- Data from both phone and old Fitbit comes through the same API; `dataSource` on each record says which (`platform` is `FITBIT` or `HEALTH_CONNECT`, plus device form factor and manufacturer).

## Data types

The history from my old Fitbit runs from October 2024 until it was lost in October 2026 (D11). "Continues" means new data still arrives from the phone. "Fitbit Air" says whether the planned device should supply it, from third-party spec sites ([SensorSpecs](https://sensorspecs.fyi/device/google-fitbit-air), [Gadgets & Wearables](https://gadgetsandwearables.com/technical-specs/fitbit-air/)); Google's own [spec page](https://store.google.com/us/product/google_fitbit_air_specs?hl=en-US) couldn't be read, so treat it as likely, not confirmed.

**In scope** (D13): only these core metrics are ingested and used. All continue on the Fitbit Air; only steps continues on the phone meanwhile:

- Heart: `heart-rate`, `daily-resting-heart-rate`
- HRV: `heart-rate-variability`, `daily-heart-rate-variability`
- Sleep: `sleep`
- SpO2: `oxygen-saturation`, `daily-oxygen-saturation`
- Respiratory rate: `daily-respiratory-rate`, `respiratory-rate-sleep-summary`
- Temperature: `daily-sleep-temperature-derivations`
- Steps: `steps`

| Type ID | In scope | Shape | Main fields | Continues? | Fitbit Air |
| --- | --- | --- | --- | --- | --- |
| `steps` | Yes | interval | `count` | Yes (phone) | Yes |
| `distance` | No | interval | distance | Yes (phone) | Yes |
| `active-minutes` | No | interval | active minutes | Yes | Yes |
| `activity-level` | No | interval | activity level | Yes | Yes |
| `active-energy-burned` | No | interval | activity calories | Yes | Yes |
| `active-zone-minutes` | No | interval | active zone minutes | No | Very likely (calculated from heart rate; not listed) |
| `sedentary-period` | No | interval | sedentary period | No | Yes |
| `exercise` | No | session | workout details | No | Yes (auto-detected) |
| `heart-rate` | Yes | sample (every few seconds) | bpm | No | Yes (every 2 s) |
| `daily-resting-heart-rate` | Yes | daily | `beatsPerMinute`, calculation method | No | Yes |
| `heart-rate-variability` | Yes | sample (during sleep) | RMSSD ms, high/low-frequency power | No | Yes |
| `daily-heart-rate-variability` | Yes | daily | average HRV ms, deep-sleep RMSSD, non-REM heart rate, entropy | No | Yes |
| `time-in-heart-rate-zone` | No | interval | time per zone | No | Yes |
| `daily-heart-rate-zones` | No | daily | zone thresholds | No | Yes |
| `oxygen-saturation` | Yes | sample (overnight) | SpO2 | No | Yes |
| `daily-oxygen-saturation` | Yes | daily | SpO2 | No | Yes |
| `daily-respiratory-rate` | Yes | daily | breaths per minute during sleep | No | Yes |
| `respiratory-rate-sleep-summary` | Yes | sample (1 per night) | breaths per minute, std dev and signal-to-noise for deep, light, REM and full sleep | No | Yes |
| `daily-sleep-temperature-derivations` | Yes | daily | nightly skin temperature °C, baseline, 30-day std dev | No | Yes |
| `sleep` | Yes | session | interval, stage timeline, stage summary (minutes and count), minutes asleep/awake/to fall asleep, short awakenings, main-sleep flag | No | Yes (stages) |
| `total-calories`, `calories-in-heart-rate-zone` | No | rollUp only | calories per window | Yes | Yes |
| `floors` | No | rollUp only | floors climbed | No | **No** (no barometric altimeter) |
| `altitude` | No | interval | altitude | No | **No** (no altimeter; may come from phone GPS during workouts) |
| `vo2-max`, `run-vo2-max`, `daily-vo2-max` | No | occasional | cardio fitness | No | **Not listed** (may still be estimated from heart rate and phone GPS runs) |
| `swim-lengths-data` | No | interval | swim lengths | No | **Not listed** (water resistant to 5 ATM, but swim tracking isn't mentioned) |
| `weight`, `height` | No | manual entries | profile values | n/a | n/a |

- **RollUp only:** `floors` (also `reconcile`), `total-calories`, `calories-in-heart-rate-zone`. No `list`.
- **Not available in any API:** Fitbit's sleep score, readiness, stress, cardio load and energy score. They're calculated in the Fitbit app (several are Premium) and were never in the legacy Fitbit Web API either ([sleep docs](https://dev.fitbit.com/build/reference/web-api/sleep/get-sleep-log-by-date/), [forum](https://community.fitbit.com/t5/Web-API-Development/Web-API-for-Readiness-Score-and-Stress-data/m-p/5579874)). A Fitbit data export (Google Takeout) may include them; unverified. A sleep score could be approximated from the sleep, heart rate and HRV fields.
- **On the Air but not in the API:** the Air computes Daily Readiness and Cardio Load in the app; neither is exposed (see above). It has no ECG or EDA sensor, which the old Fitbit didn't give us data for either.
- **Overlap:** `steps` and `distance` were recorded by both phone and Fitbit; use `reconcile`/`rollUp`, which pick one source per interval (D12, and see [Multiple sources](#multiple-sources-phone-and-fitbit)).

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

The pattern held for all 28 list types tried: `<type_snake>.interval.civil_start_time` (interval), `.sample_time.civil_time` (sample), `.date` (daily), `.interval.civil_end_time` (sleep). So ingestion config needs a filter field per type, not just a type ID.

## Consistency: list vs rollUp

- **Interval types (e.g. steps) are unstable with `list` and `reconcile`:** repeated identical requests for the same past day returned the same step total chopped into different intervals (one day ranged from about 500 to 1,700 Fitbit records). There's no stable record to key on. Google doesn't document this.
- **`rollUp` is stable:** fixed windows (60 s, 15 min, 1 h) returned identical windows and totals on every run. Windows with no data are omitted. Response: `rollupDataPoints[]` with `startTime`, `endTime` and e.g. `steps.countSum`. So interval types are ingested with `rollUp` (D12).
- **Samples, daily and session types were stable with `list`** (e.g. `heart-rate` returned the same 35,230 readings every run).
- `rollUp` body: `{"range": {"startTime", "endTime"}, "windowSize": "60s", "pageSize": 10000}`; `dailyRollUp` uses civil dates and `windowSizeDays`. Both take an optional `dataSourceFamily`.

## Multiple sources (phone and Fitbit)

`dataSourceFamily` accepts `users/me/dataSourceFamilies/` + `all-sources` (default), `google-wearables`, `google-sources` or `self-sources`. Tested on steps:

| Day | `list`, all sources | `reconcile` / `rollUp` |
| --- | --- | --- |
| Watch and phone | watch + phone + a Fitbit-labelled copy of the phone steps (about 2x) | watch steps only: the overlapping phone steps are dropped |
| Phone only | phone + the Fitbit-labelled copy (exactly 2x) | about the phone total (merged per interval, +6%) |

- Summing raw `list` records double counts, even with no watch: the Fitbit app copies phone steps under platform `FITBIT` with no device.
- `reconcile` and `rollUp` pick between sources per interval rather than adding them, so the totals match what the apps show. `dataSourceFamily` doesn't separate phone from watch cleanly (the copy counts as a wearable).
- Per-device figures would need the raw `list` source fields summed into fixed windows in the transform, handling the copy. Not planned.
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
