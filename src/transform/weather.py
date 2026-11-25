"""Weather (D30) to a curated daily table.

Each raw file is one 05:00 run: yesterday (actual) and today (forecast) at the phone's location,
in that place's local time. A date's newest run wins, so tomorrow's run replaces today's forecast
with actuals; `is_forecast` marks a date only a forecast covers so far. Hourly temperatures are
merged the same way, newest run per hour, for the night's temperature. Air quality (D32) comes as
hourly values from a separate reply per run, merged newest run per hour and summarised per local
date. Files are passed oldest run first, so a file's position is its run order."""

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


_AIR = [  # (Open-Meteo hourly field, column): µg/m³, except us_aqi (0-500)
    ("pm2_5", "pm25"),
    ("pm10", "pm10"),
    ("ozone", "ozone"),
    ("nitrogen_dioxide", "no2"),
    ("us_aqi", "aqi"),
]
_AIR_DAILY = [  # (column, expression over the merged hours)
    ("pm25_mean", "round(avg(pm25), 1)"),
    ("pm25_max", "round(max(pm25), 1)"),
    ("pm10_mean", "round(avg(pm10), 1)"),
    ("ozone_max", "round(max(ozone), 1)"),
    ("no2_mean", "round(avg(no2), 1)"),
    ("aqi_max", "max(aqi)::INT"),
]


def _runs(files: list[str]) -> str:
    """Each file's JSON, with its position in the list as the run order (oldest first)."""
    paths = ", ".join(f"'{f}'" for f in files)
    return (
        f"SELECT json AS j, list_position([{paths}], filename) AS run"
        f" FROM read_ndjson_objects([{paths}], filename = true)"
    )


def _night(rows: str, value: str, name: str) -> str:
    """Mean of value from 22:00 the evening before to 06:00, per weather date (D3)."""
    return f"""
        SELECT days.local_date, round(avg({rows}.{value}), 1) AS {name}
        FROM days JOIN {rows} ON {rows}.hour >= days.local_date::TIMESTAMP - INTERVAL 2 HOUR
            AND {rows}.hour < days.local_date::TIMESTAMP + INTERVAL 6 HOUR
        GROUP BY days.local_date"""


def _air(files: list[str]) -> str:
    """CTEs aq (daily air quality) and an (overnight PM2.5); empty but typed with no files yet."""
    if not files:
        cols = ", ".join(f"NULL::DOUBLE AS {c}" for c, _ in _AIR_DAILY)
        return f"""aq AS (SELECT NULL::DATE AS local_date, {cols} WHERE false),
        an AS (SELECT NULL::DATE AS local_date, NULL::DOUBLE AS night_pm25 WHERE false)"""
    hourly = ", ".join(_unnest("hourly", f, "DOUBLE", c) for f, c in _AIR)
    daily = ", ".join(f"{e} AS {c}" for c, e in _AIR_DAILY)
    return f"""ar AS ({_runs(files)}),
        ah AS (
            SELECT * FROM (
                SELECT run, {_unnest("hourly", "time", "TIMESTAMP", "hour")}, {hourly} FROM ar
            ) QUALIFY row_number() OVER (PARTITION BY hour ORDER BY run DESC) = 1
        ),
        aq AS (SELECT hour::DATE AS local_date, {daily} FROM ah GROUP BY 1),
        an AS ({_night("ah", "pm25", "night_pm25")})"""


def _unnest(block: str, field: str, typ: str, name: str) -> str:
    """Unnested side by side, DuckDB zips the arrays, one row per element."""
    return f"unnest(from_json(j->'$.{block}.{field}', '[\"VARCHAR\"]'))::{typ} AS {name}"


def query(files: list[str], air_files: list[str] = ()) -> str:
    """One row per local date. night_temp_c and night_pm25 are means from 22:00 the evening
    before to 06:00, the night that ends that morning (sleep belongs to the date it ends, D3)."""
    daily = ", ".join(
        _unnest("daily", f, t, n) for f, t, n in [("time", "DATE", "local_date")] + _DAILY
    )
    return f"""
        WITH r AS ({_runs(files)}),
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
        n AS ({_night("h", "temp", "night_temp_c")}),
        {_air(list(air_files))}
        SELECT days.* EXCLUDE (daylight_s), round(daylight_s / 3600, 2) AS daylight_hours,
            n.night_temp_c, aq.* EXCLUDE (local_date), an.night_pm25
        FROM days LEFT JOIN n USING (local_date) LEFT JOIN aq USING (local_date)
            LEFT JOIN an USING (local_date)
        ORDER BY local_date"""
