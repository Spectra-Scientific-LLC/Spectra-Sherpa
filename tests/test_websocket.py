from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import spectra_sherpa.app.main as app_main
import spectra_sherpa.app.services.ws_handlers as ws_handlers_mod
from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.services.tools import tool_registry
from spectra_sherpa.app.services.tools.schemas import (
    ToolCategory,
    ToolDefinition,
    ToolOrigin,
    ToolScope,
)
from spectra_sherpa.app.services.websocket_manager import ws_manager


class _NullAsyncSessionContext:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _install_noop_async_session(monkeypatch: pytest.MonkeyPatch) -> None:
    def _factory():
        return _NullAsyncSessionContext()

    monkeypatch.setattr(app_main, "async_session", _factory)


@pytest.fixture(autouse=True)
def _reset_global_state():
    original_mode = app_config.mode
    ws_manager._channels.clear()
    yield
    app_config.mode = original_mode
    ws_manager._channels.clear()


@pytest.fixture
def ws_client():
    client = TestClient(app_main.app)
    try:
        yield client
    finally:
        client.close()


def _policy_violation_on_receive(ws) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:
        ws.receive_json()
    assert exc.value.code == 1008


def test_ws_local_mode_allows_anonymous_and_maps_jobs_alias(ws_client, monkeypatch):
    app_config.mode = "local"
    _install_noop_async_session(monkeypatch)

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        return SimpleNamespace(id=42, is_superuser=False, is_active=True)

    monkeypatch.setattr(app_main, "get_user_from_credentials", _resolve_user)

    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "subscribe", "channel": "jobs"})
        response = ws.receive_json()
        assert response == {"type": "subscribed", "channel": "jobs:42"}

        ws.send_json({"action": "unsubscribe", "channel": "jobs"})
        response = ws.receive_json()
        assert response == {"type": "unsubscribed", "channel": "jobs:42"}


def test_ws_hybrid_non_loopback_rejects_anonymous(ws_client):
    app_config.mode = "hybrid"

    with ws_client.websocket_connect("/ws") as ws:
        _policy_violation_on_receive(ws)


def test_ws_hybrid_loopback_allows_anonymous(ws_client, monkeypatch):
    app_config.mode = "hybrid"
    _install_noop_async_session(monkeypatch)
    monkeypatch.setattr(app_main, "get_client_host", lambda _request_or_ws: "127.0.0.1")

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        return SimpleNamespace(id=7, is_superuser=False, is_active=True)

    monkeypatch.setattr(app_main, "get_user_from_credentials", _resolve_user)

    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "subscribe", "channel": "jobs"})
        response = ws.receive_json()
        assert response == {"type": "subscribed", "channel": "jobs:7"}


def test_ws_enterprise_mode_rejects_invalid_credentials(ws_client, monkeypatch):
    app_config.mode = "enterprise"
    _install_noop_async_session(monkeypatch)

    async def _invalid_api_key(_api_key):
        return False

    monkeypatch.setattr(app_main, "is_valid_api_key", _invalid_api_key)
    monkeypatch.setattr(app_main, "is_valid_bearer_token", lambda _token: False)

    with ws_client.websocket_connect("/ws?api_key=bad-key") as ws:
        _policy_violation_on_receive(ws)


def test_ws_enterprise_user_cannot_subscribe_other_users_jobs(ws_client, monkeypatch):
    app_config.mode = "enterprise"
    _install_noop_async_session(monkeypatch)

    async def _valid_api_key(api_key):
        return api_key == "k1"

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        if api_key == "k1":
            return SimpleNamespace(id=1, is_superuser=False, is_active=True)
        return None

    monkeypatch.setattr(app_main, "is_valid_api_key", _valid_api_key)
    monkeypatch.setattr(app_main, "get_user_from_credentials", _resolve_user)

    with ws_client.websocket_connect("/ws?api_key=k1") as ws:
        ws.send_json({"action": "subscribe", "channel": "jobs:2"})
        response = ws.receive_json()
        assert response["type"] == "error"
        assert "unauthorized channel" in response["detail"]

        ws.send_json({"action": "subscribe", "channel": "jobs"})
        response = ws.receive_json()
        assert response == {"type": "subscribed", "channel": "jobs:1"}


def test_ws_enterprise_superuser_can_subscribe_any_jobs_channel(ws_client, monkeypatch):
    app_config.mode = "enterprise"
    _install_noop_async_session(monkeypatch)

    async def _valid_api_key(api_key):
        return api_key == "root-key"

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        if api_key == "root-key":
            return SimpleNamespace(id=99, is_superuser=True, is_active=True)
        return None

    monkeypatch.setattr(app_main, "is_valid_api_key", _valid_api_key)
    monkeypatch.setattr(app_main, "get_user_from_credentials", _resolve_user)

    with ws_client.websocket_connect("/ws?api_key=root-key") as ws:
        ws.send_json({"action": "subscribe", "channel": "jobs:2"})
        response = ws.receive_json()
        assert response == {"type": "subscribed", "channel": "jobs:2"}


