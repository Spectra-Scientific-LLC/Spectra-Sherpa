from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from starlette.websockets import WebSocketDisconnect

import spectra_sherpa.app.main as app_main
import spectra_sherpa.app.services.ws_auth as ws_auth_mod
import spectra_sherpa.app.services.ws_handlers as ws_handlers_mod
from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.services.websocket_manager import ws_manager
from spectra_sherpa.app.ws_actions import SHERPA_SYNC


class _NullAsyncSessionContext:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _install_noop_async_session(monkeypatch: pytest.MonkeyPatch) -> None:
    def _factory():
        return _NullAsyncSessionContext()

    monkeypatch.setattr(app_main, "async_session", _factory)
    monkeypatch.setattr(ws_auth_mod, "async_session", _factory)


@pytest.fixture(autouse=True)
def _reset_global_state():
    from spectra_sherpa.app.contracts.auth_resolver import clear_user_compute_access_resolver

    original_mode = app_config.mode
    clear_user_compute_access_resolver()
    ws_manager._channels.clear()
    ws_manager._authorizers.clear()
    yield
    app_config.mode = original_mode
    clear_user_compute_access_resolver()
    ws_manager._channels.clear()
    ws_manager._authorizers.clear()


def _policy_violation_on_receive(ws) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:
        ws.receive_json()
    assert exc.value.code == 1008


def test_ws_local_mode_allows_anonymous_and_maps_jobs_alias(ws_client, monkeypatch):
    app_config.mode = "local"
    _install_noop_async_session(monkeypatch)
    monkeypatch.setattr(app_main, "get_client_host", lambda _request_or_ws: "127.0.0.1")

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        return SimpleNamespace(id=42, is_superuser=False, is_active=True)

    monkeypatch.setattr(ws_auth_mod, "get_user_from_credentials", _resolve_user)

    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "subscribe", "channel": "jobs"})
        response = ws.receive_json()
        assert response == {"type": "subscribed", "channel": "jobs:42"}

        ws.send_json({"action": "unsubscribe", "channel": "jobs"})
        response = ws.receive_json()
        assert response == {"type": "unsubscribed", "channel": "jobs:42"}


def test_ws_extension_test_non_loopback_rejects_anonymous(ws_client):
    app_config.mode = "extension_test"

    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "subscribe", "channel": "jobs"})
        _policy_violation_on_receive(ws)


def test_ws_extension_test_non_loopback_accepts_first_frame_authentication(ws_client, monkeypatch):
    app_config.mode = "extension_test"
    _install_noop_async_session(monkeypatch)

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        if token == "jwt-1":
            return SimpleNamespace(id=11, is_superuser=False, is_active=True)
        return None

    monkeypatch.setattr(ws_auth_mod, "get_user_from_credentials", _resolve_user)

    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "authenticate", "token": "jwt-1"})
        response = ws.receive_json()
        assert response == {"type": "authenticated", "user_id": 11}

        ws.send_json({"action": "subscribe", "channel": "jobs"})
        response = ws.receive_json()
        assert response == {"type": "subscribed", "channel": "jobs:11"}


def test_ws_managed_compute_access_is_checked_at_auth_and_each_action(ws_client, monkeypatch):
    from spectra_sherpa.app.contracts.auth_resolver import set_user_compute_access_resolver

    app_config.mode = "enterprise"
    _install_noop_async_session(monkeypatch)

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        if token == "jwt-1":
            return SimpleNamespace(id=11, is_superuser=False, is_active=True)
        return None

    calls: list[int] = []

    async def _access(user_id: int) -> bool:
        calls.append(user_id)
        return len(calls) == 1

    monkeypatch.setattr(ws_auth_mod, "get_user_from_credentials", _resolve_user)
    set_user_compute_access_resolver(_access)

    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "authenticate", "token": "jwt-1"})
        assert ws.receive_json() == {"type": "authenticated", "user_id": 11}

        ws.send_json({"action": "subscribe", "channel": "jobs"})
        response = ws.receive_json()
        assert response == {"type": "error", "detail": "Managed trial access is not active"}
        _policy_violation_on_receive(ws)

    assert calls == [11, 11]


