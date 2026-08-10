"""Shared pytest fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.db import create_session_factory, seed_default_user
from app.db.models import Base


if TYPE_CHECKING:
    from sqlalchemy.orm import Session


@pytest.fixture
def session(tmp_path) -> Session:
    factory = create_session_factory(str(tmp_path / "test.db"))
    Base.metadata.create_all(bind=factory().get_bind())
    s = factory()
    seed_default_user(s)
    return s
