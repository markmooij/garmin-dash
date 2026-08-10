"""Strain calibration: raw daily load → Whoop-style 0–21.

The personal calibration curve maps the rolling 90-day 95th percentile of
daily raw load to ≈ 20. The curve is applied **at read time**; stored
history only ever contains raw loads, so scale changes never rewrite it.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from ..settings import get_settings


def calibrate_strain(raw_load: float, window_loads: list[float]) -> float:
    """Map a daily raw load to 0–21 given the rolling window of raw loads.

    window_loads: raw loads for the calibration window ending the day BEFORE
    the target date (exclusive of the day itself, so a day can never
    calibrate against itself). An empty window (the very first activity day
    in history) self-calibrates: the day's load becomes its own 100th
    percentile → 20.
    """
    s = get_settings()
    if raw_load <= 0:
        return 0.0

    usable = [v for v in window_loads if v > 0]
    if not usable:
        # First-ever activity day: no history to compare against.
        # Its own load is the 100th percentile → strain 20.
        return round(s.STRAIN_CAP - 1.0, 3)

    p95 = _percentile(usable, s.STRAIN_PERCENTILE)
    if p95 <= 0:
        return 0.0

    # ≈20 at the 95th percentile of the window, capped at 21.
    strain = (raw_load / p95) * (s.STRAIN_CAP - 1.0)
    return round(max(0.0, min(s.STRAIN_CAP, strain)), 3)


def window_for(target: date, window_days: int, all_loads: dict[date, float]) -> list[float]:
    """Raw loads in [target − window_days, target − 1] (excludes target)."""
    loads = []
    for i in range(window_days, 0, -1):
        d = target - timedelta(days=i)
        if d in all_loads:
            loads.append(all_loads[d])
    return loads


def _percentile(values: list[float], q: float) -> float:
    """Linear-interpolation percentile (like numpy's default)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    frac = pos - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac


def strain_band(strain: float) -> str:
    """Whoop-style strain bands (informational)."""
    if strain >= 14:
        return "high"
    if strain >= 9:
        return "moderate"
    return "low"
