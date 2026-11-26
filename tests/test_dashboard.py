"""Dashboard (step 08a): usual ranges, readiness, illness flag and the page. Synthetic data only."""

from datetime import date, timedelta

import duckdb

from dashboard import build

TODAY = date(2030, 1, 31)


def days(values: list[float], last: date = TODAY) -> list[tuple[date, float]]:
    return [(last - timedelta(len(values) - 1 - i), v) for i, v in enumerate(values)]


def metric(name: str) -> build.Metric:
    return next(m for m in build.METRICS if m.name == name)


def test_usual_range_and_which_side_is_worse():
    usual = [50.0, 52, 54, 56, 58, 60, 62, 64]  # 25th-75th percentile: 54-62
    low = build.status(metric("HRV"), days(usual + [40]))
    assert low.usual == (54.0, 62.0) and low.side == -1 and low.worse  # low HRV is worse
    high = build.status(metric("Resting HR"), days(usual + [70]))
    assert high.side == 1 and high.worse  # high resting HR is worse
    assert not build.status(metric("At home"), days(usual + [70])).worse  # neither is worse
    few = build.status(metric("HRV"), days([50, 40]))
    assert few.usual is None and few.side == 0  # too few days for a usual range


def by_name(**latest: tuple[list[float], date]) -> dict[str, build.Status]:
    out = {m.name: build.status(m, []) for m in build.METRICS}
    for name, (values, last) in latest.items():
        key = name.replace("_", " ")
        out[key] = build.status(metric(key), days(values, last))
    return out


USUAL = [7.0, 7.2, 7.4, 7.6, 7.8, 8.0, 8.2, 8.4]


def test_readiness_light():
    fine = by_name(Asleep=(USUAL + [7.6], TODAY), HRV=(USUAL + [7.6], TODAY))
    assert build.readiness(fine, TODAY)[0] == "green"
    one = by_name(Asleep=(USUAL + [5.0], TODAY), HRV=(USUAL + [7.6], TODAY))
    assert build.readiness(one, TODAY) == ("amber", "Worse than usual: Asleep.")
    two = by_name(Asleep=(USUAL + [5.0], TODAY), HRV=(USUAL + [5.0], TODAY))
    assert build.readiness(two, TODAY)[0] == "red"
    old = by_name(Asleep=(USUAL, date(2029, 10, 1)))
    assert build.readiness(old, TODAY) == ("grey", "No sleep or heart data since 01 Oct 2029.")
    assert build.readiness(by_name(), TODAY) == ("grey", "No sleep or heart data.")


def test_illness_flag_needs_all_three_high_on_the_same_night():
    high = USUAL + [9.5]
    ill = by_name(Skin_temp=(high, TODAY), Resting_HR=(high, TODAY), Breathing_rate=(high, TODAY))
    assert build.illness(ill)
    normal = USUAL + [7.6]
    two = by_name(Skin_temp=(high, TODAY), Resting_HR=(high, TODAY), Breathing_rate=(normal, TODAY))
    assert not build.illness(two)


def test_sparkline():
    svg = build.sparkline([1, 3, 2])
    assert svg.startswith("<svg") and svg.count(",") == 3
    assert build.sparkline([1]) == ""


