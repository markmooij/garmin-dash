"""Read-side queries for the dashboard (single user, user_id=1)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from ..coach.interpretation import interpret_insights
from ..db.models import (
    Activity,
    ComputedScore,
    DailyWellness,
    DeviceMetrics,
    IntradaySeries,
    JournalFactor,
    MorningReport,
    SleepSession,
    SyncState,
)
from ..journal.entries import entries_in_range, get_entry
from ..journal.insights import compute_all_insights
from ..journal.schema import get_factor, get_factors
from ..settings import get_settings


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


USER_ID = 1


def _jsonable(v):
    if isinstance(v, (date,)):
        return v.isoformat()
    return v


def summary_for(session: Session, day: date) -> dict:
    """Everything the Today view needs for one date."""
    score = session.execute(
        select(ComputedScore).where(
            ComputedScore.user_id == USER_ID, ComputedScore.score_date == day
        )
    ).scalar_one_or_none()
    wellness = session.execute(
        select(DailyWellness).where(
            DailyWellness.user_id == USER_ID, DailyWellness.calendar_date == day
        )
    ).scalar_one_or_none()
    sleep = session.execute(
        select(SleepSession).where(
            SleepSession.user_id == USER_ID, SleepSession.calendar_date == day
        )
    ).scalar_one_or_none()

    activities = session.execute(
        select(Activity)
        .where(Activity.user_id == USER_ID)
        .order_by(Activity.start_time_gmt)
    ).scalars().all()
    day_acts = [a for a in activities if (a.start_time_local or "")[:10] == day.isoformat()]

    payload = score.payload if score else {}
    breakdown = payload.get("breakdown", [])
    by_id = {b.get("activity_id"): b for b in breakdown}
    act_list = []
    for a in day_acts:
        b = by_id.get(a.activity_id, {})
        act_list.append(
            {
                "name": a.activity_name,
                "type": a.activity_type,
                "start": a.start_time_local,
                "duration_s": a.duration,
                "avg_hr": a.avg_hr,
                "max_hr": a.max_hr,
                "trimp": b.get("trimp", 0),
                "edwards": b.get("edwards", 0),
                "strength": b.get("strength_duration", 0),
                "aerobic_te": a.aerobic_training_effect,
                "anaerobic_te": a.anaerobic_training_effect,
                "bb_delta": a.difference_body_battery,
            }
        )

    rec_detail = payload.get("recovery") or {}
    vo2 = session.execute(
        select(DeviceMetrics)
        .where(DeviceMetrics.user_id == USER_ID, DeviceMetrics.vo2max.is_not(None))
        .order_by(DeviceMetrics.metric_date.desc())
        .limit(1)
    ).scalar_one_or_none()

    return {
        "date": day.isoformat(),
        "recovery": {
            "score": score.recovery_score if score else None,
            "band": score.recovery_band if score else None,
            "components": rec_detail.get("components"),
            "weights": rec_detail.get("weights"),
            "hrv_used": rec_detail.get("hrv_used", False),
        },
        "strain": score.strain if score else None,
        "tsb": score.tsb if score else None,
        "ctl": score.ctl if score else None,
        "atl": score.atl if score else None,
        "raw_load": payload.get("raw_load"),
        "wellness": {
            "rhr": wellness.resting_heart_rate if wellness else None,
            "avg_stress": wellness.avg_stress if wellness else None,
            "bb_at_wake": wellness.bb_at_wake if wellness else None,
            "bb_most_recent": wellness.bb_most_recent if wellness else None,
            "bb_highest": wellness.bb_highest if wellness else None,
            "bb_lowest": wellness.bb_lowest if wellness else None,
            "steps": wellness.steps if wellness else None,
            "moderate_min": wellness.moderate_intensity_minutes if wellness else None,
            "vigorous_min": wellness.vigorous_intensity_minutes if wellness else None,
            "avg_spo2": wellness.avg_spo2 if wellness else None,
            "avg_respiration": wellness.avg_respiration if wellness else None,
        },
        "sleep": {
            "score": sleep.sleep_score if sleep else None,
            "deep_s": sleep.deep_seconds if sleep else None,
            "rem_s": sleep.rem_seconds if sleep else None,
            "light_s": sleep.light_seconds if sleep else None,
            "awake_s": sleep.awake_seconds if sleep else None,
            "total_s": sleep.sleep_seconds if sleep else None,
            "awake_count": sleep.awake_count if sleep else None,
            "avg_sleep_stress": sleep.avg_sleep_stress if sleep else None,
            "start_local": sleep.sleep_start_local if sleep else None,
            "end_local": sleep.sleep_end_local if sleep else None,
        },
        "vo2max": vo2.vo2max if vo2 else None,
        "vo2max_precise": vo2.vo2max_precise if vo2 else None,
        "activities": act_list,
    }


def trends_for(session: Session, days: int = 90, end: date | None = None) -> dict:
    """Daily series for the Trends view: scores + Garmin-native overlays."""
    end = end or date.today()
    start = end - timedelta(days=days - 1)

    scores = session.execute(
        select(ComputedScore)
        .where(
            ComputedScore.user_id == USER_ID,
            ComputedScore.score_date >= start,
            ComputedScore.score_date <= end,
        )
        .order_by(ComputedScore.score_date)
    ).scalars().all()
    wellness = session.execute(
        select(DailyWellness)
        .where(
            DailyWellness.user_id == USER_ID,
            DailyWellness.calendar_date >= start,
            DailyWellness.calendar_date <= end,
        )
    ).scalars().all()
    sleeps = session.execute(
        select(SleepSession)
        .where(
            SleepSession.user_id == USER_ID,
            SleepSession.calendar_date >= start,
            SleepSession.calendar_date <= end,
        )
    ).scalars().all()
    metrics = session.execute(
        select(DeviceMetrics)
        .where(
            DeviceMetrics.user_id == USER_ID,
            DeviceMetrics.metric_date >= start,
            DeviceMetrics.metric_date <= end,
        )
        .order_by(DeviceMetrics.metric_date)
    ).scalars().all()

    w = {r.calendar_date: r for r in wellness}
    sl = {r.calendar_date: r for r in sleeps}
    dm = {r.metric_date: r for r in metrics}

    dates, recovery, strain, atl, ctl, tsb = [], [], [], [], [], []
    rhr, stress, sleep_score, bb_wake, steps, vo2 = [], [], [], [], [], []
    for r in scores:
        d = r.score_date
        dates.append(d.isoformat())
        recovery.append(r.recovery_score)
        strain.append(r.strain)
        atl.append(r.atl)
        ctl.append(r.ctl)
        tsb.append(r.tsb)
        wd = w.get(d)
        rhr.append(wd.resting_heart_rate if wd else None)
        stress.append(wd.avg_stress if wd else None)
        bb_wake.append(wd.bb_at_wake if wd else None)
        steps.append(wd.steps if wd else None)
        sd = sl.get(d)
        sleep_score.append(sd.sleep_score if sd else None)
        md = dm.get(d)
        vo2.append(md.vo2max if md else None)

    return {
        "dates": dates,
        "recovery": recovery,
        "strain": strain,
        "atl": atl,
        "ctl": ctl,
        "tsb": tsb,
        "rhr": rhr,
        "stress": stress,
        "sleep_score": sleep_score,
        "bb_wake": bb_wake,
        "steps": steps,
        "vo2max": vo2,
    }


def trend_averages(session: Session, days: int = 90, end: date | None = None) -> dict:
    """Mean of each dashboard metric over the trailing `days` window.

    Used by the Today view to show every metric against its chosen trend
    average (e.g. "RHR 52 / gem. 54"). Averages are computed in SQL over
    the same window the Trends page uses, so the number matches what the
    trend charts show. Missing days are simply excluded from each mean (a
    metric with no data in the window yields None, not 0).
    """
    end = end or date.today()
    start = end - timedelta(days=days - 1)

    def _avg(model, column, date_col):
        return session.execute(
            select(func.avg(column)).where(
                model.user_id == USER_ID,
                date_col >= start,
                date_col <= end,
            )
        ).scalar_one_or_none()

    def _avg_sum(model, col_a, col_b, date_col):
        # Sum two columns per row, then average across rows (intensity minutes).
        return session.execute(
            select(func.avg(func.coalesce(col_a, 0) + func.coalesce(col_b, 0))).where(
                model.user_id == USER_ID,
                date_col >= start,
                date_col <= end,
            )
        ).scalar_one_or_none()

    return {
        "days": days,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "recovery": _avg(ComputedScore, ComputedScore.recovery_score, ComputedScore.score_date),
        "strain": _avg(ComputedScore, ComputedScore.strain, ComputedScore.score_date),
        "atl": _avg(ComputedScore, ComputedScore.atl, ComputedScore.score_date),
        "ctl": _avg(ComputedScore, ComputedScore.ctl, ComputedScore.score_date),
        "tsb": _avg(ComputedScore, ComputedScore.tsb, ComputedScore.score_date),
        "sleep_score": _avg(SleepSession, SleepSession.sleep_score, SleepSession.calendar_date),
        "rhr": _avg(DailyWellness, DailyWellness.resting_heart_rate, DailyWellness.calendar_date),
        "stress": _avg(DailyWellness, DailyWellness.avg_stress, DailyWellness.calendar_date),
        "bb_at_wake": _avg(DailyWellness, DailyWellness.bb_at_wake, DailyWellness.calendar_date),
        "bb_most_recent": _avg(DailyWellness, DailyWellness.bb_most_recent, DailyWellness.calendar_date),
        "steps": _avg(DailyWellness, DailyWellness.steps, DailyWellness.calendar_date),
        "intensity_min": _avg_sum(
            DailyWellness,
            DailyWellness.moderate_intensity_minutes,
            DailyWellness.vigorous_intensity_minutes,
            DailyWellness.calendar_date,
        ),
        "spo2": _avg(DailyWellness, DailyWellness.avg_spo2, DailyWellness.calendar_date),
        "respiration": _avg(DailyWellness, DailyWellness.avg_respiration, DailyWellness.calendar_date),
        "vo2max": _avg(DeviceMetrics, DeviceMetrics.vo2max, DeviceMetrics.metric_date),
    }


def recent_series(session: Session, days: int = 14, end: date | None = None) -> dict:
    """Trailing daily series for the Garmin-native mini-visualisations.

    Returns one list per metric (oldest → newest, ending at `end` or today),
    aligned on the same dates, with None for a day that has no value. Used by
    the Today view to render sparklines and goal rings for the watch-native
    indicators. Missing days are left as None (not interpolated) so the
    visualisation can show gaps honestly.
    """
    end = end or date.today()
    start = end - timedelta(days=days - 1)

    wellness = session.execute(
        select(DailyWellness)
        .where(
            DailyWellness.user_id == USER_ID,
            DailyWellness.calendar_date >= start,
            DailyWellness.calendar_date <= end,
        )
        .order_by(DailyWellness.calendar_date)
    ).scalars().all()
    metrics = session.execute(
        select(DeviceMetrics)
        .where(
            DeviceMetrics.user_id == USER_ID,
            DeviceMetrics.metric_date >= start,
            DeviceMetrics.metric_date <= end,
        )
        .order_by(DeviceMetrics.metric_date)
    ).scalars().all()

    w = {r.calendar_date: r for r in wellness}
    dm = {r.metric_date: r for r in metrics}

    dates, rhr, stress, bb_wake, steps, intensity, spo2, resp, vo2 = [], [], [], [], [], [], [], [], []
    for i in range(days):
        d = start + timedelta(days=i)
        dates.append(d.isoformat())
        wd = w.get(d)
        rhr.append(wd.resting_heart_rate if wd else None)
        stress.append(wd.avg_stress if wd and wd.avg_stress is not None and wd.avg_stress >= 0 else None)
        bb_wake.append(wd.bb_at_wake if wd else None)
        steps.append(wd.steps if wd else None)
        intensity.append(
            (wd.moderate_intensity_minutes or 0) + (wd.vigorous_intensity_minutes or 0)
            if wd
            else None
        )
        spo2.append(wd.avg_spo2 if wd else None)
        resp.append(wd.avg_respiration if wd else None)
        md = dm.get(d)
        vo2.append(md.vo2max if md else None)

    return {
        "dates": dates,
        "rhr": rhr,
        "stress": stress,
        "bb_wake": bb_wake,
        "steps": steps,
        "intensity": intensity,
        "spo2": spo2,
        "respiration": resp,
        "vo2max": vo2,
    }


def journal_for(session: Session, day: date) -> dict:
    """Today's journal entry (raw responses + factor registry for the form)."""
    entry = get_entry(session, day)
    return {
        "date": day.isoformat(),
        "responses": entry.responses if entry else {},
        "notes": entry.notes if entry else None,
        "factors": [
            {"key": f.key, "label": f.label, "kind": f.kind, "prompt": f.prompt}
            for f in get_factors(session)
        ],
    }


