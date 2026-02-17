from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from spectra_sherpa.app.core.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

# Build engine kwargs conditionally per database driver
_engine_kwargs: dict = {"pool_pre_ping": True}

if _is_sqlite:
    # check_same_thread is SQLite-only (aiosqlite)
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # PostgreSQL: configure connection pool for production
    _engine_kwargs["pool_size"] = 10
    _engine_kwargs["max_overflow"] = 20

engine = create_async_engine(settings.database_url, **_engine_kwargs)


if _is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA cache_size=-64000")
        cursor.execute("PRAGMA wal_autocheckpoint=1000")
        cursor.execute("PRAGMA journal_size_limit=67108864")
        cursor.close()


async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Backward-compatible session dependency for tests and legacy imports.

    Newer code paths use ``app.api.deps.get_session`` directly, but keeping this
    here avoids import breakage in test fixtures and older modules.
    """
    async with async_session() as session:
        yield session
