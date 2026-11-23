"""Flattening SQL per Google Health type: raw API pages (one JSON object per line) in, one typed
row per data point out, with local_date (D3) and the source platform. Field paths are from the
record shapes in docs/google-health-api.md; many numbers arrive as strings, so all are cast."""

TIME_ZONE = "Australia/Melbourne"  # only for steps, whose rollUp windows are UTC (D17)

_SOURCE = "r->>'$.dataSource.platform' AS platform"


def _cols(obj: str, cols: list[tuple[str, str, str]]) -> str:
    return ", ".join(f"(r->>'$.{obj}.{path}')::{typ} AS {name}" for name, path, typ in cols)


def _date(path: str) -> str:
    parts = ", ".join(f"(r->>'$.{path}.{p}')::INT" for p in ("year", "month", "day"))
    return f"make_date({parts})"


def _sample(obj: str, cols: list[tuple[str, str, str]]) -> str:
    """Samples carry a UTC time plus the local (civil) date the device recorded."""
    t = f"$.{obj}.sampleTime"
    return (
        f"((r->>'{t}.physicalTime')::TIMESTAMPTZ AT TIME ZONE 'UTC') AS time_utc, "
        f"{_date(obj + '.sampleTime.civilTime.date')} AS local_date, {_cols(obj, cols)}, {_SOURCE}"
    )


def _daily(obj: str, cols: list[tuple[str, str, str]]) -> str:
    return f"{_date(obj + '.date')} AS local_date, {_cols(obj, cols)}, {_SOURCE}"


def _stage_minutes(stage: str) -> str:
    shape = '[{"type":"VARCHAR","minutes":"VARCHAR"}]'
    summary = f"from_json(r->'$.sleep.summary.stagesSummary', '{shape}')"
    return (
        f"(list_filter({summary}, lambda s: s.type = '{stage}')[1].minutes)::INT"
        f" AS {stage.lower()}_minutes"
    )


# Sleep belongs to the local date it ends (D3): end time plus the record's own UTC offset.
_SLEEP = ", ".join(
    [
        "((r->>'$.sleep.interval.startTime')::TIMESTAMPTZ AT TIME ZONE 'UTC') AS start_utc",
        "((r->>'$.sleep.interval.endTime')::TIMESTAMPTZ AT TIME ZONE 'UTC') AS end_utc",
        "((r->>'$.sleep.interval.endTime')::TIMESTAMPTZ AT TIME ZONE 'UTC'"
        " + to_seconds(replace(r->>'$.sleep.interval.endUtcOffset', 's', '')::INT))::DATE"
        " AS local_date",
        "r->>'$.sleep.type' AS sleep_type",
        "(r->>'$.sleep.metadata.mainSleep')::BOOLEAN AS main_sleep",
        _cols(
            "sleep.summary",
            [
                ("minutes_asleep", "minutesAsleep", "INT"),
                ("minutes_awake", "minutesAwake", "INT"),
                ("minutes_to_fall_asleep", "minutesToFallAsleep", "INT"),
                ("minutes_in_sleep_period", "minutesInSleepPeriod", "INT"),
            ],
        ),
        *(_stage_minutes(s) for s in ("DEEP", "LIGHT", "REM", "AWAKE")),
        "(r->'$.sleep.stages')::VARCHAR AS stages_json",  # timeline, for a hypnogram later
        _SOURCE,
    ]
)

# Steps are rollUp windows with no source (one per interval already, D12); empty ones dropped.
_STEPS = (
    "((r->>'$.startTime')::TIMESTAMPTZ AT TIME ZONE 'UTC') AS window_start_utc, "
    f"((r->>'$.startTime')::TIMESTAMPTZ AT TIME ZONE '{TIME_ZONE}')::DATE AS local_date, "
    "(r->>'$.steps.countSum')::INT AS steps"
)

_BRPM = [
    (f"{s}_brpm", f"{s}SleepStats.breathsPerMinute", "DOUBLE")
    for s in ("deep", "light", "rem", "full")
]

# type -> (columns, sort column)
SELECTS: dict[str, tuple[str, str]] = {
    "heart-rate": (_sample("heartRate", [("bpm", "beatsPerMinute", "SMALLINT")]), "time_utc"),
    "heart-rate-variability": (
        _sample(
            "heartRateVariability",
            [
                ("rmssd_ms", "rootMeanSquareOfSuccessiveDifferencesMilliseconds", "DOUBLE"),
                ("high_freq_power", "metadata.highFrequencyPower", "DOUBLE"),
                ("low_freq_power", "metadata.lowFrequencyPower", "DOUBLE"),
            ],
        ),
        "time_utc",
    ),
    "oxygen-saturation": (
        _sample("oxygenSaturation", [("spo2_pct", "percentage", "DOUBLE")]),
        "time_utc",
    ),
    "respiratory-rate-sleep-summary": (
        _sample("respiratoryRateSleepSummary", _BRPM),
        "time_utc",
    ),
    "daily-resting-heart-rate": (
        _daily("dailyRestingHeartRate", [("bpm", "beatsPerMinute", "SMALLINT")]),
        "local_date",
    ),
    "daily-heart-rate-variability": (
        _daily(
            "dailyHeartRateVariability",
            [
                ("avg_hrv_ms", "averageHeartRateVariabilityMilliseconds", "DOUBLE"),
                (
                    "deep_rmssd_ms",
                    "deepSleepRootMeanSquareOfSuccessiveDifferencesMilliseconds",
                    "DOUBLE",
                ),
                ("non_rem_bpm", "nonRemHeartRateBeatsPerMinute", "DOUBLE"),
                ("entropy", "entropy", "DOUBLE"),
            ],
        ),
        "local_date",
    ),
    "daily-oxygen-saturation": (
        _daily(
            "dailyOxygenSaturation",
            [
                ("avg_pct", "averagePercentage", "DOUBLE"),
                ("lower_pct", "lowerBoundPercentage", "DOUBLE"),
                ("upper_pct", "upperBoundPercentage", "DOUBLE"),
                ("stddev_pct", "standardDeviationPercentage", "DOUBLE"),
            ],
        ),
        "local_date",
    ),
    "daily-respiratory-rate": (
        _daily("dailyRespiratoryRate", [("brpm", "breathsPerMinute", "DOUBLE")]),
        "local_date",
    ),
    "daily-sleep-temperature-derivations": (
        _daily(
            "dailySleepTemperatureDerivations",
            [
                ("nightly_c", "nightlyTemperatureCelsius", "DOUBLE"),
                ("baseline_c", "baselineTemperatureCelsius", "DOUBLE"),
                ("stddev_30d_c", "relativeNightlyStddev30dCelsius", "DOUBLE"),
            ],
        ),
        "local_date",
    ),
    "sleep": (_SLEEP, "start_utc"),
    "steps": (_STEPS, "window_start_utc"),
}


def query(kind: str, files: list[str]) -> str:
    """One query over the given local .jsonl.gz files. Paths are ours (temp dir), not user input."""
    cols, order = SELECTS[kind]
    points = "rollupDataPoints" if kind == "steps" else "dataPoints"
    paths = ", ".join(f"'{f}'" for f in files)
    where = "WHERE steps > 0" if kind == "steps" else ""
    return (
        f"SELECT * FROM (SELECT {cols} FROM ("
        f"SELECT unnest(json_extract(json, '$.{points}[*]')) AS r"
        f" FROM read_ndjson_objects([{paths}]))) {where} ORDER BY {order}"
    )
