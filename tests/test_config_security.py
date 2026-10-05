from __future__ import annotations

import socket

import pytest
from dotenv import dotenv_values
from fastapi import HTTPException

from spectra_sherpa.app.api.v1.routes import config
from spectra_sherpa.app.core import mode_policy
from spectra_sherpa.app.services import basic_chat


def test_spectrasherpa_url_allows_https_public_cloud_host(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: [(None, None, None, None, ("1.1.1.1", 0))])
    assert config._is_allowed_url("https://cloud.spectrascientific.com")
    assert config._is_allowed_url("https://cloud.spectrascientific.com/api/v1")


def test_spectrasherpa_url_blocks_untrusted_private_and_plain_http_targets() -> None:
    assert not config._is_allowed_url("http://cloud.spectrascientific.com")
    assert not config._is_allowed_url("https://192.168.1.100")
    assert not config._is_allowed_url("https://169.254.169.254")


def test_spectrasherpa_url_blocks_hostname_that_resolves_private(monkeypatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: [(None, None, None, None, ("127.0.0.1", 0))])
    assert not config._is_allowed_url("https://ssrf.example.com")


def test_byo_chat_config_is_read_at_request_time(monkeypatch) -> None:
    monkeypatch.setenv("CHAT_ENDPOINT_URL", "https://example.test/v1")
    monkeypatch.setenv("CHAT_ENDPOINT_KEY", "test-key")
    monkeypatch.setenv("CHAT_ENDPOINT_MODEL", "test-model")

    runtime_config = basic_chat.get_config()

    assert runtime_config.url == "https://example.test/v1"
    assert runtime_config.key == "test-key"
    assert runtime_config.model == "test-model"
    assert basic_chat.is_configured()


@pytest.mark.asyncio
async def test_save_byo_chat_config_validates_url_before_persisting(monkeypatch) -> None:
    monkeypatch.setattr(config, "_can_manage_byo_chat", lambda _request: True)
    monkeypatch.setattr(mode_policy, "is_local", lambda: True)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: [(None, None, None, None, ("127.0.0.1", 0))])

    request = config.ByoChatConfigRequest(
        endpoint_url="https://ssrf.example.com/v1",
        endpoint_key="sk-test",
        model="test-model",
    )

    with pytest.raises(HTTPException) as exc_info:
        await config.save_byo_chat_config(request, object(), user=object())

    assert exc_info.value.status_code == 400
    assert "private" in str(exc_info.value.detail).lower() or "restricted" in str(exc_info.value.detail).lower()


@pytest.mark.asyncio
async def test_save_byo_chat_config_does_not_reuse_key_across_provider_families(monkeypatch) -> None:
    monkeypatch.setattr(config, "_can_manage_byo_chat", lambda _request: True)
    monkeypatch.setattr(mode_policy, "is_local", lambda: True)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: [(None, None, None, None, ("1.1.1.1", 0))])
    monkeypatch.setenv("CHAT_ENDPOINT_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CHAT_ENDPOINT_KEY", "existing-openai-family-key")

    request = config.ByoChatConfigRequest(
        provider="anthropic",
        endpoint_url="https://api.anthropic.com",
        endpoint_key="",
        model="claude-sonnet-4-6",
    )

    with pytest.raises(HTTPException) as exc_info:
        await config.save_byo_chat_config(request, object(), user=object())

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "endpoint_key is required."


@pytest.mark.asyncio
async def test_save_byo_chat_config_does_not_reuse_key_across_endpoints_in_one_transport(monkeypatch) -> None:
    monkeypatch.setattr(config, "_can_manage_byo_chat", lambda _request: True)
    monkeypatch.setattr(mode_policy, "is_local", lambda: True)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: [(None, None, None, None, ("1.1.1.1", 0))])
    monkeypatch.setenv("CHAT_ENDPOINT_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CHAT_ENDPOINT_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("CHAT_ENDPOINT_KEY", "deepseek-key")

    request = config.ByoChatConfigRequest(
        provider="openai_compatible",
        endpoint_url="https://api.openai.com/v1",
        endpoint_key="",
        model="gpt-4o-mini",
    )

    with pytest.raises(HTTPException) as exc_info:
        await config.save_byo_chat_config(request, object(), user=object())

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "endpoint_key is required."


@pytest.mark.asyncio
async def test_switching_to_keyless_provider_clears_stale_key(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(config, "_can_manage_byo_chat", lambda _request: True)
    monkeypatch.setattr(mode_policy, "is_local", lambda: True)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: [(None, None, None, None, ("1.1.1.1", 0))])
    monkeypatch.setattr(config, "_find_or_create_env_path", lambda: tmp_path / ".env")
    monkeypatch.setenv("CHAT_ENDPOINT_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CHAT_ENDPOINT_KEY", "existing-openai-family-key")

    request = config.ByoChatConfigRequest(
        provider="ollama",
        endpoint_url="https://ollama.example/v1",
        endpoint_key="",
        model="llama3.2",
    )

    response = await config.save_byo_chat_config(request, object(), user=object())

    assert response == {"success": True, "configured": True}
    assert dotenv_values(tmp_path / ".env")["CHAT_ENDPOINT_KEY"] == ""
    assert basic_chat.get_config().key == ""


@pytest.mark.asyncio
async def test_test_byo_chat_config_does_not_reuse_key_across_provider_families(monkeypatch) -> None:
    monkeypatch.setattr(config, "_can_manage_byo_chat", lambda _request: True)
    monkeypatch.setattr(mode_policy, "is_local", lambda: True)
    monkeypatch.setenv("CHAT_ENDPOINT_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CHAT_ENDPOINT_KEY", "existing-openai-family-key")
    captured: dict[str, str] = {}

    async def fake_test_connection(_url, endpoint_key, _model, **_kwargs):
        captured["key"] = endpoint_key
        return False, "API key is required."

    monkeypatch.setattr(basic_chat, "test_connection", fake_test_connection)
    request = config.ByoChatConfigRequest(
        provider="anthropic",
        endpoint_url="https://api.anthropic.com",
        endpoint_key="",
        model="claude-sonnet-4-6",
    )

    response = await config.test_byo_chat_config(request, object(), user=object())

    assert captured["key"] == ""
    assert response == {"success": False, "message": "API key is required."}


@pytest.mark.asyncio
async def test_test_byo_chat_config_does_not_reuse_key_across_endpoints_in_one_transport(monkeypatch) -> None:
    monkeypatch.setattr(config, "_can_manage_byo_chat", lambda _request: True)
    monkeypatch.setattr(mode_policy, "is_local", lambda: True)
    monkeypatch.setenv("CHAT_ENDPOINT_PROVIDER", "openai_compatible")
    monkeypatch.setenv("CHAT_ENDPOINT_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("CHAT_ENDPOINT_KEY", "deepseek-key")
    captured: dict[str, str] = {}

    async def fake_test_connection(_url, endpoint_key, _model, **_kwargs):
        captured["key"] = endpoint_key
        return False, "API key is required."

    monkeypatch.setattr(basic_chat, "test_connection", fake_test_connection)
    request = config.ByoChatConfigRequest(
        provider="openai_compatible",
        endpoint_url="https://api.openai.com/v1",
        endpoint_key="",
        model="gpt-4o-mini",
    )

    response = await config.test_byo_chat_config(request, object(), user=object())

    assert captured["key"] == ""
    assert response == {"success": False, "message": "API key is required."}
