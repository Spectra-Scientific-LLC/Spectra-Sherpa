"""Pytest configuration and shared fixtures"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

def _configure_writable_runtime_dirs() -> None:
    """Force third-party runtime state into writable temp directories.

    SpectroChemPy writes config files (for example, ``PCA.json`` and
    ``PlotPreferences.json``). In sandboxed or locked-down environments,
    user home directories may be read-only and cause unrelated test failures.
    """

    runtime_root = Path(tempfile.mkdtemp(prefix="spectra-sherpa-pytest-"))
    scp_config = runtime_root / "scp-config"
    scp_projects = runtime_root / "scp-projects"
    mpl_config = runtime_root / "mplconfig"

    for path in (scp_config, scp_projects, mpl_config):
        path.mkdir(parents=True, exist_ok=True)

    os.environ["SCP_CONFIG_HOME"] = str(scp_config)
    os.environ["SCP_PROJECTS_HOME"] = str(scp_projects)
    os.environ["MPLCONFIGDIR"] = str(mpl_config)


_configure_writable_runtime_dirs()

from app.db.base import Base
from app.api.deps import get_session
from app.main import app
from app.models.user import User


@pytest.fixture
async def test_engine():
    """Create a test database engine"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session"""
    async_session = sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        yield session


@pytest.fixture
async def test_user(test_session: AsyncSession) -> User:
    """Create a test user"""
    user = User(username="testuser", password_hash="testhash")
    test_session.add(user)
    await test_session.commit()
    await test_session.refresh(user)
    return user


@pytest.fixture
async def client(test_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create a test HTTP client"""

    async def override_get_session():
        yield test_session

    app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
