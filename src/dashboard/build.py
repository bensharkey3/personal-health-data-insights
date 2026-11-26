"""The morning dashboard (step 08a): one static, phone-sized HTML page from the curated Parquet.

Every metric shows its latest value against its usual range, the middle half (25th-75th
percentile) of the 30 days before it, with a sparkline. The readiness light and illness flag are
simple rules over last night's values; the step 08b AI summary will sit above them. Device
metrics without recent data say so instead of failing (D11). The page shows a place name (D35) but never coordinates. Standard library only, apart from DuckDB for the queries."""

import html
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from string import Template

import duckdb

USUAL_DAYS = 30  # the window a value is compared with
SHOWN_DAYS = 30  # sparkline length
GH = "curated/google_health"


@dataclass
class Metric:
    name: str
    unit: str
    sql: str  # SELECT local_date, value over {gh} and {curated}
    higher_is_better: bool | None = None  # None: neither direction is "worse"
    digits: int = 0


def _gh(kind: str, value: str, where: str = "") -> str:
    """Daily values from a curated Google Health type (all its months)."""
    return f"SELECT local_date, {value} FROM '{{gh}}/{kind}/*/*.parquet' {where} GROUP BY 1"


def _cur(table: str, value: str, where: str = "", group: bool = True) -> str:
    """Daily values from a single-file curated table (phone or weather)."""
    by = "GROUP BY 1" if group else ""
    return f"SELECT local_date, {value} FROM '{{curated}}/{table}/data.parquet' {where} {by}"


_SLEPT = "WHERE main_sleep"
_LATE = "WHERE start_hour_local >= 22"
_ACTUAL = "WHERE NOT is_forecast"
METRICS = [
    Metric("Asleep", "h", _gh("sleep", "sum(minutes_asleep) / 60", _SLEPT), True, 1),
    Metric("Deep sleep", "min", _gh("sleep", "sum(deep_minutes)", _SLEPT), True),
    Metric("REM sleep", "min", _gh("sleep", "sum(rem_minutes)", _SLEPT), True),
    Metric("HRV", "ms", _gh("daily-heart-rate-variability", "avg(avg_hrv_ms)"), True),
    Metric("Resting HR", "bpm", _gh("daily-resting-heart-rate", "avg(bpm)"), False),
    Metric("SpO2", "%", _gh("daily-oxygen-saturation", "avg(avg_pct)"), True, 1),
    Metric("Breathing rate", "/min", _gh("daily-respiratory-rate", "avg(brpm)"), False, 1),
    Metric(
        "Skin temp", "°C", _gh("daily-sleep-temperature-derivations", "avg(nightly_c)"), False, 2
    ),
    Metric("Steps", "", _gh("steps", "sum(steps)"), True),
    Metric("Screen time", "h", _cur("tasker/screen_sessions", "sum(minutes) / 60"), False, 1),
    Metric(
        "Screen after 22:00", "min", _cur("tasker/screen_sessions", "sum(minutes)", _LATE), False
    ),
    Metric(
        "At home", "h", _cur("tasker/places", "sum(minutes) / 60", "WHERE place = 'home'"), None, 1
    ),
    Metric(
        "At the office",
        "h",
        _cur("tasker/places", "sum(minutes) / 60", "WHERE place = 'office'"),
        None,
        1,
    ),
    Metric("Night temp", "°C", _cur("weather/daily", "night_temp_c", _ACTUAL, False), None, 1),
    Metric("Night PM2.5", "µg/m³", _cur("weather/daily", "night_pm25", _ACTUAL, False), False, 1),
]
# Totals over a whole day: today's is still counting, so they show the last complete day instead.
# Sleep and the nightly metrics belong to the date they end (D3), so today's value is complete.
DAY_TOTALS = ("Steps", "Screen time", "Screen after 22:00", "At home", "At the office")
READINESS = ("Asleep", "HRV", "Resting HR")  # last night's sleep and recovery
ILLNESS = ("Skin temp", "Resting HR", "Breathing rate")  # all high together: often 1-2 days early


@dataclass
class Status:
    metric: Metric
    series: list[tuple[date, float]]  # oldest first
    latest: tuple[date, float] | None
    usual: tuple[float, float] | None  # 25th-75th percentile of the window before latest

    @property
    def side(self) -> int:
        """+1 above the usual range, -1 below, 0 inside or unknown."""
        if not (self.latest and self.usual):
            return 0
        v, (lo, hi) = self.latest[1], self.usual
        return 1 if v > hi else -1 if v < lo else 0

    @property
    def worse(self) -> bool:
        good = self.metric.higher_is_better
        return good is not None and self.side == (-1 if good else 1)


def series(root: Path, m: Metric, today: date) -> list[tuple[date, float]]:
    sql = m.sql.format(gh=(root / GH).as_posix(), curated=(root / "curated").as_posix())
    try:
        rows = duckdb.sql(
            f"SELECT * FROM ({sql}) t(d, v) WHERE v IS NOT NULL ORDER BY d"
        ).fetchall()
    except duckdb.IOException:  # no files for this metric yet
        return []
    return [(d, float(v)) for d, v in rows if m.name not in DAY_TOTALS or d < today]