def test_ws_injected_transport_authority_sees_connect_and_each_frame(ws_client, monkeypatch):
    app_config.mode = "extension_test"
    _install_noop_async_session(monkeypatch)

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        if token == "jwt-1":
            return SimpleNamespace(id=11, is_superuser=False, is_active=True)
        return None

    calls: list[tuple[str, int | None]] = []

    async def _admit(event: str, _address: str | None, user_id: int | None):
        calls.append((event, user_id))
        return app_main.WebSocketAdmissionDecision(allowed=True)

    monkeypatch.setattr(ws_auth_mod, "get_user_from_credentials", _resolve_user)
    original = app_main.app.state.websocket_admission_provider
    app_main.app.state.websocket_admission_provider = _admit
    try:
        with ws_client.websocket_connect("/ws") as ws:
            ws.send_json({"action": "authenticate", "token": "jwt-1"})
            assert ws.receive_json() == {"type": "authenticated", "user_id": 11}
            ws.send_json({"action": "subscribe", "channel": "jobs"})
            assert ws.receive_json() == {"type": "subscribed", "channel": "jobs:11"}
    finally:
        app_main.app.state.websocket_admission_provider = original

    assert calls == [("connect", None), ("authenticate", None), ("subscribe", 11)]


def test_ws_transport_refusal_is_visible_and_closes_connection(ws_client, monkeypatch):
    app_config.mode = "local"
    _install_noop_async_session(monkeypatch)
    monkeypatch.setattr(app_main, "get_client_host", lambda _request_or_ws: "127.0.0.1")

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        return SimpleNamespace(id=7, is_superuser=False, is_active=True)

    monkeypatch.setattr(ws_auth_mod, "get_user_from_credentials", _resolve_user)

    async def _refuse(_event: str, _address: str | None, _user_id: int | None):
        return app_main.WebSocketAdmissionDecision(
            allowed=False,
            reason="api_deployment",
            retry_after_seconds=17,
        )

    original = app_main.app.state.websocket_admission_provider
    app_main.app.state.websocket_admission_provider = _refuse
    try:
        with ws_client.websocket_connect("/ws") as ws:
            assert ws.receive_json() == {
                "type": "error",
                "detail": "Managed trial transport admission refused",
                "reason": "api_deployment",
                "retry_after_seconds": 17,
            }
            with pytest.raises(WebSocketDisconnect) as exc:
                ws.receive_json()
            assert exc.value.code == 1013
    finally:
        app_main.app.state.websocket_admission_provider = original


def test_ws_transport_authority_failure_fails_closed(ws_client, monkeypatch):
    app_config.mode = "local"
    _install_noop_async_session(monkeypatch)
    monkeypatch.setattr(app_main, "get_client_host", lambda _request_or_ws: "127.0.0.1")

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        return SimpleNamespace(id=7, is_superuser=False, is_active=True)

    async def _unavailable(_event: str, _address: str | None, _user_id: int | None):
        raise RuntimeError("database detail must not cross the socket")

    monkeypatch.setattr(ws_auth_mod, "get_user_from_credentials", _resolve_user)
    original = app_main.app.state.websocket_admission_provider
    app_main.app.state.websocket_admission_provider = _unavailable
    try:
        with ws_client.websocket_connect("/ws") as ws:
            refusal = ws.receive_json()
            assert refusal == {
                "type": "error",
                "detail": "Managed trial transport admission refused",
                "reason": "transport_authority_unavailable",
                "retry_after_seconds": 1,
            }
            assert "database detail" not in str(refusal)
    finally:
        app_main.app.state.websocket_admission_provider = original


def test_ws_extension_test_non_loopback_ignores_query_param_credentials(ws_client):
    app_config.mode = "extension_test"

    with ws_client.websocket_connect("/ws?api_key=k1") as ws:
        ws.send_json({"action": "subscribe", "channel": "jobs"})
        _policy_violation_on_receive(ws)


def test_ws_extension_test_non_loopback_ignores_header_credentials(ws_client):
    app_config.mode = "extension_test"

    with ws_client.websocket_connect("/ws", headers={"authorization": "Bearer jwt-1"}) as ws:
        ws.send_json({"action": "subscribe", "channel": "jobs"})
        _policy_violation_on_receive(ws)


