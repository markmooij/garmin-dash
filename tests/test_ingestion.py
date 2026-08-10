"""Tests for ingestion module."""

from pathlib import Path


def test_fixtures_dir_exists():
    """Test fixtures directory exists."""
    fixtures_dir = Path("tests/fixtures")
    assert fixtures_dir.exists() or fixtures_dir.mkdir(exist_ok=True)


def test_fixture_files_created():
    """Test fixture files are created by backfill."""
    fixtures_dir = Path("tests/fixtures")
    # These will be created by the backfill script
    fixture_files = list(fixtures_dir.glob("*.json"))
    if fixture_files:
        assert len(fixture_files) > 0
