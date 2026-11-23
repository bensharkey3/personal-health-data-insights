"""Tasker events (D24) to curated tables: screen sessions and home/office stays.

Raw files are CSV, `<UTC epoch seconds>,<event>` per line. All files are read on every rebuild
(a year is about 70k lines); a batch the phone re-sent after a missed reply repeats lines, so
events are de-duplicated, and malformed lines are dropped. Each `<thing>_on` pairs with the next
event for the same thing if that's `<thing>_off`; anything else (a lost event) is dropped."""

from transform.google_health import TIME_ZONE

TABLES = {  # table -> (things, longest believable interval)
    "screen_sessions": ("('screen')", "12 HOURS"),
    "places": ("('home', 'office')", "14 DAYS"),
}


def query(table: str, files: list[str]) -> str:
    things, longest = TABLES[table]
    paths = ", ".join(f"'{f}'" for f in files)
    place = "" if table == "screen_sessions" else "thing AS place, "
    return f"""
        WITH events AS (
            SELECT DISTINCT to_timestamp(t::BIGINT) AS ts,
                split_part(e, '_', 1) AS thing, split_part(e, '_', 2) AS state
            FROM read_csv([{paths}], header = false, auto_detect = false,
                null_padding = true, ignore_errors = true,  -- a malformed line is skipped
                columns = {{'t': 'VARCHAR', 'e': 'VARCHAR'}})
            WHERE regexp_full_match(t, '[0-9]{{9,11}}')
                AND regexp_full_match(e, '(screen|home|office)_(on|off)')
        ), paired AS (
            SELECT thing, state, ts AS start_ts,
                lead(state) OVER w AS next_state, lead(ts) OVER w AS end_ts
            FROM events WHERE thing IN {things}
            WINDOW w AS (PARTITION BY thing ORDER BY ts)
        )
        SELECT {place}start_ts AT TIME ZONE 'UTC' AS start_utc,
            end_ts AT TIME ZONE 'UTC' AS end_utc,
            round(epoch(end_ts - start_ts) / 60, 1) AS minutes,
            (start_ts AT TIME ZONE '{TIME_ZONE}')::DATE AS local_date,
            hour(start_ts AT TIME ZONE '{TIME_ZONE}') AS start_hour_local
        FROM paired
        WHERE state = 'on' AND next_state = 'off' AND end_ts - start_ts <= INTERVAL {longest}
        ORDER BY start_utc"""