def test_ws_extension_test_loopback_allows_anonymous(ws_client, monkeypatch):
    app_config.mode = "extension_test"
    _install_noop_async_session(monkeypatch)
    monkeypatch.setattr(app_main, "get_client_host", lambda _request_or_ws: "127.0.0.1")

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        return SimpleNamespace(id=7, is_superuser=False, is_active=True)

    monkeypatch.setattr(ws_auth_mod, "get_user_from_credentials", _resolve_user)

    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "subscribe", "channel": "jobs"})
        response = ws.receive_json()
        assert response == {"type": "subscribed", "channel": "jobs:7"}


def test_ws_extension_test_loopback_authenticate_can_upgrade_identity_with_api_key(ws_client, monkeypatch):
    app_config.mode = "extension_test"
    _install_noop_async_session(monkeypatch)
    monkeypatch.setattr(app_main, "get_client_host", lambda _request_or_ws: "127.0.0.1")

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        if api_key == "linked-key":
            return SimpleNamespace(id=99, is_superuser=False, is_active=True)
        return SimpleNamespace(id=7, is_superuser=False, is_active=True)

    monkeypatch.setattr(ws_auth_mod, "get_user_from_credentials", _resolve_user)

    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "authenticate", "api_key": "linked-key"})
        response = ws.receive_json()
        assert response == {"type": "authenticated", "user_id": 99}

        ws.send_json({"action": "subscribe", "channel": "jobs"})
        response = ws.receive_json()
        assert response == {"type": "subscribed", "channel": "jobs:99"}


def test_ws_enterprise_ignores_query_param_credentials(ws_client, monkeypatch):
    app_config.mode = "enterprise"
    _install_noop_async_session(monkeypatch)

    with ws_client.websocket_connect("/ws?api_key=bad-key") as ws:
        ws.send_json({"action": "subscribe", "channel": "jobs"})
        _policy_violation_on_receive(ws)


def test_ws_enterprise_rejects_invalid_first_frame_authentication(ws_client, monkeypatch):
    app_config.mode = "enterprise"
    _install_noop_async_session(monkeypatch)

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        return None

    monkeypatch.setattr(ws_auth_mod, "get_user_from_credentials", _resolve_user)

    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "authenticate", "token": "bad-jwt"})
        _policy_violation_on_receive(ws)


def test_ws_enterprise_ignores_header_credentials(ws_client, monkeypatch):
    app_config.mode = "enterprise"
    _install_noop_async_session(monkeypatch)

    with ws_client.websocket_connect("/ws", headers={"x-api-key": "root-key"}) as ws:
        ws.send_json({"action": "subscribe", "channel": "jobs"})
        _policy_violation_on_receive(ws)


def test_ws_enterprise_user_cannot_subscribe_other_users_jobs(ws_client, monkeypatch):
    app_config.mode = "enterprise"
    _install_noop_async_session(monkeypatch)

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        if api_key == "k1":
            return SimpleNamespace(id=1, is_superuser=False, is_active=True)
        return None

    monkeypatch.setattr(ws_auth_mod, "get_user_from_credentials", _resolve_user)

    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "authenticate", "api_key": "k1"})
        response = ws.receive_json()
        assert response == {"type": "authenticated", "user_id": 1}

        ws.send_json({"action": "subscribe", "channel": "jobs:2"})
        response = ws.receive_json()
        assert response["type"] == "error"
        assert "unauthorized channel" in response["detail"]

        ws.send_json({"action": "subscribe", "channel": "jobs"})
        response = ws.receive_json()
        assert response == {"type": "subscribed", "channel": "jobs:1"}


