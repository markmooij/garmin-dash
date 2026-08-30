"""Database engine, session factory, and declarative base."""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from ..settings import get_settings


if TYPE_CHECKING:
    from collections.abc import Iterator

    from .models import User


class Base(DeclarativeBase):
    """Declarative base for all models."""


def _make_engine(db_path: str):
    """Create a SQLite engine with WAL + FK pragmas."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    return engine


def create_session_factory(db_path: str | None = None) -> sessionmaker[Session]:
    """Create a sessionmaker bound to the configured database."""
    path = db_path or get_settings().DB_PATH
    engine = _make_engine(path)
    return sessionmaker(bind=engine, expire_on_commit=False)


# Default factory for the app; tests create their own.
_session_factory = create_session_factory()


@contextlib.contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session context: commit on success, rollback on error."""
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Session:
    """Return a new database session."""
    return _session_factory()


def seed_default_user(session: Session) -> User:
    """Ensure the default single-user row exists (id=1)."""
    from .models import User

    user = session.get(User, 1)
    if user is None:
        user = User(id=1, display_name="Me")
        session.add(user)
        session.commit()
    return user


def init_db() -> None:
    """Create all tables + default user + seed factors (tests / first-run bootstrap)."""
    from . import models  # noqa: F401

    engine = _session_factory().bind
    if engine is not None:
        Base.metadata.create_all(bind=engine)
    session = _session_factory()
    try:
        seed_default_user(session)
        from ..journal.schema import seed_factors

        seed_factors(session)
        session.commit()
    finally:
        session.close()
