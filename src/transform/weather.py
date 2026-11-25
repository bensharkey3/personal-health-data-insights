"""Weather (D30) to a curated daily table.

Each raw file is one 05:00 run: yesterday (actual) and today (forecast) at the phone's location,
in that place's local time. A date's newest run wins, so tomorrow's run replaces today's forecast
with actuals; `is_forecast` marks a date only a forecast covers so far. Hourly temperatures are
merged the same way, newest run per hour, for the night's temperature. Files are passed oldest run
first, so the file's position is the run order."""

_DAILY = [  # (Open-Meteo field, type, column)
    ("temperature_2m_max", "DOUBLE", "temp_max_c"),
    ("temperature_2m_min", "DOUBLE", "temp_min_c"),
    ("apparent_temperature_max", "DOUBLE", "apparent_max_c"),
    ("precipitation_sum", "DOUBLE", "precipitation_mm"),
    ("relative_humidity_2m_mean", "DOUBLE", "humidity_pct"),
    ("wind_speed_10m_max", "DOUBLE", "wind_max_kmh"),
    ("uv_index_max", "DOUBLE", "uv_max"),
    ("sunrise", "TIMESTAMP", "sunrise_local"),
    ("sunset", "TIMESTAMP", "sunset_local"),
    ("daylight_duration", "DOUBLE", "daylight_s"),
]


def _unnest(block: str, field: str, typ: str, name: str) -> str:
    """Unnested side by side, DuckDB zips the arrays, one row per element."""
    return f"unnest(from_json(j->'$.{block}.{field}', '[\"VARCHAR\"]'))::{typ} AS {name}"


def query(files: list[str]) -> str:
    """One row per local date. night_temp_c is the mean from 22:00 the evening before to 06:00,
    the night that ends that morning (sleep belongs to the date it ends, D3)."""
    paths = ", ".join(f"'{f}'" for f in files)
    daily = ", ".join(
        _unnest("daily", f, t, n) for f, t, n in [("time", "DATE", "local_date")] + _DAILY
    )
    return f"""
        WITH r AS (
            SELECT json AS j, list_position([{paths}], filename) AS run
            FROM read_ndjson_objects([{paths}], filename = true)
        ),
        d AS (
            SELECT run, j->>'$.timezone' AS time_zone, {daily} FROM r
        ),
        days AS (
            SELECT * EXCLUDE (run), local_date = max(local_date) OVER (PARTITION BY run)
                AS is_forecast  -- the last day of a run is today, still a forecast
            FROM d QUALIFY row_number() OVER (PARTITION BY local_date ORDER BY run DESC) = 1
        ),
        h AS (
            SELECT * FROM (
                SELECT run, {_unnest("hourly", "time", "TIMESTAMP", "hour")},
                    {_unnest("hourly", "temperature_2m", "DOUBLE", "temp")} FROM r
            ) QUALIFY row_number() OVER (PARTITION BY hour ORDER BY run DESC) = 1
        ),
        n AS (
            SELECT days.local_date, round(avg(h.temp), 1) AS night_temp_c
            FROM days JOIN h ON h.hour >= days.local_date::TIMESTAMP - INTERVAL 2 HOUR
                AND h.hour < days.local_date::TIMESTAMP + INTERVAL 6 HOUR
            GROUP BY days.local_date
        )
        SELECT days.* EXCLUDE (daylight_s), round(daylight_s / 3600, 2) AS daylight_hours,
            n.night_temp_c
        FROM days LEFT JOIN n USING (local_date)
        ORDER BY local_date"""
