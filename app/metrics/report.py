"""Text report rendering for the metrics engine (gdash report)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from ..db.models import ComputedScore, DailyWellness


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _spark(values: list[float | None], lo: float = 0.0, hi: float = 100.0) -> str:
    """Compact ASCII sparkline (uPlot will take over in Phase 3)."""
    if not values:
        return ""
    chars = "▁▂▃▄▅▆▇█"
    span = (hi - lo) or 1.0
    out = []
    for v in values:
        if v is None:
            out.append("·")
            continue
        idx = int(max(0.0, min(1.0, (v - lo) / span)) * (len(chars) - 1))
        out.append(chars[idx])
    return "".join(out)


def report_today(session: Session, day: date | None = None) -> str:
    day = day or date.today()
    lines: list[str] = []
    score = session.execute(
        select(ComputedScore).where(
            ComputedScore.user_id == 1, ComputedScore.score_date == day
        )
    ).scalar_one_or_none()

    lines.append(f"📊 garmin-dash — {day.isoformat()}")
    lines.append("─" * 56)
    if score is None:
        lines.append("  No computed scores for this day yet — run: gdash ingest sync && gdash metrics compute")
        return "\n".join(lines)

    rec = score.recovery_score
    band_icon = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(score.recovery_band or "", "⚪")
    lines.append(f"  Recovery  {band_icon} {rec if rec is not None else '—':>6.1f}/100  [{score.recovery_band or 'n/a'}]")
    lines.append(f"  Strain    🏋️ {score.strain if score.strain is not None else 0:>6.2f}/21")
    lines.append(f"  TSB       ⚖️  {score.tsb if score.tsb is not None else 0:>6.1f}   (CTL {score.ctl or 0:.1f} / ATL {score.atl or 0:.1f})")

    payload = score.payload or {}
    rec_detail = (payload.get("recovery") or {})
    comps = rec_detail.get("components") or {}
    if comps:
        lines.append("  └ recovery inputs:")
        for k, v in comps.items():
            lines.append(f"      {k:<8} {v:>6.1f}")
        weights = rec_detail.get("weights") or {}
        wstr = ", ".join(f"{k}={v:.2f}" for k, v in sorted(weights.items()))
        lines.append(f"      weights  ({wstr}){'  [HRV unavailable → fallback]' if not rec_detail.get('hrv_used') else ''}")

    breakdown = payload.get("breakdown") or []
    if breakdown:
        lines.append("  └ load breakdown:")
        for b in breakdown:
            lines.append(
                f"      {b.get('type','?'):<18} trimp {b.get('trimp',0):>8.1f}  "
                f"edwards {b.get('edwards',0):>7.1f}  strength {b.get('strength_duration',0):>7.1f}"
            )

    lines.append("  ─")
    wellness = session.execute(
        select(DailyWellness).where(
            DailyWellness.user_id == 1, DailyWellness.calendar_date == day
        )
    ).scalar_one_or_none()
    if wellness:
        lines.append(
            f"  Garmin-native: RHR {wellness.resting_heart_rate or '—'} · avg stress {wellness.avg_stress or '—'} · "
            f"BB at wake {wellness.bb_at_wake or '—'} (peak {wellness.bb_highest or '—'}) · "
            f"steps {wellness.steps or '—'}"
        )

    # 14-day trend
    start = day - timedelta(days=13)
    rows = session.execute(
        select(ComputedScore)
        .where(ComputedScore.user_id == 1, ComputedScore.score_date >= start, ComputedScore.score_date <= day)
        .order_by(ComputedScore.score_date)
    ).scalars().all()
    by_day = {r.score_date: r for r in rows}
    recs = [by_day.get(day - timedelta(days=i)) for i in range(13, -1, -1)]
    strains = [r.strain if r else None for r in recs]
    recovs = [r.recovery_score if r else None for r in recs]
    lines.append("  ─")
    lines.append(f"  14d strain:   {_spark(strains, 0, 21)}")
    lines.append(f"  14d recovery: {_spark(recovs, 0, 100)}")
    return "\n".join(lines)


def report_range(session: Session, days: int, title: str, day: date | None = None) -> str:
    day = day or date.today()
    start = day - timedelta(days=days - 1)
    rows = session.execute(
        select(ComputedScore)
        .where(
            ComputedScore.user_id == 1,
            ComputedScore.score_date >= start,
            ComputedScore.score_date <= day,
        )
        .order_by(ComputedScore.score_date)
    ).scalars().all()

    lines = [f"📊 garmin-dash — {title} ({start.isoformat()} → {day.isoformat()})", "─" * 56]
    if not rows:
        lines.append("  No computed scores in range.")
        return "\n".join(lines)

    recs = [r.recovery_score for r in rows if r.recovery_score is not None]
    strains = [r.strain for r in rows if r.strain is not None]
    tsbs = [r.tsb for r in rows if r.tsb is not None]
    days_with = sum(1 for r in rows if (r.recovery_score is not None or (r.strain or 0) > 0))

    if recs:
        lines.append(f"  Recovery   avg {sum(recs)/len(recs):>5.1f}  min {min(recs):.1f}  max {max(recs):.1f}  ({len(recs)}/{len(rows)} days)")
    if strains:
        lines.append(f"  Strain     avg {sum(strains)/len(strains):>5.2f}  total {sum(strains):.1f}  max {max(strains):.2f}")
    if tsbs:
        lines.append(f"  TSB        avg {sum(tsbs)/len(tsbs):>5.1f}  min {min(tsbs):.1f}  max {max(tsbs):.1f}")
    lines.append(f"  Active days {days_with}/{len(rows)}")

    strain_spark = _spark([r.strain if r else None for r in rows], 0, 21)
    rec_spark = _spark([r.recovery_score if r else None for r in rows], 0, 100)
    lines.append(f"  strain:   {strain_spark}")
    lines.append(f"  recovery: {rec_spark}")
    return "\n".join(lines)
