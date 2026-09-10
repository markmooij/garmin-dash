"""Small SVG visualisations for the Garmin-native dashboard indicators.

Each indicator is rendered as a compact, colour-coded graphic so the Today
view reads as an at-a-glance overview rather than a row of static numbers.
The colour thresholds follow the published conventions for each metric
(Garmin stress/Body Battery zones, clinical SpO2/respiration ranges, WHO
activity guidance, and the Cooper Institute VO2max bands).

All functions are pure: they take the metric value(s) and return an SVG
string (or ``""`` when there is nothing to draw). No DOM or JS is required,
so they are trivially testable and work inside Jinja templates.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from markupsafe import Markup


if TYPE_CHECKING:
    from collections.abc import Sequence


# ── colour helpers ──────────────────────────────────────────────────────

def _band(value: float | None, bands: Sequence[tuple[float, str]]) -> str:
    """Return the colour for `value` given ordered (upper_bound, colour) bands.

    The first band whose upper bound is >= value wins; values above the last
    bound take the last colour. ``None`` maps to the neutral zinc grey.
    """
    if value is None:
        return "#71717a"  # zinc-500
    for upper, colour in bands:
        if value <= upper:
            return colour
    return bands[-1][1]


def rhr_color(rhr: float | None) -> str:
    """Resting heart rate: lower is generally fitter (AHA 60-100 normal)."""
    return _band(rhr, [(55, "#34d399"), (65, "#fbbf24"), (float("inf"), "#f87171")])


def stress_color(stress: float | None) -> str:
    """Garmin stress scale: 0-25 rest, 26-50 low, 51-75 medium, 76-100 high."""
    return _band(stress, [(25, "#34d399"), (50, "#fbbf24"), (75, "#fb923c"), (float("inf"), "#f87171")])


def bb_color(bb: float | None) -> str:
    """Body Battery: higher is more charged."""
    return _band(bb, [(40, "#f87171"), (70, "#fbbf24"), (float("inf"), "#34d399")])


def vo2_color(vo2: float | None) -> str:
    """VO2max fitness bands (Cooper Institute, approximate for a fit adult)."""
    return _band(vo2, [(38, "#f87171"), (42, "#fb923c"), (46, "#fbbf24"), (50, "#a3e635"), (float("inf"), "#34d399")])


def spo2_color(spo2: float | None) -> str:
    """SpO2: 95-100 normal, 90-94 borderline, <90 low."""
    return _band(spo2, [(90, "#f87171"), (95, "#fbbf24"), (float("inf"), "#34d399")])


def resp_color(resp: float | None) -> str:
    """Respiration: 12-20 normal, 10-11 / 21-25 borderline, else concerning."""
    if resp is None:
        return "#71717a"
    if 12 <= resp <= 20:
        return "#34d399"
    if 10 <= resp < 12 or 20 < resp <= 25:
        return "#fbbf24"
    return "#f87171"


def steps_color(pct: float | None) -> str:
    """Steps goal completion: >=100% green, 70-99% yellow, <70% red."""
    return _band(pct, [(70, "#f87171"), (100, "#fbbf24"), (float("inf"), "#34d399")])


def intensity_color(pct: float | None) -> str:
    """Intensity-minutes goal completion (same traffic-light as steps)."""
    return _band(pct, [(70, "#f87171"), (100, "#fbbf24"), (float("inf"), "#34d399")])


# ── sparkline ───────────────────────────────────────────────────────────

def sparkline(values: Sequence[float | None], color: str, *, width: int = 120, height: int = 32) -> str:
    """A compact line chart for a daily series (None gaps are skipped).

    The line is drawn between consecutive non-None points; a gap in the data
    simply leaves a break in the polyline. A small dot marks the latest value.
    """
    pts = [(i, v) for i, v in enumerate(values) if v is not None]
    if len(pts) < 2:
        return ""
    ys = [p[1] for p in pts]
    min_y, max_y = min(ys), max(ys)
    span = (max_y - min_y) or 1.0
    n = len(values)
    pad = 3
    coords = []
    for i, v in pts:
        x = pad + (i / (n - 1)) * (width - 2 * pad)
        y = height - pad - ((v - min_y) / span) * (height - 2 * pad)
        coords.append((x, y))
    points = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    last_x, last_y = coords[-1]
    return Markup(
        f'<svg viewBox="0 0 {width} {height}" class="w-full" style="height:{height}px" '
        f'aria-hidden="true">'
        f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2.5" fill="{color}"/>'
        f'</svg>'
    )


# ── horizontal gauge (zones + needle) ───────────────────────────────────

def gauge(
    value: float | None,
    zones: Sequence[tuple[float, float, str]],
    *,
    width: int = 120,
    height: int = 10,
) -> str:
    """A horizontal gauge with coloured zones and a needle at `value`.

    `zones` is a list of (start, end, colour) in the metric's units. The track
    is drawn as the zones (low opacity), and a needle marks the current value.
    """
    if value is None:
        return ""
    total = zones[-1][1]
    segs = []
    for start, end, colour in zones:
        x = (start / total) * width
        w = ((end - start) / total) * width
        segs.append(
            f'<rect x="{x:.1f}" y="0" width="{w:.1f}" height="{height}" '
            f'fill="{colour}" opacity="0.28" rx="1"/>'
        )
    x = min(max(value, 0), total) / total * width
    needle = f'<rect x="{x - 1:.1f}" y="-3" width="2" height="{height + 6}" fill="#e4e4e7" rx="1"/>'
    return Markup(
        f'<svg viewBox="0 0 {width} {height + 6}" class="w-full" style="height:{height + 6}px" '
        f'aria-hidden="true">'
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="2" fill="#27272a"/>'
        f'{"".join(segs)}{needle}'
        f'</svg>'
    )


# ── progress ring (goal completion) ─────────────────────────────────────

def ring(pct: float | None, color: str, *, size: int = 44, stroke: int = 5) -> str:
    """A circular progress ring for goal completion (0-100%)."""
    if pct is None:
        return ""
    pct = min(max(pct, 0), 100)
    r = (size - stroke) / 2
    c = size / 2
    circ = 2 * math.pi * r
    filled = circ * pct / 100
    return Markup(
        f'<svg viewBox="0 0 {size} {size}" class="w-full" style="max-width:{size}px" '
        f'aria-hidden="true">'
        f'<circle cx="{c}" cy="{c}" r="{r}" fill="none" stroke="#27272a" stroke-width="{stroke}"/>'
        f'<circle cx="{c}" cy="{c}" r="{r}" fill="none" stroke="{color}" stroke-width="{stroke}" '
        f'stroke-linecap="round" stroke-dasharray="{filled:.1f} {circ:.1f}" '
        f'transform="rotate(-90 {c} {c})"/>'
        f'</svg>'
    )


# ── battery (Body Battery) ──────────────────────────────────────────────

def battery(level: float | None, color: str, *, width: int = 22, height: int = 40) -> str:
    """A vertical battery glyph filled to `level` (0-100)."""
    if level is None:
        return ""
    level = min(max(level, 0), 100)
    cap = 3
    body_h = height - cap
    fill_h = body_h * level / 100
    return Markup(
        f'<svg viewBox="0 0 {width} {height}" class="w-full" style="max-width:{width}px" '
        f'aria-hidden="true">'
        f'<rect x="1" y="0" width="{width - 2}" height="{body_h}" rx="3" '
        f'fill="none" stroke="#3f3f46" stroke-width="1.5"/>'
        f'<rect x="3" y="{body_h - fill_h:.1f}" width="{width - 6}" height="{fill_h:.1f}" '
        f'rx="1.5" fill="{color}"/>'
        f'<rect x="{width / 2 - 2:.1f}" y="{body_h}" width="4" height="{cap}" rx="1" fill="#3f3f46"/>'
        f'</svg>'
    )


# ── convenience builders (value + label + colour together) ──────────────

def stress_gauge(stress: float | None) -> str:
    return gauge(
        stress,
        [(0, 25, "#34d399"), (25, 50, "#fbbf24"), (50, 75, "#fb923c"), (75, 100, "#f87171")],
    )


def spo2_gauge(spo2: float | None) -> str:
    # Clinical range is ~88-100; draw zones across that window.
    return gauge(
        spo2,
        [(88, 90, "#f87171"), (90, 95, "#fbbf24"), (95, 100, "#34d399")],
    )


def resp_gauge(resp: float | None) -> str:
    return gauge(
        resp,
        [(8, 10, "#f87171"), (10, 12, "#fbbf24"), (12, 20, "#34d399"), (20, 25, "#fbbf24"), (25, 30, "#f87171")],
    )


def vo2_gauge(vo2: float | None) -> str:
    return gauge(
        vo2,
        [(30, 38, "#f87171"), (38, 42, "#fb923c"), (42, 46, "#fbbf24"), (46, 50, "#a3e635"), (50, 60, "#34d399")],
    )
