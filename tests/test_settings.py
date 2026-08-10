"""Tests for settings module."""

from app.settings import Settings


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
