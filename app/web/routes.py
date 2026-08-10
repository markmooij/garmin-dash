"""FastAPI routes for the dashboard (HTML views + JSON API)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates

from ..db import get_session
from . import query


if TYPE_CHECKING:
    from sqlalchemy.orm import Session

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


def _db() -> Session:
    """Request-scoped DB session (no request needed)."""
    return get_session()


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


@router.get("/healthz")
def healthz():
    return {"status": "ok"}


def _today_local() -> date:
    """Server-local calendar date (dev machine / container TZ)."""
    return date.today()
