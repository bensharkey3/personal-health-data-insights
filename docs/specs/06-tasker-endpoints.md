# Step 06: Phone screen time and home/office presence (Automate)

**Goal:** phone screen time and home/office presence land in the pipeline automatically, once a day when bedtime mode ends (D24, D25).

## Scope

- The phone (Automate, D26) logs screen on/off and home/office Wi-Fi changes to a local CSV file, one `<UTC epoch seconds>,<event>` line each. Events: `screen_on`, `screen_off`, `home_on`, `home_off`, `office_on`, `office_off`. Network names and coordinates never leave the phone
- When bedtime mode ends in the morning, Automate POSTs the batch to the `phdi-tasker` function URL with the shared secret, and deletes it only after a 2xx reply, so a failed send is retried the next morning (D25)
- The receiver stores the body gzipped as-is in `raw/tasker/events/dt=<UTC date received>/run=<ts>.csv.gz`, then starts the transform. Bodies with no valid lines write nothing
- The transform rebuilds two tables from all phone raw files on every batch:
  - `curated/tasker/screen_sessions/data.parquet`: `start_utc`, `end_utc`, `minutes`, `local_date`, `start_hour_local`
  - `curated/tasker/places/data.parquet`: `place`, plus the same columns
  - Repeated lines from a re-sent batch are removed. An `_on` without a following `_off` is dropped, as are screen sessions over 12 h

## Setup

Block names and options below are from Automate's docs as I understand them; confirm each on the phone. Each flow loops: wait for a change, write a line, go back to the wait.

1. Create the secret (laptop, after deploy):
   ```
   MSYS_NO_PATHCONV=1 aws ssm put-parameter --name /phdi/tasker/secret --type SecureString --value "Bearer $(openssl rand -hex 32)"
   ```
2. Phone settings: Automate's battery use **Unrestricted**, location **Allow all the time** (Android only reveals Wi-Fi names to apps with it), and Do Not Disturb access.
3. Flow **screen**: **Display on?** with *Proceed: When changed*, then **File write**, file `phdi/events.csv`, *Append* on, content `{floor(now)},screen_on\n` from the yes path or `{floor(now)},screen_off\n` from the no path. `now` is epoch seconds.
4. Flow **places**: the same loop with **Wi-Fi connected?** (*When changed*, SSID = your home network), writing `home_on` / `home_off`. Duplicate it for the office network. The SSIDs live only in the flow on the phone.
5. Flow **send**: **Interruption mode?** with *When changed*, continuing only when it's back to all notifications (bedtime mode ended). Then:
   1. **File move** `phdi/events.csv` to `phdi/sending/{floor(now)}.csv` (its failure path just continues, as there may be no new events).
   2. **File list** `phdi/sending`, then **For each** file:
      - **File read text** into `body`.
      - **HTTP request**: POST to the function URL, header `Authorization` = the secret, body `body`, content type `text/csv`, response status into `status`.
      - **File delete** the file if `status >= 200 && status < 300`.
   3. Back to the wait.

   The function URL (`aws lambda get-function-url-config --function-name phdi-tasker`) and the secret (`aws ssm get-parameter --name /phdi/tasker/secret --with-decryption`) go into this flow's variables on the phone only.
6. Start all three flows. Run **send** once by hand (with a few screen events logged) and check a `raw/tasker/events/` file appears in S3.
7. About 30 blocks in total, around the free version's limit of blocks running at once; the premium unlock removes it. Flows can be exported as `.flo` files: blank the URL, secret and SSIDs before any is committed.

## Done when

- A POST without the secret gets 401; an empty POST with it gets 204 and writes nothing
- A night of screen sessions and a day of home/office stays appear in the curated Parquet

## Out of scope

Per-app usage, GPS tracking, immediate (non-batched) sending.