def factors_for(session: Session) -> dict:
    """The full factor registry (incl. inactive) for the management page."""
    rows = session.execute(
        select(JournalFactor)
        .where(JournalFactor.user_id == 1)
        .order_by(JournalFactor.sort_order, JournalFactor.id)
    ).scalars().all()
    return {
        "factors": [
            {
                "key": r.key,
                "label": r.label,
                "kind": r.kind,
                "prompt": r.prompt,
                "active": r.active,
            }
            for r in rows
        ]
    }


def journal_history(session: Session, days: int = 30, end: date | None = None) -> dict:
    """Recent logged entries, most recent first (web history view)."""
    end = end or date.today()
    start = end - timedelta(days=days - 1)
    entries = entries_in_range(session, start, end)
    out = []
    for e in reversed(entries):
        labels = {}
        for k in e.responses:
            factor = get_factor(session, k)
            labels[k] = factor.label if factor else k
        out.append(
            {
                "date": e.entry_date.isoformat(),
                "responses": {
                    k: {"label": labels.get(k, k), "value": v} for k, v in e.responses.items()
                },
            }
        )
    return {"start": start.isoformat(), "end": end.isoformat(), "entries": out}


def insights_for(
    session: Session,
    end: date | None = None,
    sort: str = "effect",
    direction: str = "desc",
    limit: int | None = None,
) -> dict:
    """Gated correlation insights (dashboard + /api/insights).

    `sort` ∈ {"effect", "date", "alphabet"} — effect = |Cohen's d|,
    date = most recent sample day, alphabet = factor label. `direction` is
    "asc"|"desc". The list is capped at `limit` (INSIGHTS_MAX_DISPLAY) and
    each shown insight carries an optional LLM interpretation (cached).
    """
    end = end or date.today()
    insights = compute_all_insights(session, end=end)
    settings = get_settings()
    limit = settings.INSIGHTS_MAX_DISPLAY if limit is None else limit
    sort = sort if sort in ("date", "alphabet", "effect") else "effect"
    direction = direction if direction in ("asc", "desc") else "desc"

    if sort == "date":
        insights.sort(key=lambda i: i.last_sample_date, reverse=(direction == "desc"))
    elif sort == "alphabet":
        insights.sort(
            key=lambda i: (i.factor_label.lower(), i.outcome_label),
            reverse=(direction == "desc"),
        )
    else:  # effect (default)
        insights.sort(key=lambda i: abs(i.cohens_d), reverse=(direction == "desc"))

    shown = insights[:limit]
    interpretations = interpret_insights(session, shown)
    return {
        "end": end.isoformat(),
        "window_days": settings.JOURNAL_INSIGHT_WINDOW_DAYS,
        "min_samples": settings.JOURNAL_INSIGHT_MIN_SAMPLES,
        "sort": sort,
        "direction": direction,
        "limit": limit,
        "total": len(insights),
        "insights": [
            {
                "factor_key": i.factor_key,
                "factor_label": i.factor_label,
                "outcome_key": i.outcome_key,
                "outcome_label": i.outcome_label,
                "mean_exposed": round(i.mean_exposed, 1),
                "mean_baseline": round(i.mean_baseline, 1),
                "diff": round(i.diff, 1),
                "cohens_d": round(i.cohens_d, 2),
                "magnitude": i.magnitude_label,
                "direction": i.direction,
                "n_exposed": i.n_exposed,
                "n_baseline": i.n_baseline,
                "window_start": i.window_start.isoformat(),
                "window_end": i.window_end.isoformat(),
                "last_sample_date": i.last_sample_date.isoformat(),
                "text": i.text(),
                "interpretation": interpretations.get(idx),
            }
            for idx, i in enumerate(shown)
        ],
    }


