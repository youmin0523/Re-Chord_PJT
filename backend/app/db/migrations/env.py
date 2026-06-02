"""Alembic migration runtime — async-aware bootstrap.

Run from project root:
    alembic -c backend/app/db/alembic.ini revision --autogenerate -m "init"
    alembic -c backend/app/db/alembic.ini upgrade head

Requires ``DATABASE_URL`` env var or ``sqlalchemy.url`` in alembic.ini.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config


# Alembic config object — gives us access to .ini values.
config = context.config

# Logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject DATABASE_URL into the config if the env var is set.
# configparser uses %-interpolation, so URL-encoded chars in the password
# (e.g. %40 for '@', %2C for ',') would be parsed as broken interpolation
# tokens. Double them up so configparser collapses %% back to % and the
# URL reaches SQLAlchemy intact.
env_url = os.environ.get("DATABASE_URL")
if env_url:
    config.set_main_option("sqlalchemy.url", env_url.replace("%", "%%"))

# Import target metadata.
from backend.app.db.models import Base  # noqa: E402

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection (generates SQL only)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