def test_ws_enterprise_user_cannot_subscribe_unknown_channel(ws_client, monkeypatch):
    """Subscription channel names are an allowlist, not a client namespace."""
    app_config.mode = "enterprise"
    _install_noop_async_session(monkeypatch)

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        if api_key == "k1":
            return SimpleNamespace(id=1, is_superuser=False, is_active=True)
        return None

    monkeypatch.setattr(ws_auth_mod, "get_user_from_credentials", _resolve_user)

    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "authenticate", "api_key": "k1"})
        assert ws.receive_json() == {"type": "authenticated", "user_id": 1}

        ws.send_json({"action": "subscribe", "channel": "future-unscoped-channel"})
        response = ws.receive_json()
        assert response["type"] == "error"
        assert "unauthorized channel" in response["detail"]


def test_ws_enterprise_superuser_can_subscribe_any_jobs_channel(ws_client, monkeypatch):
    """After v0.4.1 Phase 2, is_superuser moved to ManagedUserAccount
    and OSS admin gates read through the ``AdminResolver`` contract.
    Registering a resolver that returns True for user id 99 simulates
    the server's startup wiring; is_superuser attribute is ignored.
    """
    from spectra_sherpa.app.contracts.auth_resolver import (
        clear_extra_admin_resolver,
        set_extra_admin_resolver,
    )

    app_config.mode = "enterprise"
    _install_noop_async_session(monkeypatch)

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        if api_key == "root-key":
            return SimpleNamespace(id=99, is_active=True)
        return None

    monkeypatch.setattr(ws_auth_mod, "get_user_from_credentials", _resolve_user)

    async def _admin_resolver(user_id: int) -> bool:
        return user_id == 99

    set_extra_admin_resolver(_admin_resolver)
    try:
        with ws_client.websocket_connect("/ws") as ws:
            ws.send_json({"action": "authenticate", "api_key": "root-key"})
            response = ws.receive_json()
            assert response == {"type": "authenticated", "user_id": 99}

            ws.send_json({"action": "subscribe", "channel": "jobs:2"})
            response = ws.receive_json()
            assert response == {"type": "subscribed", "channel": "jobs:2"}
    finally:
        clear_extra_admin_resolver()


def test_ws_data_import_action_is_no_longer_supported(ws_client, monkeypatch):
    app_config.mode = "enterprise"
    _install_noop_async_session(monkeypatch)

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        if api_key == "k1":
            return SimpleNamespace(id=1, is_superuser=False, is_active=True)
        return None

    monkeypatch.setattr(ws_auth_mod, "get_user_from_credentials", _resolve_user)

    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "authenticate", "api_key": "k1"})
        response = ws.receive_json()
        assert response == {"type": "authenticated", "user_id": 1}

        ws.send_json({"action": "llm_data_import", "message": "inspect /etc/hosts"})
        response = ws.receive_json()
        assert response == {"type": "error", "detail": "Unknown action"}


def test_ws_unregistered_sherpa_action_returns_unknown_action(ws_client, monkeypatch):
    app_config.mode = "local"
    _install_noop_async_session(monkeypatch)
    monkeypatch.setattr(app_main, "get_client_host", lambda _request_or_ws: "127.0.0.1")

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        return SimpleNamespace(id=1, is_superuser=False, is_active=True)

    monkeypatch.setattr(ws_auth_mod, "get_user_from_credentials", _resolve_user)
    original_registry = app_main.app.state.ws_action_registry
    app_main.app.state.ws_action_registry = app_main.create_app(include_server_routers=False).state.ws_action_registry
    try:
        with ws_client.websocket_connect("/ws") as ws:
            ws.send_json({"action": SHERPA_SYNC, "payload": {"nodes": [], "edges": []}})
            response = ws.receive_json()
            assert response == {"type": "error", "detail": "Unknown action"}
    finally:
        app_main.app.state.ws_action_registry = original_registry


# ---------------------------------------------------------------------------
# Helpers for WS tool tests
# ---------------------------------------------------------------------------


