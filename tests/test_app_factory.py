from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import spectra_sherpa.app.main as app_main
from spectra_sherpa.app.api.v1 import api as api_v1
from spectra_sherpa.app.ws_actions import LLM_CHAT, SHERPA_SYNC


def _paths(routes) -> set[str]:
    return {route.path for route in routes}


def _sync_event(events: list[str], name: str) -> Callable[..., None]:
    def _fn(*args: Any, **kwargs: Any) -> None:
        events.append(name)

    return _fn


def _async_event(events: list[str], name: str) -> Callable[..., Awaitable[None]]:
    async def _fn(*args: Any, **kwargs: Any) -> None:
        events.append(name)

    return _fn


def test_build_api_router_can_skip_server_routes():
    with patch("spectra_sherpa.app.api.v1.api.get_server_routers") as get_server:
        router = api_v1.build_api_router(include_server_routers=False)
    get_server.assert_not_called()
    paths = _paths(router.routes)
    assert "/auth/me" in paths
    assert "/auth/login" not in paths
    assert not any(path.startswith("/admin") for path in paths)


def test_build_api_router_can_skip_actor_compat_route():
    router = api_v1.build_api_router(include_actor_compat_route=False)

    assert "/auth/me" not in _paths(router.routes)


def test_build_api_router_includes_server_routes_when_enabled():
    server_router = APIRouter()

    @server_router.get("/whoami")
    async def _whoami() -> dict[str, str]:
        return {"user": "server"}

    with patch(
        "spectra_sherpa.app.api.v1.api.get_server_routers",
        return_value=[(server_router, {"prefix": "/auth"})],
    ) as get_server:
        router = api_v1.build_api_router(include_server_routers=True)

    get_server.assert_called_once()
    assert "/auth/whoami" in _paths(router.routes)


def test_build_api_router_exposes_auth_me_for_multi_user_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("spectra_sherpa.app.core.mode_policy.is_multi_user", lambda: True)

    router = api_v1.build_api_router(include_server_routers=True)

    assert "/auth/me" in _paths(router.routes)
    assert "/auth/login" not in _paths(router.routes)


def test_build_api_router_exposes_auth_me_when_server_routes_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("spectra_sherpa.app.api.v1.api.get_server_routers", lambda: [])

    router = api_v1.build_api_router(include_server_routers=True)

    assert "/auth/me" in _paths(router.routes)
    assert "/auth/login" not in _paths(router.routes)


def test_create_app_accepts_extra_router_prefix_string():
    extra = APIRouter()

    @extra.get("/ping")
    async def _ping() -> dict[str, bool]:
        return {"ok": True}

    app = app_main.create_app(
        include_server_routers=False,
        extra_routers=[(extra, "/x")],
    )
    assert "/x/ping" in _paths(app.routes)
    assert "/ws" in _paths(app.routes)
    assert "/api/ready" in _paths(app.routes)
    assert app.state.ws_action_registry.names() == (LLM_CHAT,)


def test_create_app_accepts_extra_router_mapping():
    extra = APIRouter()

    @extra.get("/status")
    async def _status() -> dict[str, str]:
        return {"status": "ok"}

    app = app_main.create_app(
        include_server_routers=False,
        extra_routers=[(extra, {"prefix": "/svc", "tags": ["svc"]})],
    )
    assert "/svc/status" in _paths(app.routes)


def test_create_app_can_skip_actor_compat_route():
    app = app_main.create_app(include_server_routers=False, include_actor_compat_route=False)

    assert "/api/v1/auth/me" not in _paths(app.routes)


def test_create_app_resets_websocket_actions_to_core_only():
    app = app_main.create_app(include_server_routers=False)
    app.state.ws_action_registry.register("custom_action", lambda *_args, **_kwargs: None)  # type: ignore[arg-type]
    assert "custom_action" in app.state.ws_action_registry.names()

    fresh_app = app_main.create_app(include_server_routers=False)

    assert fresh_app.state.ws_action_registry.names() == (LLM_CHAT,)
    assert SHERPA_SYNC not in fresh_app.state.ws_action_registry.names()


