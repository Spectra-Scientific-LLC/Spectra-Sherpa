from __future__ import annotations

import asyncio
import logging

from spectra_sherpa.app import models  # noqa: F401  # Ensure models are registered
from spectra_sherpa.app.db.base import Base
from spectra_sherpa.app.db.session import engine

logger = logging.getLogger(__name__)


async def init_db() -> None:
    """Initialise the database schema.

    Uses Alembic migrations in **all** modes to keep the schema in sync
    with the codebase.

    - **Fresh database** (no tables): ``create_all`` bootstraps the full
      schema, then ``alembic upgrade head`` runs every migration to stamp
      ``alembic_version``.  Most migrations are idempotent (guarded with
      ``_table_exists`` / ``_column_exists``); structural migrations like
      ``l2g4h6i8j471`` skip when their work is already done.
    - **Legacy database** (tables but no ``alembic_version``): same as
      fresh — ``create_all`` adds any new tables, then ``upgrade head``
      runs all migrations, adding any missing columns.
    - **Tracked database** (has ``alembic_version``): ``upgrade head``
      applies only pending migrations.
    """
    from sqlalchemy import inspect as sa_inspect

    async with engine.connect() as conn:
        table_names = await conn.run_sync(lambda sync_conn: sa_inspect(sync_conn).get_table_names())

    has_alembic = "alembic_version" in table_names

    if not has_alembic:
        # Fresh or legacy database — bootstrap tables first.
        # create_all() is idempotent for existing tables so it safely
        # creates any new tables without touching existing ones.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        label = "fresh" if not table_names else "legacy (untracked)"
        logger.info("Bootstrapped %s database tables via create_all", label)

    # Run all migrations from base (untracked) or pending (tracked).
    # Most migrations use idempotent guards (_table_exists / _column_exists);
    # structural migrations (e.g. FK rebuilds) skip when already applied.
    try:
        await _run_alembic("upgrade", "head")
        logger.info("Alembic migrations applied successfully")
    except Exception as exc:
        logger.error(
            "Alembic migration failed: %s",
            exc,
            exc_info=True,
        )
        raise RuntimeError("Database migration failed; startup aborted.") from exc


async def _run_alembic(cmd: str, revision: str) -> None:
    """Run an Alembic command in a worker thread.

    Alembic's ``env.py`` calls ``asyncio.run()`` which cannot nest inside
    an active event loop, so we delegate to ``asyncio.to_thread``.
    """
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
    await asyncio.to_thread(getattr(command, cmd), cfg, revision)
