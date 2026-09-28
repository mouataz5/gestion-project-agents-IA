"""Alembic environment.

The database URL comes from, in order: ``config.attributes["database_url"]`` (programmatic use,
tests) or the application settings (``DATABASE_URL``). It is never stored in ``alembic.ini``.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import Connection, create_engine, pool

import app.models  # noqa: F401  (registers every model on Base.metadata)
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.base import Base

config = context.config
target_metadata = Base.metadata

if not config.attributes.get("skip_logging_setup", False):
    configure_logging(get_settings(), component="migrations")


def _database_url() -> str:
    url = config.attributes.get("database_url")
    return str(url) if url else get_settings().database_dsn


def _configure(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            _configure(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
