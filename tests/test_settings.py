"""Tests for settings module."""

import logging

from app.settings import Settings
from app.web import _warn_missing_dashboard_url


def test_settings_defaults():
    """Test default settings values."""
    settings = Settings()
    assert settings.APP_NAME == "Garmin Dash"
    assert settings.DEBUG is True
    assert settings.DOCKER_PROFILE == "dev"


def test_settings_prod():
    """Test production settings."""
    settings = Settings()
    settings.DOCKER_PROFILE = "prod"
    assert settings.is_prod is True


def test_settings_log_path():
    """Test log path property."""
    settings = Settings()
    settings.log_path.mkdir(exist_ok=True)
    assert settings.log_path.exists()


def test_settings_data_path():
    """Test data path property."""
    settings = Settings()
    settings.data_path.mkdir(exist_ok=True)
    assert settings.data_path.exists()


# ── DASHBOARD_URL operator warning ───────────────────────────────────

def test_warns_when_signal_enabled_without_dashboard_url(monkeypatch, caplog):
    """Signal messages link the dashboard — warn when the URL is missing."""

    class _Settings:
        SIGNAL_ENABLED = True
        DASHBOARD_URL = ""

    monkeypatch.setattr("app.web.get_settings", lambda: _Settings())
    with caplog.at_level(logging.WARNING, logger="garmin_dash.web"):
        _warn_missing_dashboard_url()
    assert "DASHBOARD_URL" in caplog.text


def test_no_warning_when_dashboard_url_set(monkeypatch, caplog):
    class _Settings:
        SIGNAL_ENABLED = True
        DASHBOARD_URL = "http://pi.local:8081"

    monkeypatch.setattr("app.web.get_settings", lambda: _Settings())
    with caplog.at_level(logging.WARNING, logger="garmin_dash.web"):
        _warn_missing_dashboard_url()
    assert caplog.text == ""


def test_no_warning_when_signal_disabled(monkeypatch, caplog):
    class _Settings:
        SIGNAL_ENABLED = False
        DASHBOARD_URL = ""

    monkeypatch.setattr("app.web.get_settings", lambda: _Settings())
    with caplog.at_level(logging.WARNING, logger="garmin_dash.web"):
        _warn_missing_dashboard_url()
    assert caplog.text == ""
