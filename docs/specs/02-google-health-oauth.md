# Step 02: Google Health OAuth and one day of data

**Goal:** prove the cloud can authorise and pull one full day of every in-scope type (D13), using 2026-08-08 from the old Fitbit history (D11).

## Scope

- Google Cloud project, OAuth consent screen and "Desktop app" client, with the consent screen published so the refresh token doesn't expire (D16)
- `src/ingest/google_health/authorise.py`: one-off browser sign-in on the laptop that saves a refresh token outside the repo
- Client ID, client secret and refresh token as SSM SecureString parameters under `/phdi/google/`, created by hand in CloudShell (D15)
- Lambda `phdi-google-health-ingest` (`handler.py`, `client.py`), invoked by hand: refreshes the access token and pulls one day of all 11 types, `list` for most and `rollUp` for steps (D12)

## Raw layout

One object per type-day: `raw/google_health/<type>/dt=YYYY-MM-DD/pages.jsonl.gz`, gzipped JSON Lines with one API response page per line, exactly as returned. Pages stream into the gzip buffer, so memory holds one page at a time. `dt` is the local day the request covered, except steps, where it's the UTC day (D17). Step 03 replaced this with run-stamped files (D19).

## Manual steps

1. **Google Cloud console** > Google Auth Platform > Audience: **Publish app** (In production). Sign-in then shows an "unverified app" warning; continue past it.
2. **Laptop:** `py src/ingest/google_health/authorise.py` signs in and writes `~/.config/health-insights/token.json`.
3. **CloudShell:** for each of `client_id`, `client_secret` (from `client_secret.json`) and `refresh_token` (from `token.json`), paste the value at a hidden prompt, so it stays out of shell history:
   ```
   read -rs v && aws ssm put-parameter --type SecureString --name /phdi/google/client_id --value "$v"; unset v
   ```
4. **CloudShell:** invoke and check:
   ```
   aws lambda invoke --function-name phdi-google-health-ingest --payload '{"date":"2026-08-08"}' --cli-binary-format raw-in-base64-out out.json && cat out.json
   aws s3 ls --recursive s3://$(aws s3 ls | grep -o 'phdi-raw-.*')/raw/google_health/
   ```

## Done when

- All 11 types land under `dt=2026-08-08`, with point counts matching the local extract (except steps, which covers the UTC day)
- No tokens in code, logs or git

## Out of scope

Scheduling, watermarks, webhooks, retries.