def test_ws_rejects_revoked_token_on_existing_connection(ws_client, monkeypatch):
    """An already-open enterprise socket is closed when its token is revoked."""
    from spectra_sherpa.app.contracts.auth_resolver import set_extra_bearer_token_validator

    app_config.mode = "enterprise"

    user = SimpleNamespace(id=11, is_superuser=False, is_active=True)

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def execute(self, _stmt):
            class _Result:
                def scalar_one_or_none(self_inner):
                    return user

                def one_or_none(self_inner):
                    return (2, True)

            return _Result()

    monkeypatch.setattr(app_main, "async_session", lambda: _FakeSession())
    monkeypatch.setattr(ws_auth_mod, "async_session", lambda: _FakeSession())

    calls: list[str] = []

    async def _validator(token: str) -> dict | None:
        calls.append(token)
        if len(calls) == 1:
            return {"sub": "11", "tv": 1}
        return None

    set_extra_bearer_token_validator(_validator)
    try:
        with ws_client.websocket_connect("/ws") as ws:
            ws.send_json({"action": "authenticate", "token": "jwt-1"})
            assert ws.receive_json() == {"type": "authenticated", "user_id": 11}

            # Token is revoked before the next protected action.
            ws.send_json({"action": "subscribe", "channel": "jobs"})
            response = ws.receive_json()
            assert response == {"type": "error", "detail": "Session invalidated"}
            _policy_violation_on_receive(ws)
    finally:
        from spectra_sherpa.app.contracts.auth_resolver import clear_extra_bearer_token_validator

        clear_extra_bearer_token_validator()


@pytest.mark.parametrize("channel", ["jobs:11", "workflow:23"])
@pytest.mark.parametrize("authority_failure", [False, True], ids=["revoked", "authority-unavailable"])
def test_ws_passive_subscriber_loses_all_channels_on_revocation(ws_client, monkeypatch, channel, authority_failure):
    """Delivery itself must check session authority, without an incoming action."""
    from spectra_sherpa.app.contracts.auth_resolver import (
        clear_extra_bearer_token_validator,
        set_extra_bearer_token_validator,
    )

    app_config.mode = "enterprise"
    _install_noop_async_session(monkeypatch)
    user = SimpleNamespace(id=11, is_active=True)
    monkeypatch.setattr(ws_auth_mod, "get_user_from_credentials", AsyncMock(return_value=user))
    monkeypatch.setattr(app_main, "_authorize_workflow_channel", AsyncMock(return_value="workflow:23"))
    revoked = False
    validations = []

    async def validator(token):
        validations.append(revoked)
        if revoked and authority_failure:
            raise RuntimeError("synthetic session authority outage")
        return None if revoked else {"sub": "11", "tv": 1}

    set_extra_bearer_token_validator(validator)
    try:
        with ws_client.websocket_connect("/ws") as ws:
            ws.send_json({"action": "authenticate", "token": "synthetic-review-token"})
            assert ws.receive_json() == {"type": "authenticated", "user_id": 11}
            for requested in ("jobs:11", "workflow:23"):
                ws.send_json({"action": "subscribe", "channel": requested})
                assert ws.receive_json() == {"type": "subscribed", "channel": requested}

            event = {"type": "job_update", "review_marker": "protected"}
            ws.portal.call(ws_manager.broadcast, channel, event)
            assert ws.receive_json() == event
            revoked = True
            ws.portal.call(ws_manager.broadcast, channel, event)
            assert ws.receive_json() == {"type": "error", "detail": "Session invalidated"}
            _policy_violation_on_receive(ws)
            assert validations[-1] is True
            assert not any(ws_manager._channels.values())
            assert not ws_manager._authorizers
            # A second producer cannot deliver via a different retained channel.
            ws.portal.call(ws_manager.broadcast, "workflow:23" if channel == "jobs:11" else "jobs:11", event)
    finally:
        clear_extra_bearer_token_validator()


@pytest.mark.parametrize("change", ["revoked", "inactive", "different-user"])
def test_ws_api_key_revocation_blocks_passive_delivery(ws_client, monkeypatch, change):
    app_config.mode = "enterprise"
    _install_noop_async_session(monkeypatch)
    resolver = AsyncMock(return_value=SimpleNamespace(id=11, is_active=True))
    monkeypatch.setattr(ws_auth_mod, "get_user_from_credentials", resolver)
    invalidate = Mock()
    monkeypatch.setattr(ws_auth_mod, "invalidate_api_key_cache", invalidate)
    with ws_client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "authenticate", "api_key": "synthetic-key"})
        assert ws.receive_json() == {"type": "authenticated", "user_id": 11}
        ws.send_json({"action": "subscribe", "channel": "jobs"})
        assert ws.receive_json() == {"type": "subscribed", "channel": "jobs:11"}
        resolver.return_value = {
            "revoked": None,
            "inactive": SimpleNamespace(id=11, is_active=False),
            "different-user": SimpleNamespace(id=12, is_active=True),
        }[change]
        ws.portal.call(ws_manager.broadcast, "jobs:11", {"type": "protected"})
        assert ws.receive_json() == {"type": "error", "detail": "Session invalidated"}
        _policy_violation_on_receive(ws)
        invalidate.assert_called_with("synthetic-key")