# ---------------------------------------------------------------------------
# Helpers for WS tool tests
# ---------------------------------------------------------------------------

def _setup_local_ws(monkeypatch, *, is_superuser: bool = False, user_id: int = 1):
    """Common setup for local-mode WS tool tests."""
    app_config.mode = "local"
    _install_noop_async_session(monkeypatch)
    # Also patch the handler-level async_session (used by tool_invoke)
    monkeypatch.setattr(ws_handlers_mod, "async_session", lambda: _NullAsyncSessionContext())

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        return SimpleNamespace(id=user_id, is_superuser=is_superuser, is_active=True)

    monkeypatch.setattr(app_main, "get_user_from_credentials", _resolve_user)


def _make_test_tool(
    name: str,
    *,
    scope: ToolScope = ToolScope.public,
    category: ToolCategory = ToolCategory.system,
    parameters: dict | None = None,
) -> ToolDefinition:
    """Create a simple tool definition for testing."""
    return ToolDefinition(
        name=name,
        description=f"Test tool: {name}",
        scope=scope,
        category=category,
        origin=ToolOrigin.builtin,
        parameters=parameters or {"type": "object", "properties": {}, "required": []},
    )


@pytest.fixture
def _cleanup_test_tools():
    """Clean up any test tools registered during a test."""
    registered: list[str] = []
    yield registered
    for name in registered:
        tool_registry.unregister(name)


# ---------------------------------------------------------------------------
# TestWsToolList
# ---------------------------------------------------------------------------

class TestWsToolList:
    """WS integration tests for the tool_list action."""

    def test_tool_list_returns_public_tools(self, ws_client, monkeypatch, _cleanup_test_tools):
        _setup_local_ws(monkeypatch)
        defn = _make_test_tool("ws_test_public")
        tool_registry.register(defn, lambda: {"ok": True})
        _cleanup_test_tools.append("ws_test_public")

        with ws_client.websocket_connect("/ws") as ws:
            ws.send_json({"action": "tool_list"})
            response = ws.receive_json()

        assert response["type"] == "tool_list"
        names = [t["name"] for t in response["payload"]]
        assert "ws_test_public" in names

    def test_tool_list_hides_internal_tools(self, ws_client, monkeypatch, _cleanup_test_tools):
        _setup_local_ws(monkeypatch)
        defn = _make_test_tool("ws_test_internal", scope=ToolScope.internal)
        tool_registry.register(defn, lambda: None)
        _cleanup_test_tools.append("ws_test_internal")

        with ws_client.websocket_connect("/ws") as ws:
            ws.send_json({"action": "tool_list"})
            response = ws.receive_json()

        names = [t["name"] for t in response["payload"]]
        assert "ws_test_internal" not in names

    def test_tool_list_hides_admin_from_non_superuser(self, ws_client, monkeypatch, _cleanup_test_tools):
        _setup_local_ws(monkeypatch, is_superuser=False)
        defn = _make_test_tool("ws_test_admin", scope=ToolScope.admin)
        tool_registry.register(defn, lambda: None)
        _cleanup_test_tools.append("ws_test_admin")

        with ws_client.websocket_connect("/ws") as ws:
            ws.send_json({"action": "tool_list"})
            response = ws.receive_json()

        names = [t["name"] for t in response["payload"]]
        assert "ws_test_admin" not in names

    def test_tool_list_shows_admin_to_superuser(self, ws_client, monkeypatch, _cleanup_test_tools):
        _setup_local_ws(monkeypatch, is_superuser=True)
        defn = _make_test_tool("ws_test_admin_visible", scope=ToolScope.admin)
        tool_registry.register(defn, lambda: None)
        _cleanup_test_tools.append("ws_test_admin_visible")

        with ws_client.websocket_connect("/ws") as ws:
            ws.send_json({"action": "tool_list"})
            response = ws.receive_json()

        names = [t["name"] for t in response["payload"]]
        assert "ws_test_admin_visible" in names

    def test_tool_list_filters_by_category(self, ws_client, monkeypatch, _cleanup_test_tools):
        _setup_local_ws(monkeypatch)
        defn_spectral = _make_test_tool("ws_test_spectral", category=ToolCategory.spectral)
        defn_workflow = _make_test_tool("ws_test_workflow", category=ToolCategory.workflow)
        tool_registry.register(defn_spectral, lambda: None)
        tool_registry.register(defn_workflow, lambda: None)
        _cleanup_test_tools.extend(["ws_test_spectral", "ws_test_workflow"])

        with ws_client.websocket_connect("/ws") as ws:
            ws.send_json({"action": "tool_list", "category": "spectral"})
            response = ws.receive_json()

        names = [t["name"] for t in response["payload"]]
        assert "ws_test_spectral" in names
        assert "ws_test_workflow" not in names


