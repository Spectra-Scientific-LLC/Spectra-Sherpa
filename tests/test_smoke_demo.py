"""
Demo release-gate smoke suite.

Validates core surfaces that a deployment must expose:
  1. GET  /auth/me             (all distributions)
  2. POST /auth/register       (server distribution only)
  3. POST /auth/login          (server distribution only)
  4. POST /workflows/{id}/execute  (workflow execution round-trip)
  5. WebSocket /ws roundtrip   (subscribe + receive ack)

Run modes:
  - In-process (default):  ASGI transport + in-memory SQLite.
  - Against live server:   set SMOKE_BASE_URL=https://your-domain.com

Markers:
  @pytest.mark.smoke            — all tests in this module
  @pytest.mark.server_only      — skipped when running the OSS distribution
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import StaticPool
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

from spectra_sherpa.app.db.base import Base
from spectra_sherpa.app.main import app
from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.api.deps import get_session, get_current_user
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_node import WorkflowNode
import spectra_sherpa.app.main as app_main
from spectra_sherpa.app.services.websocket_manager import ws_manager


# ---------------------------------------------------------------------------
# Detect if full auth routes exist (server distribution)
# ---------------------------------------------------------------------------
try:
    from spectra_sherpa.app.api.v1.routes.auth import router as _auth_router  # noqa: F401

    _HAS_SERVER_AUTH = True
except ImportError:
    _HAS_SERVER_AUTH = False

_SMOKE_BASE_URL = os.environ.get("SMOKE_BASE_URL")

pytestmark = pytest.mark.smoke

server_only = pytest.mark.skipif(
    not _HAS_SERVER_AUTH, reason="Server-only auth routes not available (OSS distribution)"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
async def smoke_engine():
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
async def smoke_session(smoke_engine) -> AsyncSession:
    factory = sessionmaker(smoke_engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def smoke_user(smoke_session: AsyncSession) -> User:
    user = User(username="smoke_user", password_hash="nologin")
    smoke_session.add(user)
    await smoke_session.commit()
    await smoke_session.refresh(user)
    return user


@pytest.fixture
async def auth_client(
    smoke_session: AsyncSession, smoke_user: User
) -> AsyncClient:
    """HTTP client authenticated as smoke_user."""
    # Guard against test-ordering contamination: ensure local mode so the
    # api_key_middleware does not reject requests before dependency overrides
    # take effect.
    original_mode = app_config.mode
    app_config.mode = "local"

    async def override_get_session():
        yield smoke_session

    async def override_get_current_user():
        return smoke_user

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_current_user] = override_get_current_user

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    app_config.mode = original_mode


@pytest.fixture
def ws_client():
    """Sync TestClient for WebSocket tests."""
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture(autouse=True)
def _reset_ws_state():
    ws_manager._channels.clear()
    yield
    ws_manager._channels.clear()



# ---------------------------------------------------------------------------
# 1. GET /auth/me
# ---------------------------------------------------------------------------
class TestAuthMe:
    async def test_auth_me_returns_user(self, auth_client: AsyncClient, smoke_user: User):
        resp = await auth_client.get("/api/v1/auth/me")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        assert resp.text, f"Empty response body (status={resp.status_code})"
        data = resp.json()
        assert data["username"] == smoke_user.username
        assert "id" in data


# ---------------------------------------------------------------------------
# 2. POST /auth/register  (server-only)
# ---------------------------------------------------------------------------
class TestAuthRegister:
    @server_only
    async def test_register_creates_user(self, auth_client: AsyncClient):
        resp = await auth_client.post(
            "/api/v1/auth/register",
            json={"username": "newuser", "password": "securepassword123"},
        )
        assert resp.status_code in (200, 201)
        data = resp.json()
        assert data["username"] == "newuser"

    async def test_register_not_found_oss(self, auth_client: AsyncClient):
        """In OSS distribution, /auth/register should not exist."""
        if _HAS_SERVER_AUTH:
            pytest.skip("Server auth routes installed")
        resp = await auth_client.post(
            "/api/v1/auth/register",
            json={"username": "newuser", "password": "securepassword123"},
        )
        # FastAPI returns 405 Method Not Allowed or 404 for unregistered routes
        assert resp.status_code in (404, 405)


# ---------------------------------------------------------------------------
# 3. POST /auth/login  (server-only)
# ---------------------------------------------------------------------------
class TestAuthLogin:
    @server_only
    async def test_login_returns_token(self, auth_client: AsyncClient):
        # Requires a registered user — register first
        await auth_client.post(
            "/api/v1/auth/register",
            json={"username": "loginuser", "password": "securepassword123"},
        )
        resp = await auth_client.post(
            "/api/v1/auth/login",
            data={"username": "loginuser", "password": "securepassword123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_not_found_oss(self, auth_client: AsyncClient):
        """In OSS distribution, /auth/login should not exist."""
        if _HAS_SERVER_AUTH:
            pytest.skip("Server auth routes installed")
        resp = await auth_client.post(
            "/api/v1/auth/login",
            data={"username": "anyone", "password": "anything"},
        )
        assert resp.status_code in (404, 405)


# ---------------------------------------------------------------------------
# 4. POST /workflows/{id}/execute  (workflow execution round-trip)
# ---------------------------------------------------------------------------
class TestWorkflowExecute:
    async def test_execute_empty_workflow(
        self,
        auth_client: AsyncClient,
        smoke_session: AsyncSession,
        smoke_user: User,
    ):
        """An empty workflow should execute successfully with no results."""
        wf = Workflow(name="smoke-empty", user_id=smoke_user.id)
        smoke_session.add(wf)
        await smoke_session.commit()
        await smoke_session.refresh(wf)

        resp = await auth_client.post(
            f"/api/v1/workflows/{wf.id}/execute",
            json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow_id"] == wf.id
        assert data["status"] in ("success", "completed", "partial")

    async def test_execute_single_node_workflow(
        self,
        auth_client: AsyncClient,
        smoke_session: AsyncSession,
        smoke_user: User,
    ):
        """A workflow with a single preprocessing node should execute."""
        wf = Workflow(name="smoke-snv", user_id=smoke_user.id)
        smoke_session.add(wf)
        await smoke_session.flush()

        node = WorkflowNode(
            workflow_id=wf.id,
            node_id="snv_1",
            node_type="normalize.snv",
            parameters={},
            status="ready",
        )
        smoke_session.add(node)
        await smoke_session.commit()
        await smoke_session.refresh(wf)

        resp = await auth_client.post(
            f"/api/v1/workflows/{wf.id}/execute",
            json={"node_id": "snv_1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["workflow_id"] == wf.id
        # Node without input data will error, but the endpoint should not 500
        assert data["status"] in ("success", "completed", "error", "partial")

    async def test_execute_nonexistent_workflow(self, auth_client: AsyncClient):
        resp = await auth_client.post(
            "/api/v1/workflows/999999/execute",
            json={},
        )
        assert resp.status_code == 404

    async def test_health_endpoint(self, auth_client: AsyncClient):
        resp = await auth_client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# 5. WebSocket /ws roundtrip
# ---------------------------------------------------------------------------
class _NullAsyncSessionContext:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class TestWebSocket:
    def test_ws_subscribe_roundtrip(self, ws_client: TestClient, monkeypatch):
        """Connect, subscribe to a channel, and receive ack."""
        app_config.mode = "local"

        def _factory():
            return _NullAsyncSessionContext()

        monkeypatch.setattr(app_main, "async_session", _factory)

        async def _resolve_user(_session, api_key=None, token=None, client_host=None):
            return SimpleNamespace(id=1, is_superuser=False, is_active=True)

        monkeypatch.setattr(app_main, "get_user_from_credentials", _resolve_user)

        with ws_client.websocket_connect("/ws") as ws:
            ws.send_json({"action": "subscribe", "channel": "jobs"})
            resp = ws.receive_json()
            assert resp["type"] == "subscribed"
            assert "jobs" in resp["channel"]

    def test_ws_sherpa_sync_roundtrip(self, ws_client: TestClient, monkeypatch):
        """Send sherpa_sync and verify response (may be error without full state)."""
        app_config.mode = "local"

        def _factory():
            return _NullAsyncSessionContext()

        monkeypatch.setattr(app_main, "async_session", _factory)

        async def _resolve_user(_session, api_key=None, token=None, client_host=None):
            return SimpleNamespace(id=1, is_superuser=False, is_active=True)

        monkeypatch.setattr(app_main, "get_user_from_credentials", _resolve_user)

        with ws_client.websocket_connect("/ws") as ws:
            ws.send_json({
                "action": "sherpa_sync",
                "workflow_state": {"nodes": [], "edges": []},
            })
            resp = ws.receive_json()
            # Either a sync response or an error (both are valid round-trips)
            assert resp["type"] in ("sherpa_sync", "sherpa_status", "sherpa_error", "error")
