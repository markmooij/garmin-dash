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
from ..journal.schema import FACTORS_BY_KEY
from . import query


if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


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
):
    day = date or _today_local()
    try:
        data = query.summary_for(db, day)
    finally:
        db.close()
    return templates.TemplateResponse(
        request,
        "today.html",
        {"day": day, "prev": day - timedelta(days=1), "next": day + timedelta(days=1), "data": data},
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
    """Save the journal form: one field per registered factor, prefixed 'f_'.

    Checkboxes only submit when checked (bool factors default False when
    absent from the form); count factors are parsed as float, blank/invalid
    values are skipped rather than stored as garbage.
    """
    form = await request.form()
    entry_date_raw = form.get("entry_date")
    entry_date = date.fromisoformat(str(entry_date_raw)) if entry_date_raw else _today_local()
    notes = str(form.get("notes") or "") or None

    responses: dict = {}
    for key, factor in FACTORS_BY_KEY.items():
        field = f"f_{key}"
        if factor.kind == "bool":
            responses[key] = field in form
        else:
            raw = form.get(field)
            if raw in (None, ""):
                continue
            try:
                responses[key] = float(str(raw))
            except ValueError:
                continue

    try:
        upsert_entry(db, entry_date, responses, notes=notes)
        db.commit()
    finally:
        db.close()
    return RedirectResponse(url=f"/journal?date={entry_date}", status_code=303)


@router.get("/insights")
def insights_view(
    request: Request,
    db: Session = Depends(_db),  # noqa: B008
):
    try:
        data = query.insights_for(db)
    finally:
        db.close()
    return templates.TemplateResponse(request, "insights.html", {"data": data})


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
