"""Tests for authentication module."""

import pytest
from pathlib import Path


def test_session_module_imports():
    """Auth session module exposes the real login flow."""
    from app.auth import session

    assert callable(session.start_login)
    assert callable(session.finish_login)
    assert callable(session.resume_from_tokens)


def test_missing_credentials_raise_autherror(monkeypatch):
    """Missing GARMIN_EMAIL/PASSWORD produces a clear AuthError."""
    import pytest as _pytest

    from app.auth import session

    monkeypatch.setenv("GARMIN_EMAIL", "")
    monkeypatch.setenv("GARMIN_PASSWORD", "")

    with _pytest.raises(session.AuthError):
        session.start_login()


def test_fixture_dir_created():
    """Test fixtures directory exists."""
    fixtures_dir = Path("tests/fixtures")
    assert fixtures_dir.exists() or fixtures_dir.mkdir(exist_ok=True)
