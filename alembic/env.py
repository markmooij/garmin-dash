"""Alembic environment — wired to app settings + models."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app.db import Base
from app.db import models  # noqa: F401  (register models)
from app.settings import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _db_url() -> str:
    return f"sqlite:///{get_settings().DB_PATH}"


def run_migrations_offline() -> None:
    context.configure(
        url=_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # sqlite ALTER support
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_db_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    # Single-user app: ensure the default user exists on every boot
    # (idempotent; the dashboard and sync_state FK to users.id=1).
    from app.db import get_session, seed_default_user

    session = get_session()
    try:
        seed_default_user(session)
        session.commit()
    finally:
        session.close()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
