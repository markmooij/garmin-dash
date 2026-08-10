"""Raw training load: Banister TRIMP, Edwards zone-minutes, strength duration.

Canonical per-activity raw load is stored (never the calibrated strain), so
scale changes never touch history. TRIMP is computed from FIT intra-activity
HR samples; Edwards from Garmin's own zone-minutes (present in every
activity response); strength sports get a duration-based component because
HR undercounts them (roadmap decision: type + duration, not rep counting).
"""

from __future__ import annotations

import json
import math
import statistics

from ..settings import get_settings


# Zones for Edwards TRIMP are Garmin's 1..5 (5-zone model).
EDWARDS_ZONE_WEIGHTS = {1: 1.0, 2: 2.0, 3: 3.0, 4: 4.0, 5: 5.0}


def sport_load_factor(activity_type: str) -> float:
    """Per-minute load factor for strength-like sports (0 if not configured)."""
    s = get_settings()
    try:
        factors = json.loads(s.SPORT_LOAD_FACTORS)
    except json.JSONDecodeError:
        factors = {}
    return float(factors.get(activity_type, 0.0))


def edwards_load(zone_seconds: dict[int, float]) -> float:
    """Edwards TRIMP (zone-minutes) from Garmin zone seconds.

    Edwards = Σ minutes_in_zone_i × i. Garmin reports hrTimeInZone_1..5 in
    seconds; missing zones count as 0.
    """
    total = 0.0
    for zone, weight in EDWARDS_ZONE_WEIGHTS.items():
        secs = float(zone_seconds.get(zone, 0.0) or 0.0)
        total += (secs / 60.0) * weight
    return round(total, 3)


def banister_trimp(
    hr_samples: list[tuple[float, float]],
    hr_rest: float,
    hr_max: float,
) -> float:
    """Banister TRIMP from (elapsed_s, hr) samples.

    TRIMP per sample = Δt × HRr × 0.64 × e^(1.92 × HRr), where
    HRr = (HR − rest) / (max − rest). Sample interval is estimated as the
    median gap between consecutive samples (FIT cadence varies by sport);
    first/last samples use the median interval.

    Returns TRIMP in "load units" (≈ minutes × intensity factor). 0 when
    there are fewer than 2 usable samples or HRr cannot be computed.
    """
    if len(hr_samples) < 2:
        return 0.0
    if hr_max <= hr_rest:
        return 0.0

    samples = sorted(hr_samples)
    gaps = [
        b - a for (a, _), (b, _) in zip(samples, samples[1:], strict=False) if b - a > 0
    ]
    if not gaps:
        return 0.0
    dt = statistics.median(gaps)

    total = 0.0
    for _, hr in samples:
        if hr is None or hr <= 0:
            continue
        hr_r = (hr - hr_rest) / (hr_max - hr_rest)
        if hr_r <= 0:
            continue
        if hr_r > 1.0:
            hr_r = 1.0  # cap above-max spikes (e.g. cadence glitches)
        total += dt * hr_r * 0.64 * math.exp(1.92 * hr_r)
    return round(total, 3)


def strength_duration_load(activity_type: str, duration_s: float) -> float:
    """Duration-based load component for strength-like sports."""
    factor = sport_load_factor(activity_type)
    if factor <= 0 or not duration_s:
        return 0.0
    return round(factor * (duration_s / 60.0), 3)


def daily_raw_load(
    activities: list[dict],
    hr_rest: float | None,
) -> dict:
    """Aggregate one day's raw load.

    ``activities``: list of per-activity dicts with keys
    ``activity_type``, ``duration``, ``zone_seconds`` {1..5: seconds},
    ``trimp`` (precomputed Banister TRIMP from FIT samples, 0 if none).

    Returns canonical raw load (TRIMP + strength duration), Edwards
    zone-minutes, and per-activity breakdown.
    """
    settings = get_settings()
    rest = hr_rest or float(settings.HR_REST_FALLBACK)

    trimp_total = 0.0
    edwards_total = 0.0
    strength_total = 0.0
    breakdown = []
    for act in activities:
        trimp = float(act.get("trimp") or 0.0)
        ed = edwards_load(act.get("zone_seconds") or {})
        strength = strength_duration_load(
            act.get("activity_type", ""), float(act.get("duration") or 0.0)
        )
        trimp_total += trimp
        edwards_total += ed
        strength_total += strength
        breakdown.append(
            {
                "activity_id": act.get("activity_id"),
                "type": act.get("activity_type"),
                "trimp": trimp,
                "edwards": ed,
                "strength_duration": strength,
                "hr_rest_used": rest,
            }
        )

    raw = round(trimp_total + strength_total, 3)
    return {
        "raw_load": raw,
        "raw_load_trimp": round(trimp_total, 3),
        "raw_load_edwards": round(edwards_total, 3),
        "raw_load_strength": round(strength_total, 3),
        "breakdown": breakdown,
    }


def observed_hr_max(activity_max_hrs: list[float | None]) -> float:
    """HRmax: observed max across activities + buffer, else fallback."""
    s = get_settings()
    observed = [m for m in activity_max_hrs if m]
    if observed:
        return float(max(observed)) + s.HR_MAX_OBSERVED_BUFFER
    return float(s.HR_MAX_FALLBACK)