# ---------------------------------------------------------------------------
# TestWsToolInvoke
# ---------------------------------------------------------------------------

class TestWsToolInvoke:
    """WS integration tests for the tool_invoke action."""

    def test_tool_invoke_success(self, ws_client, monkeypatch, _cleanup_test_tools):
        _setup_local_ws(monkeypatch)
        defn = _make_test_tool("ws_test_invoke_ok")
        tool_registry.register(defn, lambda: {"result": "hello"})
        _cleanup_test_tools.append("ws_test_invoke_ok")

        with ws_client.websocket_connect("/ws") as ws:
            ws.send_json({
                "action": "tool_invoke",
                "tool_name": "ws_test_invoke_ok",
                "arguments": {},
            })
            response = ws.receive_json()

        assert response["type"] == "tool_result"
        assert response["payload"]["success"] is True
        assert response["payload"]["result"] == {"result": "hello"}

    def test_tool_invoke_unknown_tool(self, ws_client, monkeypatch, _cleanup_test_tools):
        _setup_local_ws(monkeypatch)

        with ws_client.websocket_connect("/ws") as ws:
            ws.send_json({
                "action": "tool_invoke",
                "tool_name": "nonexistent_tool_xyz",
                "arguments": {},
            })
            response = ws.receive_json()

        assert response["type"] == "tool_result"
        assert response["payload"]["success"] is False
        assert "Unknown tool" in response["payload"]["error"]

    def test_tool_invoke_missing_tool_name(self, ws_client, monkeypatch):
        _setup_local_ws(monkeypatch)

        with ws_client.websocket_connect("/ws") as ws:
            ws.send_json({"action": "tool_invoke", "arguments": {}})
            response = ws.receive_json()

        assert response["type"] == "tool_error"
        assert "Missing tool_name" in response["detail"]

    def test_tool_invoke_internal_scope_blocked(self, ws_client, monkeypatch, _cleanup_test_tools):
        _setup_local_ws(monkeypatch)
        defn = _make_test_tool("ws_test_internal_invoke", scope=ToolScope.internal)
        tool_registry.register(defn, lambda: "should not run")
        _cleanup_test_tools.append("ws_test_internal_invoke")

        with ws_client.websocket_connect("/ws") as ws:
            ws.send_json({
                "action": "tool_invoke",
                "tool_name": "ws_test_internal_invoke",
                "arguments": {},
            })
            response = ws.receive_json()

        assert response["type"] == "tool_result"
        assert response["payload"]["success"] is False
        assert "internal" in response["payload"]["error"].lower()

    def test_tool_invoke_rate_limited(self, ws_client, monkeypatch, _cleanup_test_tools):
        _setup_local_ws(monkeypatch)
        defn = _make_test_tool("ws_test_rate_limited")
        tool_registry.register(defn, lambda: "ok")
        _cleanup_test_tools.append("ws_test_rate_limited")

        # Patch the rate limiter imported inside websocket_endpoint
        from spectra_sherpa.app.api.v1.routes.llm import _llm_rate_limiter
        monkeypatch.setattr(_llm_rate_limiter, "allow", lambda _key: False)

        with ws_client.websocket_connect("/ws") as ws:
            ws.send_json({
                "action": "tool_invoke",
                "tool_name": "ws_test_rate_limited",
                "arguments": {},
            })
            response = ws.receive_json()

        assert response["type"] == "tool_error"
        assert "rate limit" in response["detail"].lower()

    def test_tool_invoke_validation_error(self, ws_client, monkeypatch, _cleanup_test_tools):
        _setup_local_ws(monkeypatch)
        defn = _make_test_tool(
            "ws_test_validate",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        )
        tool_registry.register(defn, lambda name: name)
        _cleanup_test_tools.append("ws_test_validate")

        with ws_client.websocket_connect("/ws") as ws:
            # Missing required "name" argument
            ws.send_json({
                "action": "tool_invoke",
                "tool_name": "ws_test_validate",
                "arguments": {},
            })
            response = ws.receive_json()

        assert response["type"] == "tool_result"
        assert response["payload"]["success"] is False
        assert "name" in response["payload"]["error"].lower()