def intraday_for(session: Session, day: date) -> dict:
    """1-min series (stress, HR, body battery) + activity windows for a day.

    The day is interpreted in the configured local timezone; stored datetimes
    are naive UTC, so epochs must be converted explicitly (naive.timestamp()
    would assume local time and shift every sample by the UTC offset).
    """
    tz = ZoneInfo(get_settings().TIMEZONE)
    day_start_local = datetime.combine(day, time.min, tzinfo=tz)
    day_start_utc = day_start_local.astimezone(UTC).replace(tzinfo=None)
    day_end_utc = (day_start_local + timedelta(days=1)).astimezone(UTC).replace(tzinfo=None)
    rows = session.execute(
        select(IntradaySeries)
        .where(
            IntradaySeries.user_id == USER_ID,
            IntradaySeries.ts_gmt >= day_start_utc,
            IntradaySeries.ts_gmt < day_end_utc,
        )
        .order_by(IntradaySeries.ts_gmt)
    ).scalars().all()
    series: dict[str, list[list[float]]] = {}
    for r in rows:
        series.setdefault(r.kind, []).append(
            [int(r.ts_gmt.replace(tzinfo=UTC).timestamp()), r.value]
        )

    # Anchor for the sparse body-battery step line: the last event before the
    # day starts, so the first hours of the day show a real value.
    if "body_battery" in series:
        anchor = session.execute(
            select(IntradaySeries)
            .where(
                IntradaySeries.user_id == USER_ID,
                IntradaySeries.kind == "body_battery",
                IntradaySeries.ts_gmt < day_start_utc,
            )
            .order_by(IntradaySeries.ts_gmt.desc())
            .limit(1)
        ).scalar_one_or_none()
        if anchor is not None:
            series["body_battery"].insert(
                0, [int(anchor.ts_gmt.replace(tzinfo=UTC).timestamp()), anchor.value]
            )

    activities = session.execute(
        select(Activity)
        .where(Activity.user_id == USER_ID)
        .order_by(Activity.start_time_gmt)
    ).scalars().all()
    wins = []
    for a in activities:
        start_local = (a.start_time_local or "")[:10]
        if start_local != day.isoformat() or a.duration is None:
            continue
        wins.append(
            {
                "name": a.activity_name,
                "type": a.activity_type,
                "start_s": int(a.start_time_gmt.replace(tzinfo=UTC).timestamp()),
                "end_s": int(a.start_time_gmt.replace(tzinfo=UTC).timestamp()) + int(a.duration),
            }
        )

    return {"date": day.isoformat(), "series": series, "activity_windows": wins}


