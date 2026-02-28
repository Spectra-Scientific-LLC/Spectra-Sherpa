from __future__ import annotations

import asyncio
import logging

import sqlalchemy as sa

from spectra_sherpa.app import models  # noqa: F401  # Ensure models are registered
from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.db.base import Base
from spectra_sherpa.app.db.session import engine

logger = logging.getLogger(__name__)


def _backfill_missing_columns(connection: sa.Connection) -> None:
    """Add columns defined in the ORM but missing from existing tables.

    ``create_all`` only creates *new* tables; it never alters existing ones.
    This helper bridges the gap for local-mode upgrades so that new nullable
    columns are added without requiring Alembic.
    """
    inspector = sa.inspect(connection)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue
        existing = {col["name"] for col in inspector.get_columns(table.name)}
        for col in table.columns:
            if col.name not in existing and col.nullable:
                connection.execute(
                    sa.text(f"ALTER TABLE [{table.name}] ADD COLUMN [{col.name}] {col.type}")
                )
                logger.info("Local schema upgrade: added %s.%s", table.name, col.name)


async def init_db() -> None:
    """Initialise the database schema.

    - **local mode**: Uses ``create_all`` for zero-config bootstrap (new tables
      are added automatically; columns are never altered).  A lightweight
      backfill adds any missing nullable columns to existing tables.
    - **hybrid / demo modes**: Runs Alembic ``upgrade head`` so schema
      migrations (column adds/renames, index changes) are applied correctly.
      Startup fails if migrations cannot be applied.
    """
    if app_config.mode == "local":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(_backfill_missing_columns)
        return

    # Non-local modes: require Alembic migrations.
    # Run the Alembic command in a worker thread because Alembic's env.py
    # executes asyncio.run(...), which fails inside an active event loop.
    try:
        from alembic import command
        from alembic.config import Config

        from spectra_sherpa._paths import get_package_root

        package_root = get_package_root()
        alembic_dir = package_root / "alembic"
        alembic_ini = package_root / "alembic.ini"

        if not alembic_ini.exists() or not alembic_dir.exists():
            raise RuntimeError(f"Alembic config missing (ini={alembic_ini}, dir={alembic_dir})")

        cfg = Config(str(alembic_ini))
        cfg.set_main_option("script_location", str(alembic_dir))
        cfg.set_main_option("sqlalchemy.url", str(engine.url))
        # Prevent Alembic env.py from reconfiguring logging (root→WARN)
        cfg.set_main_option("_skip_logging_config", "true")
        await asyncio.to_thread(command.upgrade, cfg, "head")
        logger.info("Alembic migrations applied successfully")
    except Exception as exc:
        logger.error(
            "Alembic migration failed in %s mode; refusing to continue: %s",
            app_config.mode,
            exc,
            exc_info=True,
        )
        raise RuntimeError("Database migration failed; startup aborted.") from exc