def test_create_app_can_register_extra_websocket_actions():
    def _register_extra(app):
        app.state.ws_action_registry.register("custom_action", lambda *_args, **_kwargs: None)  # type: ignore[arg-type]

    app = app_main.create_app(
        include_server_routers=False,
        extra_ws_action_registrars=[_register_extra],
    )

    assert "custom_action" in app.state.ws_action_registry.names()


def test_ready_endpoint_is_public_when_http_auth_required(monkeypatch: pytest.MonkeyPatch):
    class _FakeSession:
        async def execute(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    class _FakeSessionManager:
        async def __aenter__(self) -> _FakeSession:
            return _FakeSession()

        async def __aexit__(self, exc_type, exc, tb) -> bool:
            return False

    monkeypatch.setattr("spectra_sherpa.app.core.security.requires_http_auth", lambda _host: True)
    monkeypatch.setattr(app_main, "async_session", lambda: _FakeSessionManager())
    monkeypatch.setattr(
        "spectra_sherpa.app.services.plugin_loader.plugin_load_failures",
        [],
    )

    app = app_main.create_app(include_server_routers=False)
    client = TestClient(app)

    response = client.get("/api/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_version_endpoint_is_public_when_http_auth_required(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("spectra_sherpa.app.core.security.requires_http_auth", lambda _host: True)

    app = app_main.create_app(include_server_routers=False)
    client = TestClient(app)

    response = client.get("/api/v1/version")

    assert response.status_code == 200
    assert "backend_version" in response.json()


def test_local_mode_blocks_non_loopback_frontend_and_public_api(monkeypatch: pytest.MonkeyPatch):
    from spectra_sherpa.app.core.config import app_config

    monkeypatch.setattr(app_config, "mode", "local")
    monkeypatch.delenv("SPECTRA_SHERPA_ALLOW_LOCAL_NETWORK", raising=False)
    monkeypatch.delenv("SPECTRASHERPA_ALLOW_LOCAL_NETWORK", raising=False)

    app = app_main.create_app(include_server_routers=False)
    client = TestClient(app, client=("10.0.0.8", 50000))

    config_response = client.get("/api/v1/config")
    assert config_response.status_code == 403
    assert "Local mode only accepts loopback clients" in config_response.text

    frontend_response = client.get("/")
    assert frontend_response.status_code == 403

    health_response = client.get("/api/v1/health")
    assert health_response.status_code == 200


def test_local_mode_network_exposure_requires_explicit_opt_in(monkeypatch: pytest.MonkeyPatch):
    from spectra_sherpa.app.core.config import app_config

    monkeypatch.setattr(app_config, "mode", "local")
    monkeypatch.setenv("SPECTRA_SHERPA_ALLOW_LOCAL_NETWORK", "true")

    probe = APIRouter()

    @probe.get("/local-network-probe")
    async def _local_network_probe() -> dict[str, bool]:
        return {"ok": True}

    app = app_main.create_app(
        include_server_routers=False,
        extra_routers=[(probe, {})],
    )
    client = TestClient(app, client=("10.0.0.8", 50000))

    response = client.get("/local-network-probe")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_local_mode_blocks_non_loopback_websocket(monkeypatch: pytest.MonkeyPatch):
    from spectra_sherpa.app.core.config import app_config

    monkeypatch.setattr(app_config, "mode", "local")
    monkeypatch.delenv("SPECTRA_SHERPA_ALLOW_LOCAL_NETWORK", raising=False)
    monkeypatch.delenv("SPECTRASHERPA_ALLOW_LOCAL_NETWORK", raising=False)

    app = app_main.create_app(include_server_routers=False)
    client = TestClient(app, client=("10.0.0.8", 50000))

    with client.websocket_connect("/ws") as websocket:
        with pytest.raises(WebSocketDisconnect) as exc_info:
            websocket.receive_json()

    assert exc_info.value.code == 1008


def test_create_app_rejects_invalid_extra_router_config():
    extra = APIRouter()
    with pytest.raises(TypeError, match="config must be a prefix string or mapping"):
        app_main.create_app(
            include_server_routers=False,
            extra_routers=[(extra, 123)],
        )


@pytest.mark.asyncio
async def test_lifespan_runs_extra_shutdown_before_core_teardown(monkeypatch: pytest.MonkeyPatch):
    events: list[str] = []

    # Startup sync phase
    from spectra_sherpa.app.core.startup import ConfigValidationResult

    monkeypatch.setattr(app_main, "configure_logging", _sync_event(events, "configure_logging"))
    monkeypatch.setattr(
        app_main,
        "validate_config",
        lambda: (events.append("validate_config"), ConfigValidationResult())[1],
    )
    monkeypatch.setattr(app_main, "ensure_data_dirs", _sync_event(events, "ensure_data_dirs"))
    monkeypatch.setattr(app_main, "_try_leader_lock", lambda: True)

    # Startup async phase
    monkeypatch.setattr(app_main, "ensure_database_ready", _async_event(events, "ensure_database_ready"))
    monkeypatch.setattr(app_main, "ensure_default_user", _async_event(events, "ensure_default_user"))
    monkeypatch.setattr(app_main, "ensure_egress_defaults", _async_event(events, "ensure_egress_defaults"))
    monkeypatch.setattr(app_main, "reconcile_stale_jobs", _async_event(events, "reconcile_stale_jobs"))
    monkeypatch.setattr(app_main, "ensure_spectrochempy_data", _sync_event(events, "ensure_spectrochempy_data"))
    monkeypatch.setattr(
        app_main, "ensure_spectrochempy_testdata", _async_event(events, "ensure_spectrochempy_testdata")
    )
    monkeypatch.setattr(app_main, "ensure_workflow_templates", _async_event(events, "ensure_workflow_templates"))
    monkeypatch.setattr(
        "spectra_sherpa.app.services.plugin_loader.discover_plugins", _sync_event(events, "discover_plugins")
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.services.network_health.start_network_health_service",
        _async_event(events, "start_network_health_service"),
    )

    # Shutdown async phase
    monkeypatch.setattr(app_main.job_manager, "shutdown", _async_event(events, "job_manager_shutdown"))
    monkeypatch.setattr(
        "spectra_sherpa.app.services.network_health.stop_network_health_service",
        _async_event(events, "stop_network_health_service"),
    )

    async def extra_startup() -> None:
        events.append("extra_startup")

    async def extra_shutdown() -> None:
        events.append("extra_shutdown")

    lifespan = app_main._make_lifespan(
        extra_startup=[extra_startup],
        extra_shutdown=[extra_shutdown],
    )

    async with lifespan(FastAPI()):
        events.append("inside")

    assert "extra_startup" in events
    assert "extra_shutdown" in events
    assert events.index("extra_startup") < events.index("inside")
    assert events.index("extra_shutdown") < events.index("job_manager_shutdown")


# --------------------------------------------------------------------------
# Audit SEC-3: wildcard CORS must not be credentialed
# --------------------------------------------------------------------------


def _cors_kwargs(app: FastAPI) -> dict:
    from fastapi.middleware.cors import CORSMiddleware

    for mw in app.user_middleware:
        if mw.cls is CORSMiddleware:
            return dict(getattr(mw, "kwargs", None) or getattr(mw, "options", {}))
    raise AssertionError("CORSMiddleware not registered")


def test_wildcard_cors_disables_credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(app_main, "get_cors_origins", lambda: ["*"])
    app = app_main.create_app(include_server_routers=False)
    kw = _cors_kwargs(app)

    # Reflected/wildcard origin must never be combined with credentials.
    assert kw["allow_credentials"] is False
    assert kw.get("allow_origin_regex") == r".*"
    assert kw.get("allow_origins") in ([], None)


def test_explicit_cors_keeps_credentials(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(app_main, "get_cors_origins", lambda: ["https://app.example.com"])
    app = app_main.create_app(include_server_routers=False)
    kw = _cors_kwargs(app)

    assert kw["allow_credentials"] is True
    assert kw["allow_origins"] == ["https://app.example.com"]
    assert kw.get("allow_origin_regex") is None
