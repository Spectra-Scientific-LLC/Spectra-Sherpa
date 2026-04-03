"""Validate init_db bootstrap paths: fresh, legacy-untracked, and tracked.

These tests create real temp SQLite databases and run the full Alembic
migration chain to verify that the three-path logic in init_db.py is safe.

The Alembic ``env.py`` reads its URL from ``settings.database_url``, so each
test monkeypatches that setting to point at the temp database.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from spectra_sherpa.app import models  # noqa: F401  # Ensure metadata is populated for create_all paths.
from spectra_sherpa.app.db.base import Base
from spectra_sherpa.app.models.user import User


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
    _run_upgrade(async_url, "head")


def _run_upgrade(async_url: str, revision: str) -> None:
    """Run alembic upgrade to a specific revision with settings overridden."""
    from spectra_sherpa.app.core.config import settings

    original = settings.database_url
    # Settings is frozen (Pydantic), so use object.__setattr__
    object.__setattr__(settings, "database_url", async_url)
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, revision)
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

        # Step 2: alembic upgrade head (should not crash)
        _run_upgrade_head(async_url)

        # Verify alembic_version is stamped
        inspector = sa_inspect(sync_engine)
        assert "alembic_version" in inspector.get_table_names()

        # custom_algo is dropped by migration a76d82a816bf
        assert "custom_algo" not in inspector.get_table_names()

        # Verify project_id FK on experiment has ondelete SET NULL
        # (added by q7r9s1t3u926)
        fks = inspector.get_foreign_keys("experiment")
        project_fk = [fk for fk in fks if "project_id" in fk.get("constrained_columns", [])]
        assert len(project_fk) == 1
        assert project_fk[0].get("options", {}).get("ondelete", "").upper() == "SET NULL"

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

        # custom_algo is dropped by migration a76d82a816bf
        assert "custom_algo" not in inspector.get_table_names()

        # Verify core tables survived
        assert "user" in inspector.get_table_names()
        assert "workflow" in inspector.get_table_names()
        assert "experiment" in inspector.get_table_names()

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

        # custom_algo is created then dropped during the migration chain
        assert "custom_algo" not in inspector.get_table_names()

        # Verify project_id FK on workflow has ondelete SET NULL
        fks = inspector.get_foreign_keys("workflow")
        project_fk = [fk for fk in fks if "project_id" in fk.get("constrained_columns", [])]
        assert len(project_fk) == 1
        assert project_fk[0].get("options", {}).get("ondelete", "").upper() == "SET NULL"

        # Run upgrade head again — should be a no-op
        _run_upgrade_head(async_url)

        sync_engine.dispose()


class TestBootstrapLegacyWithOldCustomAlgo:
    """Scenario: legacy DB with custom_algo created without CASCADE on user_id.

    After upgrade head, custom_algo should be dropped (migration a76d82a816bf).
    """

    def test_legacy_custom_algo_gets_dropped(self, tmp_path):
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

        # Verify custom_algo exists before migration
        inspector = sa_inspect(sync_engine)
        assert "custom_algo" in inspector.get_table_names()

        # Run upgrade head — a76d82a816bf should drop custom_algo
        _run_upgrade_head(async_url)

        # Verify custom_algo has been dropped
        inspector = sa_inspect(sync_engine)
        assert "custom_algo" not in inspector.get_table_names()

        sync_engine.dispose()


class TestTrackedLegacyAuthSplit:
    """Scenario: tracked DB still has the pre-split user.password_hash constraint."""

    def test_upgrade_head_unblocks_legacy_user_insert(self, tmp_path):
        db_path = tmp_path / "tracked_legacy_auth.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)

        sync_engine = sa.create_engine(sync_url)
        with sync_engine.begin() as conn:
            conn.execute(
                text(
                    """
                CREATE TABLE "user" (
                    id INTEGER PRIMARY KEY,
                    username VARCHAR(100) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    is_superuser BOOLEAN NOT NULL DEFAULT 0,
                    api_key_hash VARCHAR(255),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    email VARCHAR(255),
                    last_active DATETIME,
                    last_login_at DATETIME,
                    login_count INTEGER NOT NULL DEFAULT 0
                )
            """
                )
            )
            conn.execute(
                text(
                    """
                CREATE TABLE alembic_version (
                    version_num VARCHAR(32) NOT NULL PRIMARY KEY
                )
            """
                )
            )
            conn.execute(
                text(
                    """
                INSERT INTO alembic_version (version_num)
                VALUES ('r8s0t2u4v037')
            """
                )
            )

        with Session(sync_engine) as session:
            session.add(User(username="before-upgrade"))
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()

        _run_upgrade_head(async_url)

        inspector = sa_inspect(sync_engine)
        columns = {column["name"]: column for column in inspector.get_columns("user")}
        assert columns["password_hash"]["nullable"] is True
        assert columns["is_superuser"]["nullable"] is True
        assert columns["login_count"]["nullable"] is True
        assert columns["email"]["nullable"] is True

        with Session(sync_engine) as session:
            user = User(username="after-upgrade")
            session.add(user)
            session.flush()
            row = session.execute(
                text(
                    """
                    SELECT username, password_hash, is_superuser, login_count
                    FROM "user"
                    WHERE username = :username
                    """
                ),
                {"username": "after-upgrade"},
            ).mappings().one()
            assert row["username"] == "after-upgrade"
            assert row["password_hash"] is None
            assert row["is_superuser"] in (None, 0, False)
            assert row["login_count"] in (None, 0)
            session.rollback()

        sync_engine.dispose()


class TestLegacyAuthDefaults:
    """Validate the narrower production hotfix behavior directly."""

    def test_password_hash_relaxation_alone_unblocks_current_user_insert(self, tmp_path):
        db_path = tmp_path / "legacy_defaults.db"
        sync_engine = sa.create_engine(_sync_url(db_path))

        with sync_engine.begin() as conn:
            conn.execute(
                text(
                    """
                CREATE TABLE "user" (
                    id INTEGER PRIMARY KEY,
                    username VARCHAR(100) NOT NULL UNIQUE,
                    password_hash VARCHAR(255),
                    is_superuser BOOLEAN NOT NULL DEFAULT 0,
                    api_key_hash VARCHAR(255),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    email VARCHAR(255),
                    last_active DATETIME,
                    last_login_at DATETIME,
                    login_count INTEGER NOT NULL DEFAULT 0
                )
            """
                )
            )

        with Session(sync_engine) as session:
            session.add(User(username="password-hash-only"))
            session.flush()
            row = session.execute(
                text(
                    """
                    SELECT password_hash, is_superuser, login_count
                    FROM "user"
                    WHERE username = :username
                    """
                ),
                {"username": "password-hash-only"},
            ).mappings().one()
            assert row["password_hash"] is None
            assert row["is_superuser"] == 0
            assert row["login_count"] == 0
            session.rollback()

        sync_engine.dispose()
