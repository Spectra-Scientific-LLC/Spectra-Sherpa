"""Pytest configuration and shared fixtures"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

if TYPE_CHECKING:
    from spectra_sherpa.app.models.user import User


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

# SpectroChemPy's logging interferes with pytest's capture mechanism, causing
# "ValueError: I/O operation on closed file" when printing to stdout/stderr.
# We disable its console logging here before it gets imported by the app.
import logging

# Force-configure the logger before import to prevent handler attachment
logging.getLogger("spectrochempy").handlers = []
logging.getLogger("spectrochempy").propagate = False
# Also silence the root logger for good measure during tests
logging.getLogger().setLevel(logging.CRITICAL)

from starlette.testclient import TestClient


def _get_app():
    """Import the FastAPI app lazily.

    Importing ``spectra_sherpa.app.main`` pulls in the full router graph,
    which in turn imports optional SpectroChemPy-backed modules. Keeping this
    lazy avoids that startup cost for tests that never touch the HTTP app.
    """
    from spectra_sherpa.app.main import app

    return app


def _get_test_deps():
    from spectra_sherpa.app.api.deps import get_current_user, get_session

    return get_current_user, get_session


def _get_base():
    # Import models before metadata creation so SQLAlchemy registers tables.
    import spectra_sherpa.app.models  # noqa: F401
    from spectra_sherpa.app.db.base import Base

    return Base


def _get_user_model():
    from spectra_sherpa.app.models.user import User

    return User


@pytest.fixture
async def test_engine():
    """Create a test database engine"""
    Base = _get_base()
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
    async_session = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        yield session


@pytest.fixture
async def test_user(test_session: AsyncSession) -> User:
    """Create a test user"""
    User = _get_user_model()
    user = User(username="testuser", password_hash="testhash")
    test_session.add(user)
    await test_session.commit()
    await test_session.refresh(user)
    return user


@pytest.fixture
async def client(test_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create a test HTTP client"""
    app = _get_app()
    _, get_session = _get_test_deps()

    async def override_get_session():
        yield test_session

    app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def auth_client(test_session: AsyncSession, test_user: User) -> AsyncGenerator[AsyncClient, None]:
    """HTTP client authenticated as test_user."""
    app = _get_app()
    get_current_user, get_session = _get_test_deps()

    async def override_get_session():
        yield test_session

    async def override_get_current_user():
        return test_user

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_current_user] = override_get_current_user

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def swap_user(test_session: AsyncSession):
    """Context helper to temporarily swap the authenticated user for ownership tests."""
    app = _get_app()
    get_current_user, get_session = _get_test_deps()

    class _Swapper:
        def __call__(self, user: User):
            async def override_get_session():
                yield test_session

            async def override_get_current_user():
                return user

            app.dependency_overrides[get_session] = override_get_session
            app.dependency_overrides[get_current_user] = override_get_current_user

    return _Swapper()


@pytest.fixture
def ws_client():
    """Synchronous TestClient for WebSocket testing."""
    app = _get_app()
    tc = TestClient(app)
    try:
        yield tc
    finally:
        tc.close()


@pytest.fixture(autouse=True)
def reset_rate_limiter_state() -> None:
    """Reset file-backed limiter state between tests to avoid flaky 429s.

    Rate limiters persist counters to JSON files under ``settings.data_dir``.
    Without cleanup, repeated runs can inherit prior state from manual
    development sessions or earlier tests.
    """
    from spectra_sherpa.app.core.config import settings

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "auth_rate_login",
        "auth_rate_register",
        "execution_rate_limits",
    ):
        (settings.data_dir / f"{name}.json").write_text("{}")

    yield
