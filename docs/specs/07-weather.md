# Step 07: Weather

**Goal:** daily environmental context alongside my health data.

## Scope

- Choose a free weather API for my home location (set in SSM/config, never in this repo; record the choice in docs/decisions.md)
- EventBridge-scheduled Lambda, daily (or hourly for weather), raw JSON to S3
- Iceberg table for weather

## Done when

- A week of weather data is queryable and joins to health data by date

## Out of scope

Air-quality sensors or paid APIs.
