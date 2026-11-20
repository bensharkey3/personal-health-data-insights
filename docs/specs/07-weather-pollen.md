# Step 07: Weather and pollen

**Goal:** daily environmental context alongside my health data.

## Scope

- Choose free weather and pollen APIs for my home location (set in SSM/config, never in this repo; record the choice in docs/decisions.md)
- EventBridge-scheduled Lambda, daily (or hourly for weather), raw JSON to S3
- Iceberg tables for weather and pollen

## Done when

- A week of weather and pollen data is queryable and joins to health data by date

## Out of scope

Air-quality sensors or paid APIs.
