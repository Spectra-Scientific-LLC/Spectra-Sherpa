"""Explicit fixture plugin for copied tests against wheel installations.

The ordinary conftest enforces checkout provenance and is never disabled or
rewritten. Installed qualification copies this plugin and selected tests to an
isolated directory, verifies their committed bytes, and loads it with ``-p``.
"""

import sys
from pathlib import Path

import pytest
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest.fixture(scope="session", autouse=True)
def installed_pack_runtime(tmp_path_factory):
    import spectra_sherpa
    from spectra_sherpa.app.services.model_store import init_model_store

    module = Path(spectra_sherpa.__file__).resolve()
    assert module.is_relative_to(Path(sys.prefix).resolve()), "Qualification must use the installed wheel"
    assert "site-packages" in module.parts
    init_model_store(tmp_path_factory.mktemp("installed-models"))


@pytest.fixture
async def test_session():
    import spectra_sherpa.app.models  # noqa: F401
    from spectra_sherpa.app.db.base import Base

    # Keep SQLite DDL bookkeeping isolated from separately collected PostgreSQL
    # concurrency fixtures that share the imported model metadata.
    metadata = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(metadata)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()


@pytest.fixture
async def test_user(test_session):
    from spectra_sherpa.app.models.user import User

    user = User(username="installed-pack-user")
    test_session.add(user)
    await test_session.commit()
    return user
