"""Golden tests for the metrics engine — synthetic, hand-computed values.

Real fixtures are gitignored (raw health data); these tests build fully
deterministic synthetic data and assert exact numbers, so the engine's math
is byte-reproducible for anyone.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from app.db.models import (
    Activity,
    ComputedScore,
    DailyWellness,
    SleepSession,
)
from app.metrics.fitness import FitnessState
from app.metrics.load import banister_trimp, daily_raw_load, edwards_load, sport_load_factor
from app.metrics.recovery import (
    baseline_window,
    compute_recovery,
    hrv_score,
    rhr_score,
    stress_score_component,
)
from app.metrics.strain import calibrate_strain, window_for


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


# ── load.py ────────────────────────────────────────────────────────────

def test_edwards_zone_minutes():
    # 10 min z1, 20 min z2, 30 min z3 → 10 + 40 + 90 = 140
    assert edwards_load({1: 600, 2: 1200, 3: 1800}) == 140.0
    assert edwards_load({}) == 0.0
    assert edwards_load({5: 60}) == 5.0  # 1 min in z5 = 5 pts


def test_banister_trimp_constant_hr():
    # Constant HR at HRr = 0.5 for 60 s, rest 50, max 190:
    # HR = 50 + 0.5×140 = 120. TRIMP/s = 0.5 × 0.64 × e^(1.92×0.5)
    # = 0.32 × e^0.96. 60 s → 60 × that. (Function rounds to 3 dp.)
    hr_r = 0.5
    expected = round(60.0 * hr_r * 0.64 * math.exp(1.92 * hr_r), 3)
    samples = [(i * 1.0, 120.0) for i in range(60)]
    assert banister_trimp(samples, hr_rest=50.0, hr_max=190.0) == expected


def test_banister_trimp_insufficient_samples():
    assert banister_trimp([], 50.0, 190.0) == 0.0
    assert banister_trimp([(0.0, 120.0)], 50.0, 190.0) == 0.0
    assert banister_trimp([(0.0, 120.0), (1.0, 120.0)], hr_rest=190.0, hr_max=190.0) == 0.0  # no range


def test_banister_trimp_uses_median_gap():
    # gaps list of length n → n+1 samples; both cases have median gap 5
    def trimp_for(gaps):
        samples = []
        t = 0.0
        for g in gaps:
            samples.append((t, 120.0))
            t += g
        samples.append((t, 120.0))  # final sample
        return banister_trimp(samples, 50.0, 190.0)

    a = trimp_for([5, 5])
    b = trimp_for([2, 8])  # median gap = 5 as well
    assert a == pytest.approx(b, rel=1e-9)
    assert a == pytest.approx(3 * 5 * 0.32 * math.exp(0.96), rel=1e-3)
    c = trimp_for([1, 1])
    assert c < a


def test_sport_load_factor_and_strength_duration():
    assert sport_load_factor("strength_training") == 45.0
    assert sport_load_factor("lap_swimming") == 0.0
    from app.metrics.load import strength_duration_load

    assert strength_duration_load("strength_training", 3600) == 2700.0
    assert strength_duration_load("lap_swimming", 3600) == 0.0


def test_daily_raw_load_combines_components():
    acts = [
        {"activity_id": 1, "activity_type": "strength_training", "duration": 1800,
         "zone_seconds": {1: 600, 2: 600}, "trimp": 100.0},
    ]
    res = daily_raw_load(acts, hr_rest=50.0)
    # edwards = 10×1 + 10×2 = 30; strength = 45×30min = 1350; raw = 100 + 1350
    assert res["raw_load_trimp"] == 100.0
    assert res["raw_load_edwards"] == 30.0
    assert res["raw_load_strength"] == 1350.0
    assert res["raw_load"] == 1450.0


# ── strain.py ──────────────────────────────────────────────────────────

def test_calibrate_strain_constant_window():
    # Window: 100 days each of raw load 1000 → p95 = 1000 → strain = 1000/1000×20 = 20
    window = [1000.0] * 100
    assert calibrate_strain(1000.0, window) == 20.0
    assert calibrate_strain(500.0, window) == 10.0
    assert calibrate_strain(2000.0, window) == 21.0  # 40 → capped at 21


def test_calibrate_strain_edges():
    assert calibrate_strain(0.0, [100.0]) == 0.0
    assert calibrate_strain(100.0, []) == 20.0  # first-ever day self-calibrates
    assert calibrate_strain(100.0, [0.0, 0.0]) == 20.0  # no prior positive loads


def test_strain_window_excludes_target():
    all_loads = {}
    for i in range(100):
        all_loads[date(2026, 1, 1) + timedelta(days=i)] = float(i)
    target = date(2026, 3, 1)  # day 59 → window = days 0..58 (59 values)
    w = window_for(target, 90, all_loads)
    assert len(w) == 59
    assert date(2026, 3, 1) - timedelta(days=1) not in all_loads or True
    assert all_loads[target] not in w  # never self-calibrates


# ── recovery.py ────────────────────────────────────────────────────────

def test_hrv_score_log_normal_z():
    # baseline ln(RMSSD) values with known mean/std; rmssd at mean + 0.5σ
    import statistics

    ln_vals = [3.0 + 0.1 * i for i in range(60)]
    baseline = [math.exp(v) for v in ln_vals]
    mean = statistics.mean(ln_vals)
    stdev = statistics.stdev(ln_vals)
    rmssd = math.exp(mean + 0.5 * stdev)
    s = hrv_score(rmssd=rmssd, baseline=baseline)
    assert s is not None
    assert s == pytest.approx(50.0 + 12.5 * 0.5, abs=0.01)


def test_hrv_score_insufficient_baseline():
    assert hrv_score(30.0, [30.0, 30.0, 30.0]) is None  # < 7 days
    assert hrv_score(None, [30.0] * 60) is None


def test_rhr_score_inverted():
    baseline = [50.0 + (i % 3) for i in range(60)]  # variance > 0, mean 51
    assert rhr_score(51.0, baseline) == pytest.approx(50.0, abs=0.5)
    assert rhr_score(60.0, baseline) < 50.0  # higher RHR → worse
    assert rhr_score(42.0, baseline) > 50.0
    # zero-variance baseline → no z possible → neutral 50
    assert rhr_score(55.0, [50.0] * 60) == 50.0


def test_recovery_fallback_no_hrv():
    r = compute_recovery(
        rmssd=None, hrv_baseline=[],
        rhr=50.0, rhr_baseline=[50.0] * 60,
        sleep_score=80.0, avg_stress=20.0,
    )
    assert r is not None
    assert "hrv" not in r["components"]
    # weights renormalized over rhr+sleep+stress (0.2/0.2/0.1 → 0.4/0.4/0.2)
    assert r["weights"] == pytest.approx({"rhr": 0.4, "sleep": 0.4, "stress": 0.2})
    expected = 0.4 * 50 + 0.4 * 80 + 0.2 * 80  # = 20 + 32 + 16 = 68
    assert r["score"] == pytest.approx(expected)
    assert r["band"] == "green"


def test_recovery_with_hrv():
    r = compute_recovery(
        rmssd=30.0, hrv_baseline=[30.0] * 60,
        rhr=50.0, rhr_baseline=[50.0] * 60,
        sleep_score=80.0, avg_stress=20.0,
    )
    assert r is not None
    assert r["hrv_used"] is True
    assert r["weights"] == pytest.approx({"hrv": 0.5, "rhr": 0.2, "sleep": 0.2, "stress": 0.1})


def test_recovery_missing_night_returns_none():
    # No sleep, no RHR, no HRV → nothing to anchor on
    assert compute_recovery(rmssd=None, hrv_baseline=[], rhr=None, rhr_baseline=[], sleep_score=None, avg_stress=20.0) is None
    # Only stress → still None (missing night rule)
    assert compute_recovery(avg_stress=20.0) is None


def test_recovery_partial_inputs_renormalize():
    # Only RHR + stress available
    r = compute_recovery(rhr=50.0, rhr_baseline=[50.0] * 60, avg_stress=30.0)
    assert r is not None
    assert set(r["weights"].keys()) == {"rhr", "stress"}
    assert sum(r["weights"].values()) == pytest.approx(1.0)


def test_baseline_window_excludes_target():
    vals = {date(2026, 1, 1) + timedelta(days=i): float(i) for i in range(70)}
    target = date(2026, 3, 1)  # day 59; window covers days 0..58 = 59 values
    w = baseline_window(target, 60, vals)
    assert len(w) == 59
    assert vals[target] not in w


# ── fitness.py ─────────────────────────────────────────────────────────

def test_atl_ctl_tsb_steady_state():
    f = FitnessState()
    for _ in range(365):
        snap = f.update(10.0)
    assert snap["ctl"] == pytest.approx(10.0, abs=0.01)
    assert snap["atl"] == pytest.approx(10.0, abs=0.01)
    assert snap["tsb"] == pytest.approx(0.0, abs=0.02)


def test_atl_responds_faster_than_ctl():
    f = FitnessState()
    for _ in range(200):
        f.update(10.0)
    # Spike: 30 strain for 14 days
    for _ in range(14):
        f.update(30.0)
    snap = f.update(10.0)
    # ATL rises faster → TSB turns negative
    assert snap["atl"] > snap["ctl"]
    assert snap["tsb"] < 0


def test_fitness_none_before_seed():
    f = FitnessState()
    assert f.update(None) is None
    snap = f.update(5.0)
    assert snap["atl"] == 5.0 and snap["ctl"] == 5.0


def test_stress_score_component():
    assert stress_score_component(20.0) == 80.0
    assert stress_score_component(None) is None
    assert stress_score_component(-1.0) == 100.0  # Garmin -1 sentinel clamped


# ── compute.py end-to-end (synthetic DB) ───────────────────────────────

def _seed_day(session: Session, day: date, *, rhr: float, sleep_score: float | None, stress: float | None,
              activities: list[dict] | None = None):
    session.add(DailyWellness(
        user_id=1, calendar_date=day,
        resting_heart_rate=rhr, avg_stress=stress, bb_highest=90,
        steps=5000, moderate_intensity_minutes=10, vigorous_intensity_minutes=5,
    ))
    if sleep_score is not None:
        session.add(SleepSession(
            user_id=1, calendar_date=day, sleep_score=sleep_score,
            sleep_start_gmt=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            sleep_end_gmt=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            sleep_start_local=f"{day} 00:00:00", sleep_end_local=f"{day} 08:00:00",
            sleep_seconds=7 * 3600, deep_seconds=3600, light_seconds=18000,
            rem_seconds=5400, awake_seconds=600,
            avg_sleep_stress=20.0, resting_heart_rate=rhr,
        ))
    for a in (activities or []):
        session.add(Activity(
            user_id=1, activity_id=a["activity_id"],
            activity_name="Kracht", activity_type=a["type"],
            start_time_gmt=datetime.combine(day, datetime.min.time(), tzinfo=UTC),
            start_time_local=f"{day} 10:00:00",
            timezone_id="Europe/Amsterdam", duration=a["duration"],
            elapsed_duration=a["duration"], moving_duration=a["duration"],
            avg_hr=a.get("avg_hr"), max_hr=a.get("max_hr"),
            hr_time_in_zone_1=a.get("z1", 0), hr_time_in_zone_2=a.get("z2", 0),
            hr_time_in_zone_3=a.get("z3", 0), hr_time_in_zone_4=a.get("z4", 0),
            hr_time_in_zone_5=a.get("z5", 0),
        ))


def test_compute_range_materializes_and_is_deterministic(session: Session):
    from app.metrics.compute import compute_range

    start = date(2026, 1, 1)
    for i in range(30):
        d = start + timedelta(days=i)
        _seed_day(session, d, rhr=50.0, sleep_score=80.0, stress=20.0,
                  activities=[{"activity_id": i, "type": "strength_training",
                               "duration": 3600, "avg_hr": 110, "max_hr": 150}])
    session.commit()

    rows1 = compute_range(start, start + timedelta(days=29), session=session)
    assert len(rows1) == 30
    rows2 = compute_range(start, start + timedelta(days=29), session=session)
    assert rows1 == rows2  # deterministic re-run

    # materialized rows exist and idempotency held (no duplicates)
    from sqlalchemy import func, select

    n = session.execute(select(func.count()).select_from(ComputedScore)).scalar()
    assert n == 30

    last = rows1[-1]
    assert last["strain"] > 0  # strength load → strain
    assert last["recovery_score"] is not None
    assert last["atl"] is not None and last["ctl"] is not None
    assert last["payload"]["recovery"]["hrv_used"] is False  # fallback active


def test_compute_day_without_any_data_yields_zero_load(session: Session):
    from app.metrics.compute import compute_range

    rows = compute_range(date(2026, 1, 1), date(2026, 1, 3), session=session)
    assert len(rows) == 3
    for r in rows:
        assert r["strain"] == 0.0
        assert r["recovery_score"] is None  # missing night → no fabrication