def _setup_local_ws(monkeypatch, *, is_superuser: bool = False, user_id: int = 1):
    """Common setup for local-mode WS tool tests."""
    app_config.mode = "local"
    _install_noop_async_session(monkeypatch)
    # Also patch the handler-level async_session (used by tool_invoke)
    monkeypatch.setattr(ws_handlers_mod, "async_session", lambda: _NullAsyncSessionContext())

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        return SimpleNamespace(id=user_id, is_superuser=is_superuser, is_active=True)

    monkeypatch.setattr(ws_auth_mod, "get_user_from_credentials", _resolve_user)


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked", [False, True])
async def test_websocket_endpoint_uses_configured_idle_timeout(monkeypatch: pytest.MonkeyPatch, revoked):
    class _FakeWebSocket:
        def __init__(self):
            self.app = SimpleNamespace(
                state=SimpleNamespace(
                    ws_action_registry=SimpleNamespace(
                        dispatch=AsyncMock(return_value=False), requests=SimpleNamespace(close=AsyncMock())
                    )
                )
            )
            self.sent: list[dict] = []
            self.state = SimpleNamespace(ws_auth_token="synthetic-token" if revoked else None)
            self.close_code = None

        async def receive_json(self):
            return {"action": "noop"}

        async def send_json(self, payload):
            self.sent.append(payload)
            if not revoked:
                raise RuntimeError("socket gone")

        async def close(self, code):
            self.close_code = code

    async def _resolve_initial_ws_user(*args, **kwargs):
        return SimpleNamespace(id=7, is_superuser=False, is_active=True)

    async def _stamp_last_active(_user):
        return None

    async def _wait_for(awaitable, timeout):
        captured["timeout"] = timeout
        awaitable.close()
        raise asyncio.TimeoutError

    captured: dict[str, float] = {}
    ws = _FakeWebSocket()

    monkeypatch.setattr(app_main, "get_client_host", lambda _request_or_ws: "127.0.0.1")
    monkeypatch.setattr(ws_auth_mod, "resolve_initial_ws_user", _resolve_initial_ws_user)
    monkeypatch.setattr(ws_auth_mod, "stamp_last_active", _stamp_last_active)
    monkeypatch.setattr(ws_auth_mod, "revalidate_ws_token", AsyncMock(return_value=not revoked))
    monkeypatch.setattr(app_main.ws_manager, "connect", AsyncMock())
    monkeypatch.setattr(app_main.asyncio, "wait_for", _wait_for)
    original_timeout = app_main.settings.ws_idle_timeout_sec
    object.__setattr__(app_main.settings, "ws_idle_timeout_sec", 9)
    try:
        await app_main.websocket_endpoint(ws)
    finally:
        object.__setattr__(app_main.settings, "ws_idle_timeout_sec", original_timeout)

    assert captured["timeout"] == 9.0
    ws.app.state.ws_action_registry.requests.close.assert_awaited_once_with(ws)
    if revoked:
        assert ws.sent == [{"type": "error", "detail": "Session invalidated"}]
        assert ws.close_code == 1008
    else:
        assert ws.sent == [{"type": "ping"}]


@pytest.fixture(autouse=True)
def explicit_test_runtime_policy(monkeypatch):
    from spectra_sherpa.app.contracts import runtime_mode

    monkeypatch.setattr(runtime_mode, "_policies", {})
    runtime_mode.register_runtime_mode(
        runtime_mode.RuntimeModePolicy(name="extension_test", implicit_loopback_identity=True)
    )
