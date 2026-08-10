"""ASGI entry point (uvicorn app.app:app)."""

from __future__ import annotations

from .web import create_app


app = create_app()
