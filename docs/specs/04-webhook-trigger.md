# Step 04: Webhook subscription trigger

**Goal:** ingestion runs automatically whenever my Fitbit Air syncs.

## Scope

- Lambda function URL (no API Gateway) as the webhook endpoint
- Register a Google Health data subscription; handle subscriber verification
- Validate incoming notifications; invoke the step 3 ingestion for the affected data types
- Ignore or coalesce bursts (several notifications per sync)

## Done when

- Opening the Google Health app on my phone results in new raw files in S3 within minutes, with no manual step
- Unverified requests are rejected

## Out of scope

Transforms, morning chain.
