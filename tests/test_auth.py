"""Tests for authentication module."""

import pytest
from pathlib import Path


def test_token_cache_path():
    """Test token cache path can be created."""
    from app.auth.cli import AuthSettings
    settings = AuthSettings()
    # Create directory
    settings.token_cache_path.parent.mkdir(exist_ok=True)
    assert settings.token_cache_path.parent.exists()


def test_fixture_dir_created():
    """Test fixtures directory exists."""
    fixtures_dir = Path("tests/fixtures")
    assert fixtures_dir.exists() or fixtures_dir.mkdir(exist_ok=True)
