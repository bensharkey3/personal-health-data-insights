# Step 06: Tasker endpoints (screen time, geofences)

**Goal:** phone screen time and location land in the pipeline automatically.

## Scope

- Lambda function URL accepting JSON from Tasker, protected by a shared secret header (secret in SSM Parameter Store)
- Payload schemas: nightly screen-time export (per-app usage and screen sessions), geofence enter/exit events for home and office
- Raw JSON to S3; Iceberg tables for screen time and location
- Tasker setup instructions documented (profiles, tasks, HTTP request)

## Done when

- A night of screen time and a day of home/office events appear in their Iceberg tables
- Requests without the secret are rejected

## Out of scope

Full GPS tracking.
