"""Unit tests for ``_ensure_postgres_database_exists``.

Validates the defensive auto-create of the target Postgres database on
boot when the data volume was initialised under a different DB name (the
``InvalidCatalogNameError`` failure mode hit on staging after #168).

``asyncpg`` is a server-side dependency and may not be installed in the
OSS test environment, so the tests stub it into ``sys.modules`` rather
than importing it.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _install_fake_asyncpg(connection):
    """Insert a stub ``asyncpg`` module exposing ``connect`` -> ``connection``."""
    module = types.ModuleType("asyncpg")
    module.connect = AsyncMock(return_value=connection)  # type: ignore[attr-defined]
    sys.modules["asyncpg"] = module
    return module


@pytest.fixture
def fake_connection():
    conn = MagicMock()
    conn.fetchval = AsyncMock()
    conn.execute = AsyncMock()
    conn.close = AsyncMock()
    return conn


@pytest.fixture
def fake_asyncpg(fake_connection, monkeypatch):
    previous = sys.modules.get("asyncpg")
    module = _install_fake_asyncpg(fake_connection)
    yield module
    if previous is None:
        sys.modules.pop("asyncpg", None)
    else:
        sys.modules["asyncpg"] = previous


def _patched_engine(url_obj):
    eng = MagicMock()
    eng.url = url_obj
    return eng


@pytest.mark.asyncio
async def test_skips_sqlite() -> None:
    from sqlalchemy.engine import make_url

    from spectra_sherpa.app.db import init_db as init_db_module

    fake = _patched_engine(make_url("sqlite+aiosqlite:///:memory:"))
    sentinel_connect = AsyncMock()
    stub = types.ModuleType("asyncpg")
    stub.connect = sentinel_connect  # type: ignore[attr-defined]
    with patch.object(init_db_module, "engine", fake), patch.dict(sys.modules, {"asyncpg": stub}):
        await init_db_module._ensure_postgres_database_exists()
    sentinel_connect.assert_not_called()


@pytest.mark.asyncio
async def test_skips_when_target_is_postgres_admin_db() -> None:
    from sqlalchemy.engine import make_url

    from spectra_sherpa.app.db import init_db as init_db_module

    fake = _patched_engine(make_url("postgresql+asyncpg://u:p@h:5432/postgres"))
    sentinel_connect = AsyncMock()
    stub = types.ModuleType("asyncpg")
    stub.connect = sentinel_connect  # type: ignore[attr-defined]
    with patch.object(init_db_module, "engine", fake), patch.dict(sys.modules, {"asyncpg": stub}):
        await init_db_module._ensure_postgres_database_exists()
    sentinel_connect.assert_not_called()


@pytest.mark.asyncio
async def test_noop_when_database_already_exists(fake_asyncpg, fake_connection) -> None:
    from sqlalchemy.engine import make_url

    from spectra_sherpa.app.db import init_db as init_db_module

    fake_connection.fetchval.return_value = 1  # pg_database row found

    fake = _patched_engine(make_url("postgresql+asyncpg://u:p@h:5432/spectra_staging"))
    with patch.object(init_db_module, "engine", fake):
        await init_db_module._ensure_postgres_database_exists()

    fake_asyncpg.connect.assert_awaited_once_with(host="h", port=5432, user="u", password="p", database="postgres")
    fake_connection.fetchval.assert_awaited_once()
    fake_connection.execute.assert_not_awaited()
    fake_connection.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_creates_database_when_missing(fake_asyncpg, fake_connection) -> None:
    from sqlalchemy.engine import make_url

    from spectra_sherpa.app.db import init_db as init_db_module

    fake_connection.fetchval.return_value = None  # DB not found

    fake = _patched_engine(make_url("postgresql+asyncpg://u:p@h/spectra_staging"))
    with patch.object(init_db_module, "engine", fake):
        await init_db_module._ensure_postgres_database_exists()

    fake_connection.execute.assert_awaited_once()
    sql = fake_connection.execute.await_args.args[0]
    assert sql == 'CREATE DATABASE "spectra_staging"'
    fake_connection.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_quotes_database_name_with_embedded_quote(fake_asyncpg, fake_connection) -> None:
    from sqlalchemy.engine import make_url

    from spectra_sherpa.app.db import init_db as init_db_module

    fake_connection.fetchval.return_value = None

    fake = _patched_engine(make_url('postgresql+asyncpg://u:p@h/weird"name'))
    with patch.object(init_db_module, "engine", fake):
        await init_db_module._ensure_postgres_database_exists()

    sql = fake_connection.execute.await_args.args[0]
    assert sql == 'CREATE DATABASE "weird""name"'


@pytest.mark.asyncio
async def test_swallows_admin_connection_failure() -> None:
    from sqlalchemy.engine import make_url

    from spectra_sherpa.app.db import init_db as init_db_module

    fake = _patched_engine(make_url("postgresql+asyncpg://u:p@h/spectra_staging"))
    failing_connect = AsyncMock(side_effect=ConnectionRefusedError("nope"))
    stub = types.ModuleType("asyncpg")
    stub.connect = failing_connect  # type: ignore[attr-defined]
    with patch.object(init_db_module, "engine", fake), patch.dict(sys.modules, {"asyncpg": stub}):
        # Should log and return — not raise — so init_db's later engine.connect()
        # surfaces the real failure with its own clearer error.
        await init_db_module._ensure_postgres_database_exists()


@pytest.mark.asyncio
async def test_skips_when_asyncpg_missing() -> None:
    from sqlalchemy.engine import make_url

    from spectra_sherpa.app.db import init_db as init_db_module

    fake = _patched_engine(make_url("postgresql+asyncpg://u:p@h/spectra_staging"))
    # Simulate asyncpg not installed (e.g. SQLite-only dev environment) — the
    # helper must log + skip rather than raise.
    previous = sys.modules.pop("asyncpg", None)
    try:
        with patch.object(init_db_module, "engine", fake):
            await init_db_module._ensure_postgres_database_exists()
    finally:
        if previous is not None:
            sys.modules["asyncpg"] = previous
