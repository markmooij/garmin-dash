"""FastAPI routes for the dashboard (HTML views + JSON API)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from ..db import get_session
from ..journal.entries import upsert_entry
from ..journal.schema import create_factor, delete_factor, get_factors, update_factor
from ..settings import get_settings
from . import explanation, query, viz


if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


def _root_path() -> str:
    """Subpath prefix the app is served under (e.g. "/supermarxx")."""
    return (get_settings().ROOT_PATH or "").rstrip("/")


def url(path: str) -> str:
    """Prefix an app-relative path with the configured ROOT_PATH.

    Templates call this for every asset/nav/redirect path so the dashboard
    works when mounted behind a reverse proxy at a URL prefix (e.g.
    /supermarxx) instead of the domain root.
    """
    root = _root_path()
    if not root:
        return path
    if path == "/":
        return root + "/"
    return root + path


def root_path() -> str:
    """The subpath prefix with no trailing slash ("" at the domain root).

    Exposed to templates so inline JS can build paths (e.g. fetch() calls)
    by concatenating this prefix with an app-relative path.
    """
    return _root_path()


# Make `url()` and `root_path()` available to every template.
templates.env.globals["url"] = url
templates.env.globals["root_path"] = root_path

# Make the Garmin-native SVG visualisations available to every template.
for _fn in (
    "sparkline",
    "gauge",
    "ring",
    "battery",
    "stress_gauge",
    "spo2_gauge",
    "resp_gauge",
    "vo2_gauge",
    "rhr_color",
    "stress_color",
    "bb_color",
    "vo2_color",
    "spo2_color",
    "resp_color",
    "steps_color",
    "intensity_color",
):
    templates.env.globals[_fn] = getattr(viz, _fn)


def _db() -> Session:
    """Request-scoped DB session (no request needed)."""
    return get_session()


@router.get("/healthz")
def healthz(db: Session = Depends(_db)):  # noqa: B008
    """Liveness/readiness probe for Docker healthcheck + uptime monitors."""
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception:  # noqa: BLE001
        return JSONResponse({"status": "error"}, status_code=503)


# ── HTML views ─────────────────────────────────────────────────────────

@router.get("/")
def today_view(
    request: Request,
    db: Session = Depends(_db),  # noqa: B008
    date: date | None = None,
    days: int = 90,
):
    day = date or _today_local()
    days = days if days in (30, 90, 180) else 90
    try:
        data = query.summary_for(db, day)
        avg = query.trend_averages(db, days=days, end=day)
        recent = query.recent_series(db, days=14, end=day)
        last_sync = query.latest_sync_time(db)
        morning = query.latest_morning_report(db)
    finally:
        db.close()
    return templates.TemplateResponse(
        request,
        "today.html",
        {
            "day": day,
            "prev": day - timedelta(days=1),
            "next": day + timedelta(days=1),
            "data": data,
            "avg": avg,
            "recent": recent,
            "days": days,
            "last_sync": _fmt_sync_time(last_sync),
            "morning": morning,
        },
    )


@router.get("/trends")
def trends_view(
    request: Request,
    db: Session = Depends(_db),  # noqa: B008
    days: int = 90,
):
    try:
        data = query.trends_for(db, days=days)
    finally:
        db.close()
    return templates.TemplateResponse(request, "trends.html", {"days": days, "data": data})


@router.get("/journal")
def journal_view(
    request: Request,
    db: Session = Depends(_db),  # noqa: B008
    date: date | None = None,
):
    day = date or _today_local()
    try:
        data = query.journal_for(db, day)
        history = query.journal_history(db, days=30, end=day)
    finally:
        db.close()
    return templates.TemplateResponse(
        request,
        "journal.html",
        {
            "day": day,
            "prev": day - timedelta(days=1),
            "next": day + timedelta(days=1),
            "data": data,
            "history": history,
        },
    )


@router.post("/journal")
async def journal_save(
    request: Request,
    db: Session = Depends(_db),  # noqa: B008
):
    """Save the journal form: one field per active factor, prefixed 'f_'.

    Checkboxes only submit when checked (bool factors default False when
    absent from the form); count factors are parsed as float, blank/invalid
    values are skipped rather than stored as garbage.
    """
    form = await request.form()
    entry_date_raw = form.get("entry_date")
    entry_date = date.fromisoformat(str(entry_date_raw)) if entry_date_raw else _today_local()
    notes = str(form.get("notes") or "") or None

    responses: dict = {}
    for factor in get_factors(db):
        field = f"f_{factor.key}"
        if factor.kind == "bool":
            responses[factor.key] = field in form
        else:
            raw = form.get(field)
            if raw in (None, ""):
                continue
            try:
                responses[factor.key] = float(str(raw))
            except ValueError:
                continue

    try:
        upsert_entry(db, entry_date, responses, notes=notes)
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url=url(f"/journal?date={entry_date}"), status_code=303)


@router.get("/insights")
def insights_view(
    request: Request,
    db: Session = Depends(_db),  # noqa: B008
    sort: str = "effect",
    dir: str = "desc",
):
    sort = sort if sort in ("effect", "date", "alphabet") else "effect"
    direction = dir if dir in ("asc", "desc") else "desc"
    try:
        data = query.insights_for(db, sort=sort, direction=direction)
    finally:
        db.close()
    return templates.TemplateResponse(request, "insights.html", {"data": data})


@router.get("/uitleg")
def explanation_view(request: Request):
    """GET /uitleg — what each metric is, does, and how it develops."""
    return templates.TemplateResponse(
        request, "explanation.html", {"data": explanation.build_context()}
    )


@router.get("/coach")
def coach_view(request: Request):
    settings = get_settings()
    return templates.TemplateResponse(
        request, "coach.html", {"enabled": settings.LLM_ENABLED}
    )


@router.post("/api/coach/ask")
async def api_coach_ask(request: Request, db: Session = Depends(_db)):  # noqa: B008
    """Ask the coach a free-form question, grounded in the same numbers the
    dashboard shows. Always returns 200 with a text answer — disabled/failed
    states are user-facing messages, not errors (matches ask_coach's contract).
    """
    body = await request.json()
    question = str(body.get("question") or "").strip()
    if not question:
        return JSONResponse({"answer": "Stel een vraag."}, status_code=400)
    try:
        from ..coach.client import ask_coach

        answer = ask_coach(db, question)
    finally:
        db.close()
    return JSONResponse({"answer": answer})


@router.get("/intraday")
def intraday_view(
    request: Request,
    db: Session = Depends(_db),  # noqa: B008
    date: date | None = None,
):
    day = date or _today_local()
    try:
        data = query.intraday_for(db, day)
    finally:
        db.close()
    return templates.TemplateResponse(
        request,
        "intraday.html",
        {"day": day, "prev": day - timedelta(days=1), "next": day + timedelta(days=1), "data": data},
    )


# ── JSON API (extensibility contract: new card ≈ partial + route) ───────

@router.get("/journal/factors")
def factors_view(
    request: Request,
    db: Session = Depends(_db),  # noqa: B008
):
    """Factor management: add / edit / remove journal questions."""
    try:
        data = query.factors_for(db)
    finally:
        db.close()
    return templates.TemplateResponse(request, "factors.html", {"data": data})


@router.post("/journal/factors")
async def factors_add(
    request: Request,
    db: Session = Depends(_db),  # noqa: B008
):
    """Add a factor (or re-activate a soft-deleted one with the same key)."""
    form = await request.form()
    try:
        create_factor(
            db,
            key=str(form.get("key") or ""),
            label=str(form.get("label") or ""),
            kind=str(form.get("kind") or "bool"),
            prompt=str(form.get("prompt") or ""),
        )
        db.commit()
        return RedirectResponse(url=url("/journal/factors"), status_code=303)
    except ValueError as exc:
        db.rollback()
        data = query.factors_for(db)
        return templates.TemplateResponse(
            request,
            "factors.html",
            {"data": data, "error": str(exc), "form": dict(form)},
            status_code=400,
        )
    finally:
        db.close()


@router.post("/journal/factors/{key}/edit")
async def factors_edit(
    key: str,
    request: Request,
    db: Session = Depends(_db),  # noqa: B008
):
    """Edit a factor's label / kind / prompt."""
    form = await request.form()
    try:
        update_factor(
            db,
            key,
            label=str(form.get("label") or ""),
            kind=str(form.get("kind") or "bool"),
            prompt=str(form.get("prompt") or ""),
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        data = query.factors_for(db)
        return templates.TemplateResponse(
            request,
            "factors.html",
            {"data": data, "error": str(exc)},
            status_code=400,
        )
    finally:
        db.close()
    return RedirectResponse(url=url("/journal/factors"), status_code=303)


@router.post("/journal/factors/{key}/delete")
def factors_delete(
    key: str,
    db: Session = Depends(_db),  # noqa: B008
):
    """Remove a factor (soft delete — logged data is kept, just hidden)."""
    try:
        delete_factor(db, key)
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url=url("/journal/factors"), status_code=303)


@router.post("/journal/factors/{key}/restore")
def factors_restore(
    key: str,
    db: Session = Depends(_db),  # noqa: B008
):
    """Re-activate a soft-deleted factor."""
    try:
        update_factor(db, key, active=True)
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url=url("/journal/factors"), status_code=303)


