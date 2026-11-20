# Step 10: Full backfill and go-live

**Goal:** load all available history for the in-scope metrics (D13), then keep it up to date automatically (D14).

## Scope

- Run the step 03 backfill mode for each in-scope type, from the old Fitbit's first day (October 2024) to today, day by day at a slow pace, resumable from the watermark if interrupted
- Run the step 05 transforms over the backfilled raw data
- Switch on the ongoing incremental loads: Google Health webhook subscription (step 04), Tasker endpoints (step 06), weather schedule (step 07), morning chain (step 08)
- Check cost after the first week

## Done when

- Every in-scope type has curated rows from its first available day to today, with no gaps beyond the known device gap (D11)
- New data arrives automatically for a week with no manual step, and freshness alarms stay quiet

## Out of scope

Types outside D13.
