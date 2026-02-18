from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest

import spectra_sherpa.app.services.spectrasherpa as spectrasherpa_module
from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.services.spectrasherpa import (
    SPECTRASHERPA_API_BASE,
    get_spectrasherpa_service,
    reset_spectrasherpa_service,
    spectrasherpa_config,
)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url: str, headers: dict | None = None):
        if url.endswith("/auth/me"):
            return _FakeResponse(200, {"id": 1, "email": "alice@example.com", "username": "alice"})
        if url.endswith("/keys/llm"):
            return _FakeResponse(200, {"keys": []})
        return _FakeResponse(200, {"status": "ok"})


@pytest.fixture(autouse=True)
def _restore_runtime_state():
    tracked_env = [
        "APP_MODE",
        "EGRESS_ENABLED",
        "SPECTRASHERPA_API_URL",
        "SPECTRASHERPA_API_KEY",
    ]
    env_before = {key: os.environ.get(key) for key in tracked_env}
    mode_before = app_config.mode
    egress_before = app_config.egress_enabled
    api_url_before = spectrasherpa_config.api_base_url
    api_key_before = spectrasherpa_config.api_key

    spectrasherpa_module._service_instance = None
    yield

    app_config.mode = mode_before
    app_config.egress_enabled = egress_before
    spectrasherpa_config.api_base_url = api_url_before
    spectrasherpa_config.api_key = api_key_before
    spectrasherpa_module._service_instance = None

    for key, value in env_before.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


@pytest.mark.asyncio
async def test_reset_spectrasherpa_service_recreates_singleton():
    first = get_spectrasherpa_service()
    first.close = AsyncMock()

    await reset_spectrasherpa_service()

    first.close.assert_awaited_once()
    second = get_spectrasherpa_service()
    assert second is not first


@pytest.mark.asyncio
async def test_activate_hybrid_endpoint_updates_runtime_state(client, monkeypatch, tmp_path):
    import spectra_sherpa.app.api.v1.routes.config as config_routes

    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(config_routes, "_find_or_create_env_path", lambda: str(env_file))
    monkeypatch.setattr(config_routes.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(config_routes, "ALLOWED_SPECTRASHERPA_HOSTS", ["localhost", "127.0.0.1", "endpoint.example.com"])
    monkeypatch.setattr(
        "spectra_sherpa.app.services.spectrasherpa.reset_spectrasherpa_service",
        AsyncMock(),
    )
    monkeypatch.setattr("spectra_sherpa.app.core.startup.ensure_egress_defaults", AsyncMock())
    monkeypatch.setattr("spectra_sherpa.app.core.startup.link_hybrid_identity", AsyncMock())
    monkeypatch.setattr("spectra_sherpa.app.services.network_health.start_network_health_service", AsyncMock())

    app_config.mode = "local"
    app_config.egress_enabled = False

    response = await client.post(
        "/api/v1/config/activate-hybrid",
        json={
            "server_url": "https://endpoint.example.com",
            "api_key": "ss_test_key",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["config"]["mode"] == "hybrid"
    assert app_config.mode == "hybrid"
    assert app_config.egress_enabled is True
    assert os.environ["APP_MODE"] == "hybrid"
    assert os.environ["SPECTRASHERPA_API_URL"] == "https://endpoint.example.com/api/v1"
    assert os.environ["SPECTRASHERPA_API_KEY"] == "ss_test_key"

    env_text = env_file.read_text(encoding="utf-8")
    assert "APP_MODE='hybrid'" in env_text
    assert "SPECTRASHERPA_API_URL='https://endpoint.example.com/api/v1'" in env_text
    assert "SPECTRASHERPA_API_KEY='ss_test_key'" in env_text


@pytest.mark.asyncio
async def test_deactivate_hybrid_endpoint_clears_runtime_state(client, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_MODE=hybrid\n"
        "EGRESS_ENABLED=true\n"
        "SPECTRASHERPA_API_URL=https://endpoint.example.com/api/v1\n"
        "SPECTRASHERPA_API_KEY=ss_test_key\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "spectra_sherpa._paths.get_env_file_search_paths",
        lambda: [env_file],
    )
    monkeypatch.setattr(
        "spectra_sherpa.app.services.spectrasherpa.reset_spectrasherpa_service",
        AsyncMock(),
    )
    monkeypatch.setattr("spectra_sherpa.app.services.network_health.stop_network_health_service", AsyncMock())

    app_config.mode = "hybrid"
    app_config.egress_enabled = True
    spectrasherpa_config.api_key = "ss_test_key"
    spectrasherpa_config.api_base_url = "https://endpoint.example.com/api/v1"
    os.environ["APP_MODE"] = "hybrid"
    os.environ["EGRESS_ENABLED"] = "true"
    os.environ["SPECTRASHERPA_API_URL"] = "https://endpoint.example.com/api/v1"
    os.environ["SPECTRASHERPA_API_KEY"] = "ss_test_key"

    response = await client.post("/api/v1/config/deactivate-hybrid")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["config"]["mode"] == "local"
    assert app_config.mode == "local"
    assert app_config.egress_enabled is False
    assert spectrasherpa_config.api_key is None
    assert spectrasherpa_config.api_base_url == SPECTRASHERPA_API_BASE
    assert os.environ["APP_MODE"] == "local"
    assert os.environ["EGRESS_ENABLED"] == "false"
    assert "SPECTRASHERPA_API_KEY" not in os.environ
    assert "SPECTRASHERPA_API_URL" not in os.environ

    env_text = env_file.read_text(encoding="utf-8")
    assert "APP_MODE='local'" in env_text
    assert "EGRESS_ENABLED='false'" in env_text
    assert "SPECTRASHERPA_API_KEY=''" in env_text
    assert "SPECTRASHERPA_API_URL=''" in env_text


@pytest.mark.asyncio
async def test_spectrasherpa_test_endpoint_works_when_egress_disabled(client, monkeypatch):
    import spectra_sherpa.app.api.v1.routes.config as config_routes

    monkeypatch.setattr(config_routes.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(config_routes, "ALLOWED_SPECTRASHERPA_HOSTS", ["localhost", "127.0.0.1", "endpoint.example.com"])
    app_config.mode = "local"
    app_config.egress_enabled = False

    response = await client.post(
        "/api/v1/config/spectrasherpa/test",
        json={
            "server_url": "https://endpoint.example.com",
            "api_key": "ss_test_key",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert "error" not in payload
