# Step 02: Google Health OAuth and one day of data

**Goal:** prove I can authorise and pull one day of my Fitbit Air data.

## Scope

- Google Cloud project, OAuth consent screen and client (manual steps documented in the spec)
- One-off authorisation flow to obtain a refresh token, stored in SSM Parameter Store
- Python module in src/ingest/google_health/ that refreshes the access token and pulls one day of heart rate, steps and sleep. Built before the Fitbit Air arrives: develop against whatever my Android phone already records in Google Health (e.g. steps), and use synthetic fixtures for heart rate and sleep until device data exists
- Run it in the cloud (a manually invoked Lambda), writing raw JSON to S3

## Done when

- One day of phone-recorded data (e.g. steps) lands as raw JSON now; heart rate and sleep confirmed once the device is worn. Raw files go in raw/google_health/<data_type>/dt=YYYY-MM-DD/
- No tokens in code, logs or git

## Out of scope

Scheduling, watermarks, webhooks.
