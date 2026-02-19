from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import APIRouter, FastAPI

import spectra_sherpa.app.main as app_main
from spectra_sherpa.app.api.v1 import api as api_v1


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
    assert not any(path.startswith("/auth") for path in paths)
    assert not any(path.startswith("/admin") for path in paths)


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


def test_build_api_router_exposes_auth_me_when_server_routes_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("spectra_sherpa.app.api.v1.api.get_server_routers", lambda: [])

    router = api_v1.build_api_router(include_server_routers=True)

    assert "/auth/me" in _paths(router.routes)


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
    monkeypatch.setattr(app_main, "configure_logging", _sync_event(events, "configure_logging"))
    monkeypatch.setattr(app_main, "validate_security_settings", _sync_event(events, "validate_security_settings"))
    monkeypatch.setattr(app_main, "validate_concurrency_settings", _sync_event(events, "validate_concurrency_settings"))
    monkeypatch.setattr(app_main, "ensure_data_dirs", _sync_event(events, "ensure_data_dirs"))
    monkeypatch.setattr(app_main, "_try_leader_lock", lambda: True)

    # Startup async phase
    monkeypatch.setattr(app_main, "ensure_database_ready", _async_event(events, "ensure_database_ready"))
    monkeypatch.setattr(app_main, "ensure_default_user", _async_event(events, "ensure_default_user"))
    monkeypatch.setattr(app_main, "ensure_egress_defaults", _async_event(events, "ensure_egress_defaults"))
    monkeypatch.setattr(app_main, "link_hybrid_identity", _async_event(events, "link_hybrid_identity"))
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
    monkeypatch.setattr(
        "spectra_sherpa.app.services.spectrasherpa.close_spectrasherpa_service",
        _async_event(events, "close_spectrasherpa_service"),
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.services.sherpa_advisor.close_sherpa_advisor",
        _async_event(events, "close_sherpa_advisor"),
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
