# Step 07: Weather

**Goal:** yesterday's actual weather and today's forecast, at wherever I am (D29, D30).

## Scope

- Open-Meteo: free, no key or account, Bureau of Meteorology models for Australia, and an archive for history. It's CC BY 4.0, so the step 08 dashboard credits "Weather data by Open-Meteo.com"
- `phdi-weather` runs daily at 05:00 in the phone's current time zone, started by the transform's 15-minute tick (D31). It fetches at the phone's latest location fix, which the transform keeps in `curated/tasker/locations/latest.json` after each phone batch. Before the first fix it does nothing
- One request, `past_days=1&forecast_days=1` with `timezone=auto`: yesterday (actual) and today (forecast), in that place's local time, daily values plus hourly temperature. The response is stored as-is in `raw/weather/daily/dt=<UTC date>/run=<ts>.jsonl.gz`, then the transform rebuilds the table. It logs counts only, never coordinates
- `curated/weather/daily/data.parquet`, one row per `local_date`, newest run winning, so the next morning replaces a forecast with actuals: `time_zone`, `temp_max_c`, `temp_min_c`, `apparent_max_c`, `precipitation_mm`, `humidity_pct`, `wind_max_kmh`, `uv_max`, `sunrise_local`, `sunset_local`, `daylight_hours`, `is_forecast`, and `night_temp_c`, the mean from 22:00 the evening before to 06:00 (the night that ends that morning, D3), from the newest run per hour
- The location is the latest fix, normally the previous morning's, so on the morning after a trip the first run may use the old place; the next day's run corrects yesterday. A missed run leaves that day's forecast in place

## Setup

Nothing beyond step 06. To run it by hand (laptop, D18): `aws lambda invoke --function-name phdi-weather --payload '{}' out.json`

## Done when

- A week of weather is in the curated table, with yesterday as actuals and today flagged `is_forecast`, and it joins to sleep on `local_date`

## Out of scope

Pollen (not covered for Australia), air quality, paid APIs.