def write(path, sql: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    duckdb.sql(f"COPY ({sql}) TO '{path.as_posix()}' (FORMAT parquet)")


def test_page_with_phone_and_weather_but_no_device_data(tmp_path):
    write(
        tmp_path / "curated/tasker/screen_sessions/data.parquet",
        "SELECT DATE '2030-01-31' - i::INT AS local_date, 30.0 AS minutes, 23 AS start_hour_local"
        " FROM range(10) t(i)",
    )
    write(
        tmp_path / "curated/weather/daily/data.parquet",
        "SELECT * FROM (VALUES"
        " (DATE '2030-01-30', false, 12.0, 25.0, 0.5, 8.0, 6.1, 30, 15.2, 4.0),"
        " (DATE '2030-01-31', true, 13.0, 28.0, 0.0, 9.0, 5.0, 25, NULL, NULL))"
        " t(local_date, is_forecast, temp_min_c, temp_max_c, precipitation_mm, uv_max,"
        " pm25_mean, aqi_max, night_temp_c, night_pm25)",
    )
    page = build.build(tmp_path, TODAY, "2030-01-31 18:00 UTC")
    assert "No sleep or heart data." in page and "background: var(--grey)" in page
    assert "Screen after 22:00" in page and "Today (forecast)" in page
    assert "Open-Meteo.com" in page and "$" not in page  # every placeholder filled


def test_day_totals_skip_todays_unfinished_day(tmp_path):
    steps = "curated/google_health/steps/month=2030-01/data.parquet"
    write(
        tmp_path / steps,
        "SELECT DATE '2030-01-31' - i::INT AS local_date, 5000 AS steps FROM range(1, 11) t(i)"
        " UNION ALL SELECT DATE '2030-01-31', 517",  # today so far, at 6am
    )
    [(last, value)] = build.series(tmp_path, metric("Steps"), TODAY)[-1:]
    assert (last, value) == (date(2030, 1, 30), 5000.0)


def test_numbers_have_thousands_separators():
    steps = build.status(metric("Steps"), days([4000.0] * 8 + [12345.0]))
    assert "12,345" in build.card(steps, TODAY) and "4,000–4,000" in build.card(steps, TODAY)


# --- Steps charts ---


def steps_file(tmp_path, rows: str) -> None:
    """rows: a SELECT of (local_date, steps) for one synthetic steps file."""
    write(tmp_path / "curated/google_health/steps/month=2030-01/data.parquet", rows)


def test_steps_charts_by_day_week_and_month(tmp_path):
    # Thursday 2030-01-31 is today. Mon 28 - Wed 30 have 6,000; Mon 21 - Sun 27 have 3,000 except
    # Sunday 27, which is missing; today's partial 517 must not count anywhere.
    steps_file(
        tmp_path,
        "SELECT DATE '2030-01-28' + i::INT AS local_date, 6000 AS steps FROM range(3) t(i)"
        " UNION ALL SELECT DATE '2030-01-21' + i::INT, 3000 FROM range(6) t(i)"
        " UNION ALL SELECT DATE '2030-01-31', 517",
    )
    html = build.period_charts(tmp_path, TODAY, "Steps")
    assert "Yesterday 6,000" in html  # Wed 30
    assert "This week 6,000 a day" in html  # Mon-Wed only: today is still counting
    assert "This month 4,000 a day" in html  # (3 * 6,000 + 6 * 3,000) / 9 days with data
    assert html.count('class="bar"') + html.count('class="bar partial"') == 9 + 2 + 1
    assert html.count('class="bar partial"') == 2  # this week and this month, still going
    assert "<title>27 Jan" not in html  # the missing Sunday is a gap, not a zero bar
    assert "517" not in html


def test_steps_charts_without_data(tmp_path):
    assert "No steps data yet." in build.period_charts(tmp_path, TODAY, "Steps")


def test_bars_scale_to_the_tallest_and_label_every_few():
    svg = build.bars([(f"d{i}", float(i)) for i in range(1, 13)])
    assert svg.count("<rect") == 12 and "<title>d12: 12</title>" in svg
    assert 2 <= svg.count("<text") <= 6  # a few labels, not one per bar


def test_screen_time_charts_in_hours(tmp_path):
    write(
        tmp_path / "curated/tasker/screen_sessions/data.parquet",
        "SELECT DATE '2030-01-28' + i::INT AS local_date, 90.0 AS minutes, 21 AS start_hour_local"
        " FROM range(4) t(i)",  # 1.5 h a day, Mon 28 - Thu 31 (today, not counted)
    )
    html = build.period_charts(tmp_path, TODAY, "Screen time", " h")
    assert "Yesterday 1.5 h" in html and "This week 1.5 h a day" in html
    assert "<title>30 Jan: 1.5 h</title>" in html
    assert "No screen time data yet." in build.period_charts(tmp_path / "x", TODAY, "Screen time")


def test_weather_heading_names_the_place_and_a_travelled_day(tmp_path):
    write(
        tmp_path / "curated/weather/daily/data.parquet",
        "SELECT * FROM (VALUES"
        " (DATE '2030-01-30', false, 12.0, 25.0, 0.5, 8.0, 15.0, 4.0, 'Elsewhere <b>'),"
        " (DATE '2030-01-31', true, 13.0, 28.0, 0.0, 9.0, NULL, NULL, 'Testville, Sample City'))"
        " t(local_date, is_forecast, temp_min_c, temp_max_c, precipitation_mm, uv_max,"
        " night_temp_c, night_pm25, place)",
    )
    place, table = build.weather(tmp_path)
    assert place == "Testville, Sample City"
    assert "<small>Elsewhere &lt;b&gt;</small>" in table  # yesterday was elsewhere; escaped
    assert "Weather and air · Testville, Sample City" in build.build(tmp_path, TODAY, "t")
