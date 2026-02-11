from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

import spectra_sherpa  # noqa: F401 — activates app.* alias finder

from app.core.config import settings
from app.db.base import Base
import app.models  # noqa: F401

config = context.config

# Only apply alembic.ini logging config when Alembic is run standalone (CLI).
# When invoked programmatically from init_db (config_file_name is still set
# but the app has already configured logging), fileConfig would reset the
# root logger to WARN and suppress all INFO messages for the rest of startup.
if config.config_file_name is not None and not config.get_main_option("_skip_logging_config"):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    return settings.database_url


def run_migrations_offline() -> None:
    url = get_url()
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


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section) or {},
        url=get_url(),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
