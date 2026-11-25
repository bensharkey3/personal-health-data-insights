# Step 06: Phone screen time and home/office presence (Tasker)

**Goal:** phone screen time and home/office presence land in the pipeline automatically, once a day when bedtime mode ends (D24, D25).

## Scope

- Tasker (project file `src/ingest/tasker/phdi.prj.xml`, D28) logs screen on/off and home/office Wi-Fi changes to a local CSV file, one `<UTC epoch seconds>,<event>` line each. Events: `screen_on`, `screen_off`, `home_on`, `home_off`, `office_on`, `office_off`. Network names and coordinates never leave the phone
- The send first adds one coarse network location fix (no GPS) with the phone's time zone: `<epoch>,location,<lat>,<lon>,<IANA zone>`, rounded to 2 decimals (D29). It drives local dates and the weather location; it's skipped if there's no fix
- When bedtime mode ends in the morning, Tasker POSTs the batch to the `phdi-tasker` function URL with the shared secret, and deletes it only after a 2xx reply, so a failed send is retried the next morning (D25)
- The receiver stores the body gzipped as-is in `raw/tasker/events/dt=<UTC date received>/run=<ts>.csv.gz`, then starts the transform. Bodies with no valid lines write nothing
- The transform rebuilds two tables from all phone raw files on every batch:
  - `curated/tasker/screen_sessions/data.parquet`: `start_utc`, `end_utc`, `minutes`, `local_date`, `start_hour_local`
  - `curated/tasker/places/data.parquet`: `place`, plus the same columns
  - `curated/tasker/locations/data.parquet`: `local_date`, `lat`, `lon`, `time_zone`, the day's latest fix (D29)
  - Repeated lines from a re-sent batch are removed. An `_on` without a following `_off` is dropped, as are screen sessions over 12 h

## Setup

Everything on the phone comes from one imported file. Its trigger and action codes come from a community reference ([Tasker-XML-Info](https://github.com/Taskomater/Tasker-XML-Info)), as Tasker doesn't document its format; if the import fails, export one small profile made by hand and match the file to it.

1. Create the secret (laptop, after deploy):
   ```
   MSYS_NO_PATHCONV=1 aws ssm put-parameter --name /phdi/tasker/secret --type SecureString --value "Bearer $(openssl rand -hex 32)"
   ```
2. Install Tasker. In Android settings give it battery use **Unrestricted** and location **Allow all the time** (Android only reveals Wi-Fi names to apps with it).
3. Download `phdi.prj.xml` (raw link on GitHub) to the phone. In Tasker, long-press the Projects tab (bottom left) → **Import Project** → pick the file.
4. VARS tab → **+**: `%PHDI_URL` (from `aws lambda get-function-url-config --function-name phdi-tasker`) and `%PHDI_SECRET` (from `aws ssm get-parameter --name /phdi/tasker/secret --with-decryption`). They stay on the phone.
5. In profiles **phdi home** and **phdi office**, tap the Wifi Connected condition and replace `SET_HOME_SSID` / `SET_OFFICE_SSID` with your network names.
6. Test: turn the screen off and on a few times, check `phdi/events.csv` has lines like `1795000000,screen_on`, then run task **phdi send** with ▶. It's silent on success and flashes a message if anything was kept for retry. A laptop session can then check `raw/tasker/events/` in S3.

What the profiles do:

| Profile | Trigger | Task |
| --- | --- | --- |
| phdi screen on / off | Display On / Off event | Write File: append `%TIMES,screen_on` / `screen_off` to `phdi/events.csv` |
| phdi home / office | Wifi Connected to that network | entry `<place>_on`, exit `<place>_off` |
| phdi send when DND off | Custom Setting `zen_mode` = 0 (Do Not Disturb off, so bedtime mode has ended) | JavaScript: move the log to `phdi/sending/`, POST each file, delete it only after a 2xx |

Logging uses native Write File actions, which cost almost nothing; only the daily send starts JavaScript. If you change the project on the phone and re-export it, put the placeholders back before committing: a test fails if real network names, a URL or the secret are in the file.

## Done when

- A POST without the secret gets 401; an empty POST with it gets 204 and writes nothing
- A night of screen sessions and a day of home/office stays appear in the curated Parquet

## Out of scope

Per-app usage, GPS tracking, immediate (non-batched) sending.
