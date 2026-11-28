# Step 11: Garmin activities

**Goal:** my Garmin workouts in the pipeline and on the dashboard, from Garmin's official Personal API (D39).

## Scope

- `phdi-garmin-ingest` runs daily at 06:00 phone-local, started by the transform's tick with the other daily runs (D31). It swaps the personal API key for a 24-hour token (`POST https://personal.connectapi.garmin.com/personalapitoken-service/personal-api/personal-api-key/token`, `Authorization: ApiKey <key>`), then pages through `/activitylist-service/activities/search/activities` with `startDate`/`endDate`
- Window: from one day before the newest activity seen (watermark) to tomorrow, at most 7 days back. `{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"}` backfills a range
- Raw: one object per run, `raw/garmin/activities/dt=<UTC date>/run=<ts>.jsonl.gz`, each line one page as `{"activities": [...]}`. Runs with no activities write nothing
- `curated/garmin/activities/data.parquet`, one row per activity, newest run's copy winning: `activity_id`, `name`, `type`, `start_local`, `start_utc`, `local_date`, `duration_s`, `distance_m`, `avg_hr`, `max_hr`, `calories`, `elevation_gain_m`, `aerobic_effect`, `training_load`
- Dashboard **Training** section: the last activity, sessions this week against the previous 4 weeks' average, and active minutes a week for 12 weeks. Complete days only (D38)
- A rejected key (401/403) fails the run with "renew it", so the errors alarm emails me. Logs show counts only, never the key, token or activity details

## Setup (phone, once a year)

1. Garmin Connect → create a **Personal API key**, valid for **one year**. It's shown once, so copy it straight away
2. AWS console → Systems Manager → Parameter Store → create or edit `/phdi/garmin/api_key`, type **SecureString**, value the key
3. Lambda → `phdi-garmin-ingest` → Test with `{}`. The result shows how many activities it found, and the page's Training section fills in a minute later
4. Optional history: Test with `{"start": "2026-01-01", "end": "2026-11-30"}`

Garmin emails about a week before the key expires: repeat steps 1-2.

## Done when

- Recent activities show in the Training section, and a new workout appears the morning after

## Out of scope

FIT files and per-second data, Garmin health data (Fitbit covers it), Strava.