def status(m: Metric, data: list[tuple[date, float]]) -> Status:
    if not data:
        return Status(m, [], None, None)
    latest = data[-1]
    window = [v for d, v in data if latest[0] - timedelta(USUAL_DAYS) <= d < latest[0]]
    usual = None
    if len(window) >= 7:  # too few days says little about "usual"
        q = sorted(window)
        usual = (q[len(q) // 4], q[(3 * len(q)) // 4])
    return Status(m, data, latest, usual)


def readiness(by_name: dict[str, Status], today: date) -> tuple[str, str]:
    """(colour, reason) from last night's sleep and recovery; grey without recent device data."""
    recent = [by_name[n] for n in READINESS if by_name[n].latest]
    if not recent or max(s.latest[0] for s in recent) < today - timedelta(1):
        last = max((s.latest[0] for s in recent), default=None)
        since = f" since {last:%d %b %Y}" if last else ""
        return "grey", f"No sleep or heart data{since}."
    worse = [s.metric.name for s in recent if s.worse]
    colour = "green" if not worse else "amber" if len(worse) == 1 else "red"
    reason = (
        "All within your usual range." if not worse else f"Worse than usual: {', '.join(worse)}."
    )
    return colour, reason


def illness(by_name: dict[str, Status]) -> bool:
    flags = [by_name[n] for n in ILLNESS]
    return all(s.latest and s.side == 1 for s in flags) and len({s.latest[0] for s in flags}) == 1


def sparkline(values: list[float], width: int = 120, height: int = 28) -> str:
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    step = width / (len(values) - 1)
    points = " ".join(
        f"{i * step:.1f},{height - 2 - (v - lo) / span * (height - 4):.1f}"
        for i, v in enumerate(values)
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" class="spark" aria-hidden="true">'
        f'<polyline points="{points}"/></svg>'
    )


def card(s: Status, today: date) -> str:
    m, fmt = s.metric, f"{{:,.{s.metric.digits}f}}"  # 12,345
    name = html.escape(m.name)
    if not s.latest:
        return f'<div class="card none"><h3>{name}</h3><p class="v">No data yet</p></div>'
    d, v = s.latest
    stale = d < today - timedelta(1)
    arrow = {1: " ▲", -1: " ▼", 0: ""}[s.side]
    usual = (
        f"usual {fmt.format(s.usual[0])}–{fmt.format(s.usual[1])}"
        if s.usual
        else "usual: too few days"
    )
    when = f"no data since {d:%d %b}" if stale else f"{d:%a %d %b}"
    shown = [x for day, x in s.series if day > d - timedelta(SHOWN_DAYS)]
    cls = "card worse" if s.worse and not stale else "card stale" if stale else "card"
    return (
        f'<div class="{cls}"><h3>{name}</h3>'
        f'<p class="v">{fmt.format(v)} <small>{html.escape(m.unit)}</small>{arrow}</p>'
        f"<p>{usual} · {when}</p>{sparkline(shown)}</div>"
    )


def weather(root: Path) -> tuple[str, str]:
    """(place, table): yesterday's actuals and today's forecast (D30, D32), and where (D35).
    A row from a different place than today's (after travelling) names its own place."""
    path = (root / "curated/weather/daily/data.parquet").as_posix()
    try:  # by column name, so a table from before places (D35) still shows
        rel = duckdb.sql(f"SELECT * FROM '{path}' ORDER BY local_date DESC LIMIT 2")
        rows = [dict(zip(rel.columns, r, strict=True)) for r in rel.fetchall()]
    except duckdb.IOException:
        return "", '<p class="none">No weather yet.</p>'
    here = rows[0].get("place") if rows else None
    out = []
    for r in reversed(rows):
        label = "Today (forecast)" if r["is_forecast"] else f"{r['local_date']:%a %d %b}"
        if r.get("place") and r["place"] != here:
            label += f"<br><small>{html.escape(r['place'])}</small>"
        lo, hi, rain, uv = r["temp_min_c"], r["temp_max_c"], r["precipitation_mm"], r["uv_max"]
        pm, aqi = r.get("pm25_mean"), r.get("aqi_max")

        def f(x, unit="", digits=0):
            return "–" if x is None else f"{x:,.{digits}f}{unit}"

        out.append(
            f"<tr><th>{label}</th><td>{f(lo)}–{f(hi, '°C')}</td><td>{f(rain, ' mm', 1)}</td>"
            f"<td>UV {f(uv)}</td><td>PM2.5 {f(pm, '', 1)}</td><td>AQI {f(aqi)}</td></tr>"
        )
    return (html.escape(here) if here else ""), f'<table class="wx">{"".join(out)}</table>'


CHART_DAYS, CHART_WEEKS, CHART_MONTHS = 30, 12, 12


def bars(
    points: list[tuple[str, float | None]],
    partial_last: bool = False,
    digits: int = 0,
    unit: str = "",
) -> str:
    """An SVG bar chart, one bar per point (label, value); None leaves a gap. The last bar is
    drawn lighter when its period isn't over yet. Each bar's <title> shows on long-press."""
    width, height, label_h = 300, 80, 12
    top = max((v for _, v in points if v is not None), default=0) or 1
    step = width / len(points)
    every = max(1, len(points) // 4)  # a few labels, so they never overlap on a phone
    out = []
    for i, (label, v) in enumerate(points):
        x = i * step
        if v is not None:
            h = v / top * (height - label_h - 2)
            cls = "bar partial" if partial_last and i == len(points) - 1 else "bar"
            out.append(
                f'<rect class="{cls}" x="{x + step * 0.1:.1f}" y="{height - label_h - h:.1f}"'
                f' width="{step * 0.8:.1f}" height="{h:.1f}">'
                f"<title>{html.escape(label)}: {v:,.{digits}f}{html.escape(unit)}</title></rect>"
            )
        last = len(points) - 1
        if i == last or (i % every == 0 and last - i >= every / 2):  # no crowding at the end
            pos = f'x="{x + step / 2:.1f}" text-anchor="middle"'
            if i in (0, last):  # edge labels align inwards, so they aren't cut off
                pos = 'x="0" text-anchor="start"' if i == 0 else f'x="{width}" text-anchor="end"'
            out.append(f'<text {pos} y="{height - 2}">{html.escape(label)}</text>')
    return f'<svg viewBox="0 0 {width} {height}" class="bars" role="img">{"".join(out)}</svg>'


def _month(d: date, back: int) -> date:
    """The first day of the month `back` months before d's month."""
    n = d.year * 12 + d.month - 1 - back
    return date(n // 12, n % 12 + 1, 1)


def period_charts(root: Path, today: date, name: str, unit: str = "") -> str:
    """A daily metric by day (totals), and by week and month (average a day over the days with
    data). Only complete days count, so today is left out (#46). Values keep the metric's digits."""
    m = next(m for m in METRICS if m.name == name)
    days = dict(series(root, m, today))
    if not days:
        return f'<p class="none">No {name.lower()} data yet.</p>'

    def averages(start_of) -> dict[date, float]:
        groups: dict[date, list[float]] = {}
        for d, v in days.items():
            groups.setdefault(start_of(d), []).append(v)
        return {k: sum(v) / len(v) for k, v in groups.items()}

    weeks = averages(lambda d: d - timedelta(d.weekday()))  # ISO weeks start on Monday
    months = averages(lambda d: d.replace(day=1))
    this_week = today - timedelta(today.weekday())
    daily = [(today - timedelta(n)) for n in range(CHART_DAYS, 0, -1)]
    weekly = [this_week - timedelta(7 * n) for n in range(CHART_WEEKS - 1, -1, -1)]
    monthly = [_month(today, n) for n in range(CHART_MONTHS - 1, -1, -1)]
    fmt = f"{{:,.{m.digits}f}}"

    def latest(label: str, value: float | None, per_day: str = "") -> str:
        shown = "–" if value is None else fmt.format(value) + unit
        return f"<p>{label} {shown}{per_day}</p>"

    def chart(points, partial: bool = False) -> str:
        return bars(points, partial_last=partial, digits=m.digits, unit=unit)

    return "".join(
        [
            '<div class="chart"><h3>By day</h3>',
            latest("Yesterday", days.get(today - timedelta(1))),
            chart([(f"{d:%d %b}", days.get(d)) for d in daily]),
            '</div><div class="chart"><h3>By week, average a day</h3>',
            latest("This week", weeks.get(this_week), " a day"),
            chart([(f"{d:%d %b}", weeks.get(d)) for d in weekly], True),
            '</div><div class="chart"><h3>By month, average a day</h3>',
            latest("This month", months.get(_month(today, 0)), " a day"),
            chart([(f"{d:%b}", months.get(d)) for d in monthly], True),
            "</div>",
        ]
    )


def build(root: Path, today: date, built_at: str) -> str:
    """The page for local date `today`, from curated files mirrored under `root`."""
    statuses = [status(m, series(root, m, today)) for m in METRICS]
    by_name = {s.metric.name: s for s in statuses}
    colour, reason = readiness(by_name, today)
    flag = illness(by_name)
    template = Template((Path(__file__).parent / "page.html").read_text())
    place, table = weather(root)
    return template.substitute(
        today=f"{today:%A %d %B %Y}",
        colour=colour,
        reason=html.escape(reason),
        illness=(
            '<p class="ill">Skin temperature, resting HR and breathing rate are all above'
            " usual: possibly getting ill. Take it easy.</p>"
            if flag
            else ""
        ),
        cards="".join(card(s, today) for s in statuses),
        place=f" · {place}" if place else "",
        weather=table,
        steps=period_charts(root, today, "Steps"),
        screen=period_charts(root, today, "Screen time", " h"),
        built_at=html.escape(built_at),
    )
