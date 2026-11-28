"""Garmin activities (D39) to a curated table, one row per activity.

Each raw file is one run's pages of the activity list ({"activities": [...]} per line). Runs
overlap, so an activity can appear many times; the newest run's copy wins, as Garmin can update
an activity after upload. Files are passed oldest run first, so a file's position is its run
order. startTimeLocal is the device's own local time, so local dates need no zone lookup. Fields
an activity lacks come out NULL."""

_FIELDS = [  # (JSON path in an activity, type, column)
    ("$.activityName", "VARCHAR", "name"),
    ("$.activityType.typeKey", "VARCHAR", "type"),
    ("$.startTimeLocal", "TIMESTAMP", "start_local"),
    ("$.startTimeGMT", "TIMESTAMP", "start_utc"),
    ("$.duration", "DOUBLE", "duration_s"),
    ("$.distance", "DOUBLE", "distance_m"),
    ("$.averageHR", "DOUBLE", "avg_hr"),
    ("$.maxHR", "DOUBLE", "max_hr"),
    ("$.calories", "DOUBLE", "calories"),
    ("$.elevationGain", "DOUBLE", "elevation_gain_m"),
    ("$.aerobicTrainingEffect", "DOUBLE", "aerobic_effect"),
    ("$.activityTrainingLoad", "DOUBLE", "training_load"),
]


def query(files: list[str]) -> str:
    paths = ", ".join(f"'{f}'" for f in files)
    cols = ", ".join(f"(a->>'{p}')::{t} AS {c}" for p, t, c in _FIELDS)
    return f"""
        WITH pages AS (
            SELECT json AS j, list_position([{paths}], filename) AS run
            FROM read_ndjson_objects([{paths}], filename = true)
        ),
        acts AS (
            SELECT run, unnest(from_json(j->'$.activities', '["JSON"]')) AS a FROM pages
        )
        SELECT (a->>'$.activityId')::BIGINT AS activity_id, {cols},
            (a->>'$.startTimeLocal')::TIMESTAMP::DATE AS local_date
        FROM acts
        WHERE a->>'$.activityId' IS NOT NULL
        QUALIFY row_number() OVER (PARTITION BY activity_id ORDER BY run DESC) = 1
        ORDER BY start_local"""
