"""Pytest configuration and shared fixtures"""

from __future__ import annotations

import os
import shutil
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


_TEST_APP_DATA_ROOT: Path | None = None


@pytest.fixture
def monorepo_root() -> Path:
    """Scope private repository contracts without hiding missing evidence there."""
    package_root = Path(__file__).resolve().parents[1]
    root = package_root.parents[1]
    if root / "packages" / "spectra-sherpa" != package_root:
        pytest.skip("This contract checks monorepo-only workflows or retained evidence")
    return root


def _verify_environment_provenance() -> None:
    """Fail immediately if tests would run against the wrong worktree's source.

    A shared interpreter/environment (e.g. one conda env reused across many
    git worktrees) can silently resolve ``import spectra_sherpa`` to a
    DIFFERENT worktree's source than the one pytest was invoked from, if
    that worktree's editable install happens to win dependency resolution.
    Every result from a run like that is meaningless: it tested code you
    were not looking at, and the failure is invisible unless someone checks
    ``spectra_sherpa.__file__`` by hand. This corrupted a real evidence
    regeneration run and cost real debugging time before the trap was
    caught; it should never require a human to notice it again. See
    manifest.md, "Machine gates enforce what review bandwidth cannot."
    """
    worktree_src = (Path(__file__).resolve().parents[1] / "src").resolve()
    import spectra_sherpa

    imported_path = Path(spectra_sherpa.__file__).resolve()
    try:
        imported_path.relative_to(worktree_src)
    except ValueError:
        raise RuntimeError(
            "Environment provenance check failed.\n"
            f"  This test session's conftest.py lives under: {worktree_src}\n"
            f"  But `import spectra_sherpa` resolved to:      {imported_path}\n"
            "  These are different checkouts. Every test result from this run "
            "would silently test the WRONG code.\n"
            f"  Fix: run with PYTHONPATH={worktree_src} explicitly, or run "
            "`poetry install` inside this worktree so its own editable "
            "install wins, then re-run."
        ) from None


_verify_environment_provenance()


def _configure_writable_runtime_dirs() -> None:
    """Force third-party runtime state into writable temp directories.

    SpectroChemPy writes config files (for example, ``PCA.json`` and
    ``PlotPreferences.json``). In sandboxed or locked-down environments,
    user home directories may be read-only and cause unrelated test failures.
    """

    global _TEST_APP_DATA_ROOT

    runtime_root = Path(tempfile.mkdtemp(prefix="spectra-sherpa-pytest-")).resolve()
    scp_config = runtime_root / "scp-config"
    scp_projects = runtime_root / "scp-projects"
    mpl_config = runtime_root / "mplconfig"
    app_data = runtime_root / "app-data"
    _TEST_APP_DATA_ROOT = app_data

    for path in (scp_config, scp_projects, mpl_config, app_data):
        path.mkdir(parents=True, exist_ok=True)

    os.environ["DATA_DIR"] = str(app_data)
    # Another package may have imported the frozen singleton during collection.
    # Its storage must follow the same root that the isolation fixture cleans.
    from spectra_sherpa.app.core.config import settings

    object.__setattr__(settings, "data_dir", app_data)
    os.environ["SCP_CONFIG_HOME"] = str(scp_config)
    os.environ["SCP_PROJECTS_HOME"] = str(scp_projects)
    os.environ["MPLCONFIGDIR"] = str(mpl_config)


_configure_writable_runtime_dirs()


@pytest.fixture(autouse=True)
def _isolate_experiment_storage_between_tests():
    """A fresh in-memory database must never inherit another test's durable files."""

    assert _TEST_APP_DATA_ROOT is not None
    from spectra_sherpa.app.core.config import settings

    object.__setattr__(settings, "data_dir", _TEST_APP_DATA_ROOT)
    experiments = _TEST_APP_DATA_ROOT / "experiments"
    shutil.rmtree(experiments, ignore_errors=True)
    yield
    shutil.rmtree(experiments, ignore_errors=True)


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
    user = User(username="testuser")
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


@pytest.fixture(autouse=True, scope="session")
def _init_model_store_for_tests(tmp_path_factory) -> None:
    """Ensure ModelStore is initialised so training nodes can persist artifacts."""
    from spectra_sherpa.app.services.model_store import init_model_store

    base = tmp_path_factory.mktemp("model_store")
    init_model_store(base)


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


@pytest.fixture
def patch_eigenvector_loader(monkeypatch: pytest.MonkeyPatch):
    """Route Eigenvector execution tests to generated non-upstream fixtures."""
    from tests.eigenvector_test_fixtures import generated_eigenvector_result

    monkeypatch.setattr(
        "spectra_sherpa.app.lib.eigenvector.load_eigenvector_dataset",
        generated_eigenvector_result,
    )
    return generated_eigenvector_result


@pytest.fixture
def deployment_artifact_factory(test_session, monkeypatch):
    """Real owned artifact/version records; storage verification is isolated here."""
    from uuid import uuid4

    from spectra_sherpa.app.models.model_artifact import ModelArtifact
    from spectra_sherpa.app.models.workflow_version import WorkflowVersion
    from spectra_sherpa.app.services import deployment_binding

    monkeypatch.setattr(deployment_binding, "verify_model_artifact_storage_record", lambda artifact: None)

    async def create(workflow):
        version = WorkflowVersion(
            workflow_id=workflow.id,
            version_number=1,
            created_by=workflow.user_id,
            snapshot={"nodes": [], "edges": []},
        )
        test_session.add(version)
        await test_session.flush()
        artifact = ModelArtifact(
            artifact_uid=str(uuid4()),
            user_id=workflow.user_id,
            workflow_id=workflow.id,
            workflow_version_id=version.id,
            project_id=workflow.project_id,
            node_id="model",
            model_type="pls",
            name="Reviewed model",
            artifact_dir="test-artifact",
            integrity_hash="a" * 64,
            n_features=2,
            is_active=True,
            is_deploy_ready=True,
        )
        test_session.add(artifact)
        await test_session.flush()
        return artifact

    return create


@pytest.fixture
def deny_inference_network(monkeypatch):
    """Deny inference connections while allowing the stdlib's Windows socketpair.

    Windows asyncio creates its wake-up socketpair with a temporary loopback
    listener. Only connections made inside that standard-library constructor
    may use loopback; application connections (including loopback) still fail.
    """
    import contextvars
    import ipaddress
    import socket

    constructing_pair = contextvars.ContextVar("constructing_local_socketpair", default=False)
    real_pair = socket.socketpair
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def pair(*args, **kwargs):
        token = constructing_pair.set(True)
        try:
            return real_pair(*args, **kwargs)
        finally:
            constructing_pair.reset(token)

    def guard(method):
        def connect(sock, address):
            if constructing_pair.get() and isinstance(address, tuple):
                try:
                    if ipaddress.ip_address(address[0]).is_loopback:
                        return method(sock, address)
                except ValueError:
                    pass
            raise AssertionError("Offline inference must not open application network connections")

        return connect

    monkeypatch.setattr(socket, "socketpair", pair)
    monkeypatch.setattr(socket.socket, "connect", guard(real_connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guard(real_connect_ex))
