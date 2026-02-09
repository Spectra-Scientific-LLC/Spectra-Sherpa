from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import app.main as app_main
from app.core.config import app_config
from app.services.websocket_manager import ws_manager


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


def test_ws_demo_mode_rejects_invalid_credentials(ws_client, monkeypatch):
    app_config.mode = "demo"
    _install_noop_async_session(monkeypatch)

    async def _invalid_api_key(_api_key):
        return False

    monkeypatch.setattr(app_main, "is_valid_api_key", _invalid_api_key)
    monkeypatch.setattr(app_main, "is_valid_bearer_token", lambda _token: False)

    with ws_client.websocket_connect("/ws?api_key=bad-key") as ws:
        _policy_violation_on_receive(ws)


def test_ws_demo_user_cannot_subscribe_other_users_jobs(ws_client, monkeypatch):
    app_config.mode = "demo"
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


def test_ws_demo_superuser_can_subscribe_any_jobs_channel(ws_client, monkeypatch):
    app_config.mode = "demo"
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
