# Step 07: Weather

**Goal:** daily weather alongside the health data, at wherever I actually was that day (D29, D30).

## Scope

- Open-Meteo: free, no key or account, Bureau of Meteorology models for Australia, and an archive for history. It's CC BY 4.0, so the step 08 dashboard credits "Weather data by Open-Meteo.com"
- No fixed location or schedule. After each phone batch, the transform builds `curated/tasker/locations` and invokes `phdi-weather` with the last 7 local dates, each at that day's location fix, carried forward on days without one. Dates before the first fix are skipped. A missed morning is filled in by the next batch
- `phdi-weather` makes one request per date, covering the date and the evening before, with `timezone=auto` so hours are local to that place. Dates older than 60 days use the archive API. Each response is stored as-is in `raw/weather/daily/dt=<date>/run=<ts>.jsonl.gz`, then the transform rebuilds the table. It logs counts only, never coordinates
- `curated/weather/daily/data.parquet`, one row per `local_date` from the newest raw file per date (later runs replace forecast values with observed ones): `time_zone`, `temp_max_c`, `temp_min_c`, `apparent_max_c`, `precipitation_mm`, `humidity_pct`, `wind_max_kmh`, `uv_max`, `sunrise_local`, `sunset_local`, `daylight_hours`, and `night_temp_c`, the mean from 22:00 the evening before to 06:00 (the night that ends that morning, D3)

## Setup

Nothing beyond step 06: the phone's daily location fix drives it. To fetch weather by hand (laptop, D18):
```
aws lambda invoke --function-name phdi-weather --cli-binary-format raw-in-base64-out \
  --payload '{"days": [{"date": "YYYY-MM-DD", "lat": LAT, "lon": LON}]}' out.json
```

## Done when

- A week of weather is in the curated table and joins to sleep on `local_date`

## Out of scope

Pollen (not covered for Australia), air quality, paid APIs.
