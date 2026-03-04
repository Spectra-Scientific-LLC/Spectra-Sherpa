"""Validate init_db bootstrap paths: fresh, legacy-untracked, and tracked.

These tests create real temp SQLite databases and run the full Alembic
migration chain to verify that the three-path logic in init_db.py is safe.

The Alembic ``env.py`` reads its URL from ``settings.database_url``, so each
test monkeypatches that setting to point at the temp database.
"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text

from spectra_sherpa.app.db.base import Base


def _alembic_cfg() -> Config:
    """Build an Alembic Config."""
    from spectra_sherpa._paths import get_package_root

    package_root = get_package_root()
    alembic_ini = package_root / "alembic.ini"
    alembic_dir = package_root / "alembic"

    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(alembic_dir))
    cfg.set_main_option("_skip_logging_config", "true")
    return cfg


def _run_upgrade_head(async_url: str) -> None:
    """Run alembic upgrade head with settings.database_url overridden."""
    from spectra_sherpa.app.core.config import settings

    original = settings.database_url
    # Settings is frozen (Pydantic), so use object.__setattr__
    object.__setattr__(settings, "database_url", async_url)
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, "head")
    finally:
        object.__setattr__(settings, "database_url", original)


def _sync_url(path: Path) -> str:
    return f"sqlite:///{path}"


def _async_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path}"


class TestBootstrapFreshDB:
    """Scenario: empty database, no tables at all.

    Mirrors init_db.py's untracked path: create_all() then upgrade head.
    """

    def test_create_all_then_upgrade_head(self, tmp_path):
        db_path = tmp_path / "fresh.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)

        # Step 1: create_all (same as init_db for untracked)
        sync_engine = sa.create_engine(sync_url)
        Base.metadata.create_all(sync_engine)

        # Verify tables exist
        inspector = sa_inspect(sync_engine)
        assert "user" in inspector.get_table_names()
        assert "custom_algo" in inspector.get_table_names()

        # Verify custom_algo has CASCADE from ORM model
        fks = inspector.get_foreign_keys("custom_algo")
        user_fk = [fk for fk in fks if "user_id" in fk.get("constrained_columns", [])]
        assert len(user_fk) == 1
        assert user_fk[0].get("options", {}).get("ondelete", "").upper() == "CASCADE"

        # Step 2: alembic upgrade head (should not crash)
        _run_upgrade_head(async_url)

        # Verify alembic_version is stamped
        inspector = sa_inspect(sync_engine)
        assert "alembic_version" in inspector.get_table_names()

        # Verify custom_algo still has all columns
        cols = {c["name"] for c in inspector.get_columns("custom_algo")}
        assert "id" in cols
        assert "node_type" in cols
        assert "mode" in cols

        sync_engine.dispose()


class TestBootstrapLegacyUntracked:
    """Scenario: tables exist (from old create_all) but no alembic_version."""

    def test_legacy_tables_then_upgrade_head(self, tmp_path):
        db_path = tmp_path / "legacy.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)

        # Simulate legacy DB: create tables via create_all, no alembic stamp
        sync_engine = sa.create_engine(sync_url)
        Base.metadata.create_all(sync_engine)

        # Verify no alembic_version
        inspector = sa_inspect(sync_engine)
        assert "alembic_version" not in inspector.get_table_names()

        # Run upgrade head — should succeed
        _run_upgrade_head(async_url)

        # Verify alembic_version is now stamped
        inspector = sa_inspect(sync_engine)
        assert "alembic_version" in inspector.get_table_names()

        # Verify custom_algo still intact with CASCADE
        fks = inspector.get_foreign_keys("custom_algo")
        user_fk = [fk for fk in fks if "user_id" in fk.get("constrained_columns", [])]
        assert len(user_fk) == 1
        assert user_fk[0].get("options", {}).get("ondelete", "").upper() == "CASCADE"

        sync_engine.dispose()


class TestBootstrapTracked:
    """Scenario: database already tracked by Alembic (upgrade from scratch)."""

    def test_upgrade_head_on_empty_db(self, tmp_path):
        db_path = tmp_path / "tracked.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)

        # Run upgrade head from scratch (no create_all first)
        _run_upgrade_head(async_url)

        # Verify tables and alembic_version
        sync_engine = sa.create_engine(sync_url)
        inspector = sa_inspect(sync_engine)
        assert "alembic_version" in inspector.get_table_names()
        assert "user" in inspector.get_table_names()
        assert "custom_algo" in inspector.get_table_names()

        # Verify custom_algo has CASCADE
        fks = inspector.get_foreign_keys("custom_algo")
        user_fk = [fk for fk in fks if "user_id" in fk.get("constrained_columns", [])]
        assert len(user_fk) == 1
        assert user_fk[0].get("options", {}).get("ondelete", "").upper() == "CASCADE"

        # Run upgrade head again — should be a no-op
        _run_upgrade_head(async_url)

        sync_engine.dispose()


class TestBootstrapLegacyWithOldCustomAlgo:
    """Scenario: legacy DB with custom_algo created without CASCADE on user_id."""

    def test_legacy_custom_algo_gets_cascade(self, tmp_path):
        db_path = tmp_path / "legacy_no_cascade.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)

        # Create minimal tables mimicking pre-CASCADE schema
        sync_engine = sa.create_engine(sync_url)
        with sync_engine.begin() as conn:
            conn.execute(
                text(
                    """
                CREATE TABLE "user" (
                    id INTEGER PRIMARY KEY,
                    username VARCHAR(100) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    is_superuser BOOLEAN DEFAULT 0,
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE TABLE project (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES "user"(id),
                    name VARCHAR(255) NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
                )
            )
            # custom_algo WITHOUT CASCADE on user_id
            conn.execute(
                text(
                    """
                CREATE TABLE custom_algo (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES "user"(id),
                    name VARCHAR(255) NOT NULL,
                    slug VARCHAR(255) NOT NULL,
                    description TEXT,
                    code TEXT NOT NULL,
                    mode VARCHAR(20) NOT NULL DEFAULT 'simple',
                    icon VARCHAR(10) NOT NULL DEFAULT '🧪',
                    node_type VARCHAR(255) NOT NULL UNIQUE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """
                )
            )

        # Verify no CASCADE on user_id
        inspector = sa_inspect(sync_engine)
        fks = inspector.get_foreign_keys("custom_algo")
        user_fk = [fk for fk in fks if "user_id" in fk.get("constrained_columns", [])]
        if user_fk:
            ondelete = user_fk[0].get("options", {}).get("ondelete", "")
            assert ondelete.upper() != "CASCADE"

        # Run upgrade head — l2g4h6i8j471 should rebuild the table
        _run_upgrade_head(async_url)

        # Verify CASCADE is now in place
        inspector = sa_inspect(sync_engine)
        fks = inspector.get_foreign_keys("custom_algo")
        user_fk = [fk for fk in fks if "user_id" in fk.get("constrained_columns", [])]
        assert len(user_fk) == 1
        assert user_fk[0].get("options", {}).get("ondelete", "").upper() == "CASCADE"

        sync_engine.dispose()
