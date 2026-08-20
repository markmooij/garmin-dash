"""FastAPI application factory for the garmin-dash web dashboard."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..settings import get_settings
from . import routes


logger = logging.getLogger("garmin_dash.web")

STATIC_DIR = Path(__file__).parent / "static"


def _warn_missing_dashboard_url() -> None:
    """Signal messages link the dashboard via DASHBOARD_URL; remind operators."""
    settings = get_settings()
    if settings.SIGNAL_ENABLED and not (settings.DASHBOARD_URL or "").strip():
        logger.warning(
            "SIGNAL_ENABLED=true but DASHBOARD_URL is unset — Signal messages will "
            "not link the dashboard. Set DASHBOARD_URL to the public URL of this "
            "instance (e.g. http://<host>:<port>) to enable the links."
        )


def create_app() -> FastAPI:
    """Build the ASGI app (uvicorn app.app:app)."""
    app = FastAPI(title="Garmin Dash", version=__version__)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(routes.router)
    _warn_missing_dashboard_url()
    return app
