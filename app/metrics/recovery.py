"""Recovery composite (0–100), Whoop-style.

Primary factor is overnight HRV as **ln(RMSSD) z-score vs a 60-day rolling
baseline** — RMSSD is log-normal, so raw z-scores are never computed on
untransformed values. HRV-adaptive: when the device exposes no HRV (Venu 2
verified), the HRV factor is dropped and weights renormalize over RHR
deviation, sleep quality and stress.

Rules:
- Missing inputs are dropped, remaining weights renormalized to sum 1.
- Missing night (no sleep AND no RHR): recovery is None — never shown as
  "low", never zero-filled.
- Baselines are exclusive of the target day (no self-calibration).
"""

from __future__ import annotations

import json
import math
import statistics
from datetime import date, timedelta

from ..settings import get_settings


def _weights(available: list[str]) -> dict[str, float]:
    """Base weights minus missing factors, renormalized to sum 1."""
    s = get_settings()
    try:
        base = json.loads(s.RECOVERY_WEIGHTS_HRV)
    except json.JSONDecodeError:
        base = {"hrv": 0.5, "rhr": 0.2, "sleep": 0.2, "stress": 0.1}
    weights = {k: v for k, v in base.items() if k in available}
    total = sum(weights.values())
    if total <= 0:
        return {}
    return {k: v / total for k, v in weights.items()}


def _z_to_score(z: float) -> float:
    """z-score → 0–100 (50 = baseline, ±12.5 per SD, clamped)."""
    return max(0.0, min(100.0, 50.0 + 12.5 * z))


def hrv_score(rmssd: float | None, baseline: list[float]) -> float | None:
    """ln(RMSSD) z-score vs baseline → 0–100. None if no data/baseline."""
    if rmssd is None or rmssd <= 0:
        return None
    if len(baseline) < get_settings().RECOVERY_MIN_BASELINE_DAYS:
        return None
    ln_vals = [math.log(v) for v in baseline if v and v > 0]
    if len(ln_vals) < get_settings().RECOVERY_MIN_BASELINE_DAYS:
        return None
    mean = statistics.mean(ln_vals)
    stdev = statistics.stdev(ln_vals) if len(ln_vals) > 1 else 0.0
    if stdev <= 0:
        return 50.0
    z = (math.log(rmssd) - mean) / stdev
    return round(_z_to_score(z), 2)


def rhr_score(rhr: float | None, baseline: list[float]) -> float | None:
    """RHR deviation vs baseline → 0–100 (higher RHR = worse recovery)."""
    if rhr is None:
        return None
    if len(baseline) < get_settings().RECOVERY_MIN_BASELINE_DAYS:
        return None
    mean = statistics.mean(baseline)
    stdev = statistics.stdev(baseline) if len(baseline) > 1 else 0.0
    if stdev <= 0:
        return 50.0
    z = (rhr - mean) / stdev
    return round(_z_to_score(-z), 2)  # inverted


def sleep_score_component(sleep_score: float | None) -> float | None:
    """Garmin sleep score (0–100) passes through; None if no sleep data."""
    if sleep_score is None:
        return None
    return round(max(0.0, min(100.0, float(sleep_score))), 2)


def stress_score_component(avg_stress: float | None) -> float | None:
    """Daily avg stress (0–100) inverted; None if missing."""
    if avg_stress is None:
        return None
    return round(max(0.0, min(100.0, 100.0 - float(avg_stress))), 2)


def compute_recovery(
    *,
    rmssd: float | None = None,
    hrv_baseline: list[float] | None = None,
    rhr: float | None = None,
    rhr_baseline: list[float] | None = None,
    sleep_score: float | None = None,
    avg_stress: float | None = None,
) -> dict | None:
    """Composite recovery for one day.

    Returns dict with score, band, component scores, weights, or None when
    there is not enough data (missing night rule).
    """
    components: dict[str, float | None] = {}

    h = hrv_score(rmssd, hrv_baseline or [])
    if h is not None:
        components["hrv"] = h
    r = rhr_score(rhr, rhr_baseline or [])
    if r is not None:
        components["rhr"] = r
    sl = sleep_score_component(sleep_score)
    if sl is not None:
        components["sleep"] = sl
    st = stress_score_component(avg_stress)
    if st is not None:
        components["stress"] = st

    # Missing night rule: without at least one overnight anchor (HRV/RHR/
    # sleep), do not fabricate a score.
    if not components or not (components.get("hrv") or components.get("rhr") or components.get("sleep")):
        return None

    weights = _weights(list(components.keys()))
    if not weights:
        return None

    # Narrowed pairs for mypy: components[k] is guaranteed not None here.
    pairs: list[tuple[float, float]] = []
    for k, w in weights.items():
        v = components[k]
        if v is not None:
            pairs.append((v, w))
    if not pairs:
        return None
    total = round(max(0.0, min(100.0, sum(v * w for v, w in pairs))), 2)

    s = get_settings()
    if total >= s.RECOVERY_BAND_GREEN:
        band = "green"
    elif total >= s.RECOVERY_BAND_YELLOW:
        band = "yellow"
    else:
        band = "red"

    return {
        "score": total,
        "band": band,
        "components": components,
        "weights": weights,
        "hrv_used": "hrv" in components,
    }


def baseline_window(target: date, window_days: int, values: dict[date, float]) -> list[float]:
    """Values in [target − window_days, target − 1] (excludes target)."""
    out = []
    for i in range(window_days, 0, -1):
        d = target - timedelta(days=i)
        if d in values and values[d] is not None:
            out.append(values[d])
    return out
