"""Where and in which time zone the phone was (D29). The phone's daily send adds a line
`<epoch>,location,<lat>,<lon>,<IANA zone>` to its Tasker batch, rounded to about 1 km. Each
timestamp elsewhere takes the zone of the latest fix at or before it (a DuckDB ASOF JOIN), so
local dates follow travel; before the first fix, the TIME_ZONE config applies."""

import os

# Fallback zone before the first phone fix. Set by Terraform from the TIME_ZONE secret (D27).
TIME_ZONE = os.environ.get("TIME_ZONE", "UTC")


def fixes(files: list[str]) -> str:
    """SELECT of (ts, lat, lon, time_zone) for a CTE: a fallback row at the epoch, plus every valid
    location line in the given Tasker CSV files. Zones are checked against DuckDB's list, as a
    bad one would fail the run. Paths are ours (temp dir), not user input."""
    fallback = (
        "SELECT TIMESTAMPTZ '1970-01-01 00:00:00+00' AS ts, NULL::DOUBLE AS lat,"
        f" NULL::DOUBLE AS lon, '{TIME_ZONE}' AS time_zone"
    )
    if not files:
        return fallback
    paths = ", ".join(f"'{f}'" for f in files)
    return f"""{fallback}
        UNION
        SELECT to_timestamp(t::BIGINT), lat::DOUBLE, lon::DOUBLE, tz
        FROM read_csv([{paths}], header = false, auto_detect = false,
            null_padding = true, ignore_errors = true,
            columns = {{'t': 'VARCHAR', 'e': 'VARCHAR', 'lat': 'VARCHAR', 'lon': 'VARCHAR',
                        'tz': 'VARCHAR'}})
        WHERE e = 'location' AND regexp_full_match(t, '[0-9]{{9,11}}')
            AND regexp_full_match(lat, '-?[0-9]{{1,2}}(\\.[0-9]+)?')
            AND regexp_full_match(lon, '-?[0-9]{{1,3}}(\\.[0-9]+)?')
            AND tz IN (SELECT name FROM pg_timezone_names())"""


def query(files: list[str]) -> str:
    """Curated locations: one row per local date with the day's latest fix (the morning one)."""
    return f"""
        WITH f AS ({fixes(files)})
        SELECT (ts AT TIME ZONE time_zone)::DATE AS local_date,
            arg_max(lat, ts) AS lat, arg_max(lon, ts) AS lon, arg_max(time_zone, ts) AS time_zone
        FROM f WHERE lat IS NOT NULL
        GROUP BY local_date ORDER BY local_date"""
