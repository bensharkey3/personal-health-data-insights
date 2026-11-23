# Step 06: Tasker screen time and home/office presence

**Goal:** phone screen time and home/office presence land in the pipeline automatically, once a day when bedtime mode ends (D24, D25).

## Scope

- Tasker logs screen on/off and home/office Wi-Fi changes to a local CSV file, one `<UTC epoch seconds>,<event>` line each. Events: `screen_on`, `screen_off`, `home_on`, `home_off`, `office_on`, `office_off`. Network names and coordinates never leave the phone
- When bedtime mode ends in the morning, Tasker POSTs the batch to the `phdi-tasker` function URL with the shared secret, and deletes it only after a 2xx reply, so a failed send is retried the next morning (D25)
- The receiver stores the body gzipped as-is in `raw/tasker/events/dt=<UTC date received>/run=<ts>.csv.gz`, then starts the transform. Bodies with no valid lines write nothing
- The transform rebuilds two tables from all Tasker raw files on every batch:
  - `curated/tasker/screen_sessions/data.parquet`: `start_utc`, `end_utc`, `minutes`, `local_date`, `start_hour_local`
  - `curated/tasker/places/data.parquet`: `place`, plus the same columns
  - Repeated lines from a re-sent batch are removed. An `_on` without a following `_off` is dropped, as are screen sessions over 12 h

## Setup

1. Create the secret (laptop, after deploy):
   ```
   MSYS_NO_PATHCONV=1 aws ssm put-parameter --name /phdi/tasker/secret --type SecureString --value "Bearer $(openssl rand -hex 32)"
   ```
2. In Tasker (Variables tab), create `%PHDI_URL` and `%PHDI_SECRET`. Their values come from `aws lambda get-function-url-config --function-name phdi-tasker` and `aws ssm get-parameter --name /phdi/tasker/secret --with-decryption`. They stay on the phone.
3. Logging profiles. Each task is one action, **File → Write File**, file `phdi/events.csv`, with **Append** and **Add Newline** ticked:

   | Profile | Trigger | Text written |
   | --- | --- | --- |
   | Screen on | Event → Display → Display On | `%TIMES,screen_on` |
   | Screen off | Event → Display → Display Off | `%TIMES,screen_off` |
   | Home | State → Net → Wifi Connected, your home SSID | entry `%TIMES,home_on`, exit task `%TIMES,home_off` |
   | Office | State → Net → Wifi Connected, your office SSID | entry `%TIMES,office_on`, exit task `%TIMES,office_off` |

4. Send profile, triggered by State → Audio → Do Not Disturb (bedtime mode turns it on), with the send task as its **exit** task, so it runs when bedtime mode ends. Exempt Tasker from battery optimisation. The task:
   1. **File → Move File**: `phdi/events.csv` to `phdi/sending/%TIMES.csv`. Tick *Continue Task After Error*, since there may be no new events.
   2. **File → List Files**: `phdi/sending`, into `%files`.
   3. **Task → For**: `%file` over `%files()`.
      - **File → Read File**: `%file` into `%body`.
      - **Net → HTTP Request**: POST to `%PHDI_URL`, header `Authorization:%PHDI_SECRET`, body `%body`, MIME type `text/csv`. Tick *Continue Task After Error*.
      - **File → Delete File**: `%file`, If `%http_response_code` matches `2*`.
   4. **Task → End For**.
5. Run the send task once by hand to check it.

## Done when

- A POST without the secret gets 401; an empty POST with it gets 204 and writes nothing
- A night of screen sessions and a day of home/office stays appear in the curated Parquet

## Out of scope

Per-app usage, GPS tracking, immediate (non-batched) sending.
