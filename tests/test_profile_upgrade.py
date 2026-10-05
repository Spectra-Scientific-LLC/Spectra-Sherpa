"""Real SQLite recovery tests, including pages retained exclusively in WAL."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

from spectra_sherpa._paths import get_package_root
from spectra_sherpa.app.db import profile_upgrade as recovery
from spectra_sherpa.app.db.sqlite_migration import migration_transaction


@pytest.fixture
def scripts():
    cfg = Config()
    cfg.set_main_option("script_location", str(get_package_root() / "alembic"))
    return ScriptDirectory.from_config(cfg)


@pytest.fixture
def profile(tmp_path):
    path = tmp_path / "spectra_platform.db"
    writer = sqlite3.connect(path)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("CREATE TABLE retained (value TEXT)")
    writer.execute("INSERT INTO retained VALUES ('committed in WAL')")
    writer.commit()
    engine = sa.create_engine(f"sqlite:///{path}")
    yield path, engine, writer
    engine.dispose()
    writer.close()


def test_backup_includes_wal_and_restore_never_overwrites(profile, scripts, tmp_path):
    path, engine, _ = profile
    assert Path(str(path) + "-wal").stat().st_size > 0
    with engine.connect() as conn:
        with migration_transaction(conn):
            snapshot = recovery.prepare_profile_upgrade(conn, scripts)
            conn.exec_driver_sql("UPDATE retained SET value='upgraded'")
    assert snapshot is not None
    restored = recovery.restore_database_copy(snapshot, tmp_path / "restored.db")
    with closing(sqlite3.connect(restored)) as database:
        assert database.execute("SELECT value FROM retained").fetchone() == ("committed in WAL",)
    with pytest.raises(FileExistsError):
        recovery.restore_database_copy(snapshot, path)
    with closing(sqlite3.connect(path)) as database:
        assert database.execute("SELECT value FROM retained").fetchone() == ("upgraded",)
    manifest = json.loads((snapshot / "manifest.json").read_text())
    assert manifest["target_revisions"] == scripts.get_heads()
    assert manifest["database"]["sha256"] == recovery._digest(restored)


def test_insufficient_space_refuses_before_mutation(profile, scripts, monkeypatch):
    path, engine, _ = profile
    monkeypatch.setattr(recovery.shutil, "disk_usage", lambda _: SimpleNamespace(free=0))
    with engine.connect() as conn, pytest.raises(recovery.ProfileUpgradeError, match="insufficient_space"):
        with migration_transaction(conn):
            recovery.prepare_profile_upgrade(conn, scripts)
            pytest.fail("migration must not start")
    assert not (path.parent / ".profile-upgrades").exists()
    with closing(sqlite3.connect(path)) as database:
        assert database.execute("SELECT value FROM retained").fetchone() == ("committed in WAL",)


def test_newer_database_is_refused_without_backup_or_schema_change(profile, scripts):
    path, engine, writer = profile
    writer.execute("CREATE TABLE alembic_version (version_num TEXT)")
    writer.execute("INSERT INTO alembic_version VALUES ('future-release')")
    writer.commit()
    with engine.connect() as conn, pytest.raises(recovery.ProfileUpgradeError, match="schema_incompatible"):
        with migration_transaction(conn):
            recovery.prepare_profile_upgrade(conn, scripts)
    assert not (path.parent / ".profile-upgrades").exists()
    assert writer.execute("SELECT version_num FROM alembic_version").fetchone() == ("future-release",)


def test_interruption_preserves_backup_and_rolls_back_then_retry_retains_both(profile, scripts):
    path, engine, _ = profile
    with engine.connect() as conn:
        with pytest.raises(KeyboardInterrupt):
            with migration_transaction(conn):
                first = recovery.prepare_profile_upgrade(conn, scripts)
                conn.exec_driver_sql("DROP TABLE retained")
                raise KeyboardInterrupt()
        with migration_transaction(conn):
            second = recovery.prepare_profile_upgrade(conn, scripts)
        assert first != second
        assert first.is_dir() and second.is_dir()
        assert conn.exec_driver_sql("SELECT value FROM retained").scalar_one() == "committed in WAL"


def test_corrupted_backup_refuses_restore(profile, scripts, tmp_path):
    _, engine, _ = profile
    with engine.connect() as conn, migration_transaction(conn):
        snapshot = recovery.prepare_profile_upgrade(conn, scripts)
    (snapshot / "database.sqlite3").write_bytes(b"damaged")
    destination = tmp_path / "restored.db"
    with pytest.raises(recovery.ProfileUpgradeError, match="backup_invalid"):
        recovery.restore_database_copy(snapshot, destination)
    assert not destination.exists()


def test_current_revision_does_not_make_repeated_backups(profile, scripts):
    path, engine, writer = profile
    writer.execute("CREATE TABLE alembic_version (version_num TEXT)")
    writer.executemany("INSERT INTO alembic_version VALUES (?)", [(head,) for head in scripts.get_heads()])
    writer.commit()
    with engine.connect() as conn, migration_transaction(conn):
        assert recovery.prepare_profile_upgrade(conn, scripts) is None
    assert not (path.parent / ".profile-upgrades").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_bootstrap", [False, True])
async def test_application_bootstrap_is_atomic(tmp_path, monkeypatch, fail_bootstrap):
    from dataclasses import replace

    from sqlalchemy.ext.asyncio import create_async_engine

    from spectra_sherpa.app.core import config
    from spectra_sherpa.app.db import init_db
    from spectra_sherpa.app.db.base import Base

    path = tmp_path / "fresh.db"
    url = f"sqlite+aiosqlite:///{path}"
    engine = create_async_engine(url)
    monkeypatch.setattr(init_db, "engine", engine)
    monkeypatch.setattr(config, "settings", replace(config.settings, database_url=url))
    monkeypatch.setattr(config.app_config, "mode", "local")
    if fail_bootstrap:
        original = Base.metadata.create_all

        def interrupted(connection):
            original(connection)
            raise RuntimeError("bootstrap interrupted")

        monkeypatch.setattr(Base.metadata, "create_all", interrupted)
        with pytest.raises(RuntimeError, match="bootstrap interrupted"):
            await init_db.init_db()
    else:
        await init_db.init_db()
    await engine.dispose()
    with closing(sqlite3.connect(path)) as database:
        tables = {row[0] for row in database.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if fail_bootstrap:
            assert not tables
        else:
            assert {"user", "workflow", "alembic_version"} <= tables
    assert not (tmp_path / ".profile-upgrades").exists()


def test_writer_is_quiesced_until_backup_and_migration_complete(profile, scripts):
    path, engine, _ = profile
    with engine.connect() as conn, migration_transaction(conn):
        recovery.prepare_profile_upgrade(conn, scripts)
        with closing(sqlite3.connect(path, timeout=0.01)) as contender:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                contender.execute("UPDATE retained SET value='competing writer'")
    with closing(sqlite3.connect(path)) as contender:
        contender.execute("UPDATE retained SET value='writer resumed'")


def test_abrupt_process_exit_recovers_original_database_and_snapshot(profile, tmp_path):
    import os
    import subprocess
    import sys

    path, _, _ = profile
    script = """