def _parse_report_time(value: str) -> tuple[int, int]:
    """'07:30' → (7, 30); falls back to (7, 30) on garbage."""
    try:
        hour, minute = value.split(":")
        return int(hour), int(minute)
    except (ValueError, AttributeError):
        return 7, 30


def sleep_status(session: Session, day: date, now: datetime | None = None) -> str:
    """Whether last night's sleep is resolved for the morning report.

    Returns one of:
      "synced"  — a SleepSession row exists for `day`; the report can show it.
      "absent"  — no sleep row, and we're past the grace window (SIGNAL_REPORT_GRACE_MINUTES
                  after the report time): the watch almost certainly didn't record sleep, so
                  the report proceeds without it.
      "pending" — no sleep row yet and still within the grace window: Garmin may be lagging
                  behind on syncing, so the report should wait.

    `day` is the calendar date the report is for (the wake-up date).
    """
    row = session.execute(
        select(SleepSession).where(
            SleepSession.user_id == USER_ID, SleepSession.calendar_date == day
        )
    ).scalar_one_or_none()
    if row is not None:
        return "synced"
    settings = get_settings()
    tz = ZoneInfo(settings.TIMEZONE)
    now = now or datetime.now(tz)
    hour, minute = _parse_report_time(settings.SIGNAL_REPORT_TIME)
    report_dt = datetime.combine(day, time(hour, minute), tzinfo=tz)
    grace_min = int(getattr(settings, "SIGNAL_REPORT_GRACE_MINUTES", 0) or 0)
    if grace_min <= 0:
        return "absent"
    return "absent" if now >= report_dt + timedelta(minutes=grace_min) else "pending"


def latest_sync_time(session: Session) -> datetime | None:
    """The most recent successful sync across all streams (UTC).

    Reads the max last_sync_at from sync_state, which is touched on every
    successful per-stream sync. Returns None when nothing has synced yet.
    """
    return session.execute(
        select(SyncState.last_sync_at)
        .where(SyncState.user_id == USER_ID)
        .order_by(SyncState.last_sync_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def latest_morning_report(session: Session) -> dict | None:
    """The most recent Signal morning briefing (the advice sent this morning).

    Returns None when no morning report has been persisted yet (e.g. a fresh
    install before the first scheduled send).
    """
    row = session.execute(
        select(MorningReport)
        .where(MorningReport.user_id == USER_ID)
        .order_by(MorningReport.report_date.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return None
    return {
        "date": row.report_date.isoformat(),
        "briefing": row.briefing,
        "commentary": row.commentary,
    }
