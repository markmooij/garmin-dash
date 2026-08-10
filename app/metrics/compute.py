"""Metrics orchestrator: compute and materialize daily scores.

compute_range() walks dates chronologically (ATL/CTL are stateful), loads
all source data once, computes raw load → strain → recovery → fitness, and
upserts into computed_scores. Idempotent: re-running any range is safe and
never duplicates rows.

Baselines are always exclusive of the target day — a day's score never
depends on data from that same day's future or itself.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..db import get_session
from ..db.models import Activity, ActivityHrSeries, ComputedScore, DailyWellness, SleepSession
from .fitness import FitnessState
from .load import banister_trimp, daily_raw_load, observed_hr_max
from .recovery import baseline_window, compute_recovery
from .strain import calibrate_strain, window_for


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _load_activities(session: Session, user_id: int) -> dict[int, dict]:
    """All activities with their FIT HR samples, keyed by activities.id."""
    acts = session.execute(
        select(Activity).where(Activity.user_id == user_id)
    ).scalars().all()

    out: dict[int, dict] = {}
    for a in acts:
        samples = session.execute(
            select(ActivityHrSeries.elapsed_s, ActivityHrSeries.hr).where(
                ActivityHrSeries.activity_pk == a.id,
                ActivityHrSeries.hr.is_not(None),
            )
        ).all()
        local_date = a.start_time_local[:10] if a.start_time_local else None
        zone_seconds = {
            z: getattr(a, f"hr_time_in_zone_{z}") or 0.0 for z in range(1, 6)
        }
        out[a.id] = {
            "activity_id": a.activity_id,
            "activity_type": a.activity_type,
            "duration": a.duration,
            "local_date": local_date,
            "zone_seconds": zone_seconds,
            "hr_samples": [(float(e), float(h)) for e, h in samples],
            "max_hr": a.max_hr,
        }
    return out


def _daily_map(rows, key_attr: str, value_attr: str) -> dict[date, float]:
    out: dict[date, float] = {}
    for r in rows:
        k = getattr(r, key_attr)
        v = getattr(r, value_attr)
        if k is not None and v is not None:
            out[k] = float(v)
    return out


def _build_day_loads(
    activities: dict[int, dict], hr_rest_by_day: dict[date, float], hr_max: float
) -> dict[date, dict]:
    """Raw load per local calendar date (TRIMP + strength duration)."""
    per_day: dict[date, dict] = {}
    for act in activities.values():
        if not act["local_date"]:
            continue
        day = date.fromisoformat(act["local_date"])
        rest = hr_rest_by_day.get(day)
        trimp = banister_trimp(act["hr_samples"], rest or 0.0, hr_max) if act["hr_samples"] else 0.0
        bucket = per_day.setdefault(
            day, {"activities": [], "trimp_sum": 0.0, "hr_rest": rest}
        )
        bucket["activities"].append(
            {
                "activity_id": act["activity_id"],
                "activity_type": act["activity_type"],
                "duration": act["duration"],
                "zone_seconds": act["zone_seconds"],
                "trimp": trimp,
            }
        )
        bucket["trimp_sum"] += trimp
    return per_day


def compute_range(
    start: date, end: date, user_id: int = 1, session: Session | None = None
) -> list[dict]:
    """Compute scores for [start, end] chronologically; materialize; return rows."""
    own = session is None
    session = session or get_session()

    try:
        activities = _load_activities(session, user_id)
        wellness = session.execute(
            select(DailyWellness).where(DailyWellness.user_id == user_id)
        ).scalars().all()
        sleep_rows = session.execute(
            select(SleepSession).where(SleepSession.user_id == user_id)
        ).scalars().all()

        rhr_by_day = _daily_map(wellness, "calendar_date", "resting_heart_rate")
        stress_by_day = _daily_map(wellness, "calendar_date", "avg_stress")
        sleep_by_day = _daily_map(sleep_rows, "calendar_date", "sleep_score")

        hr_max = observed_hr_max([a.get("max_hr") for a in activities.values()])
        day_loads = _build_day_loads(activities, rhr_by_day, hr_max)

        # Full historical raw-load series for calibration windows.
        all_raw: dict[date, float] = {}
        for d, bucket in day_loads.items():
            res = daily_raw_load(bucket["activities"], bucket["hr_rest"])
            all_raw[d] = res["raw_load"]

        # Pre-slice per-day loads once (used for strain + reporting).
        fitness = FitnessState()
        results: list[dict] = []

        day = start
        while day <= end:
            load_res = None
            if day in day_loads:
                load_res = daily_raw_load(
                    day_loads[day]["activities"], day_loads[day]["hr_rest"]
                )
                # Keep the TRIMP sum keyed from the bucket (identical to res).
                load_res["raw_load"] = all_raw[day]

            strain = calibrate_strain(
                all_raw.get(day, 0.0), window_for(day, 90, all_raw)
            )

            recovery = compute_recovery(
                rmssd=None,  # Venu 2: no HRV; engine stays capable for other devices
                hrv_baseline=[],
                rhr=rhr_by_day.get(day),
                rhr_baseline=baseline_window(day, 60, rhr_by_day),
                sleep_score=sleep_by_day.get(day),
                avg_stress=stress_by_day.get(day),
            )

            fitness_state = fitness.update(strain)

            row = {
                "user_id": user_id,
                "score_date": day,
                "recovery_score": recovery["score"] if recovery else None,
                "recovery_band": recovery["band"] if recovery else None,
                "strain": strain,
                "raw_load_trimp": (load_res or {}).get("raw_load_trimp"),
                "raw_load_edwards": (load_res or {}).get("raw_load_edwards"),
                "atl": fitness_state["atl"] if fitness_state else None,
                "ctl": fitness_state["ctl"] if fitness_state else None,
                "tsb": fitness_state["tsb"] if fitness_state else None,
                "payload": {
                    "raw_load": all_raw.get(day, 0.0),
                    "raw_load_strength": (load_res or {}).get("raw_load_strength"),
                    "hr_max_used": hr_max,
                    "recovery": recovery or {},
                    "rhr": rhr_by_day.get(day),
                    "sleep_score": sleep_by_day.get(day),
                    "avg_stress": stress_by_day.get(day),
                    "breakdown": (load_res or {}).get("breakdown", []),
                },
            }
            _upsert_score(session, row)
            results.append(row)
            day += timedelta(days=1)

        session.commit()
        return results
    finally:
        if own:
            session.close()


def _upsert_score(session: Session, row: dict) -> None:
    stmt = sqlite_insert(ComputedScore).values(**row)
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "score_date"],
        set_={
            "recovery_score": stmt.excluded.recovery_score,
            "recovery_band": stmt.excluded.recovery_band,
            "strain": stmt.excluded.strain,
            "raw_load_trimp": stmt.excluded.raw_load_trimp,
            "raw_load_edwards": stmt.excluded.raw_load_edwards,
            "atl": stmt.excluded.atl,
            "ctl": stmt.excluded.ctl,
            "tsb": stmt.excluded.tsb,
            "payload": stmt.excluded.payload,
        },
    )
    session.execute(stmt)


def compute_recent(days: int = 92, user_id: int = 1, session: Session | None = None) -> list[dict]:
    """Recompute the last ``days`` days (covers the 90-day strain window).

    ATL/CTL need history: recompute from max(start of data, today − days).
    """
    today = date.today()
    own = session is None
    session = session or get_session()
    try:
        earliest = session.execute(
            select(DailyWellness.calendar_date)
            .where(DailyWellness.user_id == user_id)
            .order_by(DailyWellness.calendar_date)
            .limit(1)
        ).scalar_one_or_none()
        if earliest:
            start = max(earliest, today - timedelta(days=days))
        else:
            start = today - timedelta(days=days)
        return compute_range(start, today, user_id=user_id, session=session)
    finally:
        if own:
            session.close()
