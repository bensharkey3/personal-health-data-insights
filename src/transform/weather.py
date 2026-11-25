"""Weather (D30) to a curated daily table, and which dates and places to fetch it for (D29).

Each raw file is one Open-Meteo response for one date at the phone's location: the date plus the
evening before, in that place's local time. Only the newest file per date is read (later runs
replace forecast values with observed ones), so a full rebuild is cheap and idempotent."""

from datetime import date, timedelta

RECENT_DAYS = 7  # each phone batch refreshes a week, so a missed morning fills itself in


def recent_days(fixes: list[tuple[date, float, float]], days: int = RECENT_DAYS) -> list[dict]:
    """The last `days` local dates up to the latest fix, each at the latest fix on or before it
    (the location carried forward). Dates before the first fix are left out."""
    if not fixes:
        return []
    fixes = sorted(fixes)
    latest = fixes[-1][0]
    out = []
    for n in range(days - 1, -1, -1):  # oldest first
        d = latest - timedelta(n)
        known = [f for f in fixes if f[0] <= d]
        if known:
            _, lat, lon = known[-1]
            out.append({"date": d.isoformat(), "lat": lat, "lon": lon})
    return out


def _daily(field: str, typ: str, name: str) -> str:
    return f"(j->>'$.daily.{field}[1]')::{typ} AS {name}"  # [1]: the date itself, [0] the eve


def query(files: list[str]) -> str:
    """One row per local date. night_temp_c is the mean from 22:00 the evening before to 06:00,
    the night that ends that morning (sleep belongs to the date it ends, D3)."""
    paths = ", ".join(f"'{f}'" for f in files)
    cols = ", ".join(
        [
            _daily("time", "DATE", "local_date"),
            "j->>'$.timezone' AS time_zone",
            _daily("temperature_2m_max", "DOUBLE", "temp_max_c"),
            _daily("temperature_2m_min", "DOUBLE", "temp_min_c"),
            _daily("apparent_temperature_max", "DOUBLE", "apparent_max_c"),
            _daily("precipitation_sum", "DOUBLE", "precipitation_mm"),
            _daily("relative_humidity_2m_mean", "DOUBLE", "humidity_pct"),
            _daily("wind_speed_10m_max", "DOUBLE", "wind_max_kmh"),
            _daily("uv_index_max", "DOUBLE", "uv_max"),
            _daily("sunrise", "TIMESTAMP", "sunrise_local"),
            _daily("sunset", "TIMESTAMP", "sunset_local"),
            "round((j->>'$.daily.daylight_duration[1]')::DOUBLE / 3600, 2) AS daylight_hours",
        ]
    )
    return f"""
        WITH r AS (SELECT json AS j FROM read_ndjson_objects([{paths}])),
        d AS (SELECT {cols}, j FROM r),
        h AS (
            SELECT local_date,
                unnest(from_json(j->'$.hourly.time', '["VARCHAR"]'))::TIMESTAMP AS hour,
                unnest(from_json(j->'$.hourly.temperature_2m', '["DOUBLE"]')) AS temp
            FROM d
        ),
        n AS (
            SELECT local_date, round(avg(temp), 1) AS night_temp_c FROM h
            WHERE hour >= local_date::TIMESTAMP - INTERVAL 2 HOUR
                AND hour < local_date::TIMESTAMP + INTERVAL 6 HOUR
            GROUP BY local_date
        )
        SELECT d.* EXCLUDE (j), n.night_temp_c
        FROM d LEFT JOIN n USING (local_date)
        ORDER BY local_date"""
