"""Contract tests for local plain-HTTP assistance transports."""

from __future__ import annotations

import socket

import pytest

from spectra_sherpa.app.services import basic_chat
from spectra_sherpa.app.services.chat_providers import ChatEndpointConfig, ChatRequest, get_chat_provider
from spectra_sherpa.app.services.chat_providers.anthropic import ANTHROPIC_VERSION


def _public_dns(*_args, **_kwargs):
    return [(None, None, None, None, ("1.1.1.1", 0))]


@pytest.mark.parametrize(
    ("provider", "base_url", "request_url"),
    [
        ("openai_compatible", "https://api.openai.com/v1", "https://api.openai.com/v1/chat/completions"),
        ("openai_compatible", "https://proxy.example/v1/chat/completions", "https://proxy.example/v1/chat/completions"),
        ("anthropic", "https://api.anthropic.com", "https://api.anthropic.com/v1/messages"),
        ("anthropic", "https://api.anthropic.com/v1", "https://api.anthropic.com/v1/messages"),
        ("ollama", "http://127.0.0.1:11434/v1", "http://127.0.0.1:11434/v1/chat/completions"),
    ],
)
def test_provider_request_url_is_canonical(provider, base_url, request_url, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    ok, reason, actual = basic_chat.validated_chat_completions_url(
        base_url,
        provider=provider,
        allow_private_endpoint=provider == "ollama",
    )
    assert ok, reason
    assert actual == request_url


def test_private_endpoint_requires_explicit_config_consent(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("127.0.0.1", 0))],
    )
    blocked, _reason, _url = basic_chat.validated_chat_completions_url(
        "http://localhost:11434/v1",
        provider="ollama",
    )
    allowed, reason, url = basic_chat.validated_chat_completions_url(
        "http://localhost:11434/v1",
        provider="ollama",
        allow_private_endpoint=True,
    )
    assert blocked is False
    assert allowed is True, reason
    assert url == "http://localhost:11434/v1/chat/completions"


def test_ollama_is_configured_without_api_key(monkeypatch):
    monkeypatch.setenv("CHAT_ENDPOINT_PROVIDER", "ollama")
    monkeypatch.setenv("CHAT_ENDPOINT_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.delenv("CHAT_ENDPOINT_KEY", raising=False)
    config = basic_chat.get_config()
    assert config.provider == "ollama"
    assert config.key == ""
    assert basic_chat.is_configured() is True


def test_ollama_never_attaches_a_stale_credential():
    provider = get_chat_provider("ollama")

    assert provider._headers("old-provider-key") == {"Content-Type": "application/json"}  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_anthropic_requires_key_before_outbound_connection(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", _public_dns)
    ok, message = await basic_chat.test_connection(
        "https://api.anthropic.com",
        "",
        "claude-sonnet-4-6",
        provider="anthropic",
    )
    assert ok is False
    assert message == "API key is required."


def test_anthropic_request_contract_uses_native_headers_and_messages_shape():
    provider = get_chat_provider("anthropic")
    config = ChatEndpointConfig(
        provider="anthropic",
        url="https://api.anthropic.com",
        key="secret-key",
        model="claude-sonnet-4-6",
    )
    request = ChatRequest(
        message="Summarize this score plot.",
        verbose=False,
        max_paragraphs=2,
        metadata={"workflow_context": {"workflow_name": "nir-calibration"}},
    )
    headers = provider._headers(config.key)  # type: ignore[attr-defined]
    body = provider._body(config, request, stream=True)  # type: ignore[attr-defined]
    assert headers == {
        "x-api-key": "secret-key",
        "anthropic-version": ANTHROPIC_VERSION,
        "content-type": "application/json",
    }
    assert body["messages"] == [{"role": "user", "content": "Summarize this score plot."}]
    assert body["stream"] is True
    assert "system" in body
    assert "nir-calibration" in body["system"]


def test_anthropic_sse_error_is_not_silently_ignored():
    provider = get_chat_provider("anthropic")

    with pytest.raises(ValueError, match="Chat endpoint streaming error"):
        provider._text_delta({"type": "error", "error": {"type": "overloaded_error"}})  # type: ignore[attr-defined]
