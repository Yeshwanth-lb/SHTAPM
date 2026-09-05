"""Alembic environment (P4).

Reads ``DATABASE_URL`` from the environment (not ``alembic.ini`` — keeps one
source of truth with the running app, per ``app.core.config.DatabaseSettings``).
Migrations target Postgres/TimescaleDB only; they are not run against the
SQLite engine used by unit tests (see ``backend/tests/test_models.py``, which
builds tables directly from ``Base.metadata`` instead).
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from app.models import Base  # noqa: F401 — import registers all tables on Base.metadata
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is required to run migrations (see .env.example)")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
