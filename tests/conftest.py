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

# SpectroChemPy's logging interferes with pytest's capture mechanism, causing
# "ValueError: I/O operation on closed file" when printing to stdout/stderr.
# We disable its console logging here before it gets imported by the app.
import logging
import subprocess
from unittest.mock import patch

# Force-configure the logger before import to prevent handler attachment
logging.getLogger("spectrochempy").handlers = []
logging.getLogger("spectrochempy").propagate = False
# Also silence the root logger for good measure during tests
logging.getLogger().setLevel(logging.CRITICAL)

# Prevent matplotlib.font_manager (loaded by spectrochempy) from hanging on macOS
# when it calls `system_profiler -xml SPFontsDataType` within pytest's captured environment.
_original_check_output = subprocess.check_output

def _mock_check_output(*args, **kwargs):
    if args and isinstance(args[0], list) and args[0][:2] == ["system_profiler", "-xml"]:
        # Return valid empty plist XML to short-circuit macOS font discovery
        # Matplotlib's font_manager extracts: d, = plistlib.loads(...)
        # So it needs a root array containing one dictionary.
        return b"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<array>
<dict>
<key>_name</key><string>Fonts</string>
<key>_items</key><array></array>
</dict>
</array>
</plist>"""
    return _original_check_output(*args, **kwargs)

with patch("subprocess.check_output", side_effect=_mock_check_output):
    from spectra_sherpa.app.api.deps import get_session
    from spectra_sherpa.app.db.base import Base
    from spectra_sherpa.app.main import app
    from spectra_sherpa.app.models.user import User

from spectra_sherpa.app.api.deps import get_session
from spectra_sherpa.app.db.base import Base
from spectra_sherpa.app.main import app
from spectra_sherpa.app.models.user import User


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
    async_session = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)

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

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def reset_rate_limiter_state() -> None:
    """Reset file-backed limiter state between tests to avoid flaky 429s.

    Rate limiters persist counters to JSON files under ``settings.data_dir``.
    Without cleanup, repeated runs can inherit prior state from manual
    development sessions or earlier tests.
    """
    from spectra_sherpa.app.core.config import settings
    from spectra_sherpa.app.core.demo_limits import reset_limiters

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "auth_rate_login",
        "auth_rate_register",
        "execution_rate_limits",
        "demo_execution_limits",
        "demo_sherpa_limits",
    ):
        (settings.data_dir / f"{name}.json").write_text("{}")

    # demo_limits caches file-backed limiters; clear cached instances.
    reset_limiters()
    yield
    reset_limiters()
