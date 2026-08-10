"""FastAPI application factory for the garmin-dash web dashboard."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .. import __version__
from . import routes


STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    """Build the ASGI app (uvicorn app.app:app)."""
    app = FastAPI(title="Garmin Dash", version=__version__)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(routes.router)
    return app