@router.get("/api/summary")
def api_summary(
    db: Session = Depends(_db),  # noqa: B008
    date: date | None = None,
):
    day = date or _today_local()
    try:
        return JSONResponse(query.summary_for(db, day))
    finally:
        db.close()


@router.get("/api/trends")
def api_trends(
    db: Session = Depends(_db),  # noqa: B008
    days: int = Query(90, ge=7, le=365),  # noqa: B008
):
    try:
        return JSONResponse(query.trends_for(db, days=days))
    finally:
        db.close()


@router.get("/api/intraday")
def api_intraday(
    db: Session = Depends(_db),  # noqa: B008
    date: date | None = None,
):
    day = date or _today_local()
    try:
        return JSONResponse(query.intraday_for(db, day))
    finally:
        db.close()


@router.get("/api/journal")
def api_journal(
    db: Session = Depends(_db),  # noqa: B008
    date: date | None = None,
):
    day = date or _today_local()
    try:
        return JSONResponse(query.journal_for(db, day))
    finally:
        db.close()


@router.get("/api/insights")
def api_insights(
    db: Session = Depends(_db),  # noqa: B008
):
    try:
        return JSONResponse(query.insights_for(db))
    finally:
        db.close()


def _today_local() -> date:
    """Server-local calendar date (dev machine / container TZ)."""
    return date.today()


def _fmt_sync_time(sync_at) -> str | None:
    """Format a UTC sync timestamp in the configured local timezone.

    Returns None when nothing has synced yet; otherwise e.g. "04 sep 2026,
    09:58" (local).
    """
    if sync_at is None:
        return None
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(get_settings().TIMEZONE)
    local = sync_at.astimezone(tz)
    return local.strftime("%d %b %Y, %H:%M")