import os, sys
import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory
from spectra_sherpa._paths import get_package_root
from spectra_sherpa.app.db.profile_upgrade import prepare_profile_upgrade
from spectra_sherpa.app.db.sqlite_migration import migration_transaction
cfg = Config()
cfg.set_main_option('script_location', str(get_package_root() / 'alembic'))
engine = sa.create_engine('sqlite:///' + sys.argv[1])
with engine.connect() as conn, migration_transaction(conn):
    prepare_profile_upgrade(conn, ScriptDirectory.from_config(cfg))
    conn.exec_driver_sql('DROP TABLE retained')
    os._exit(7)
"""
    result = subprocess.run([sys.executable, "-c", script, str(path)], env=os.environ.copy(), timeout=30)
    assert result.returncode == 7
    with closing(sqlite3.connect(path)) as database:
        assert database.execute("SELECT value FROM retained").fetchone() == ("committed in WAL",)
    snapshots = list((tmp_path / ".profile-upgrades").iterdir())
    assert len(snapshots) == 1
    recovery.restore_database_copy(snapshots[0], tmp_path / "after-crash.db")


@pytest.mark.parametrize("corrupt", [False, True])
def test_integrity_verifier_closes_handle_on_success_and_error(tmp_path, monkeypatch, corrupt):
    path = tmp_path / "verify.db"
    if corrupt:
        path.write_bytes(b"invalid sqlite database")
    else:
        with closing(sqlite3.connect(path)) as database:
            database.execute("CREATE TABLE evidence (value TEXT)")
    original = sqlite3.connect
    opened = []

    def tracked(*args, **kwargs):
        connection = original(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(recovery.sqlite3, "connect", tracked)
    if corrupt:
        with pytest.raises(sqlite3.DatabaseError):
            recovery._verify_database(path)
    else:
        recovery._verify_database(path)
    assert opened
    for connection in opened:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    path.unlink()  # Also exercises Windows file deletion after verification.


def test_backup_closes_all_source_destination_and_restore_handles(profile, scripts, monkeypatch):
    _, engine, _ = profile
    original = sqlite3.connect
    opened = []

    def tracked(*args, **kwargs):
        connection = original(*args, **kwargs)
        opened.append(connection)
        return connection

    with engine.connect() as conn, migration_transaction(conn):
        monkeypatch.setattr(recovery.sqlite3, "connect", tracked)
        recovery.prepare_profile_upgrade(conn, scripts)
        assert len(opened) >= 5
        for connection in opened:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                connection.execute("SELECT 1")
