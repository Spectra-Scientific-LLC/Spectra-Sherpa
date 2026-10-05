"""Actual provider payload and local-history privacy/lifecycle regressions."""

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from spectra_sherpa.app.contracts.scientific_query import REFUSAL
from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.services import basic_chat, chat_exchange
from spectra_sherpa.app.services.chat_providers import ChatEndpointConfig


@pytest.fixture(autouse=True)
def local_history(monkeypatch):
    chat_exchange._records.clear()
    monkeypatch.setattr(app_config, "mode", "local")
    yield
    chat_exchange._records.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai_compatible", "anthropic", "ollama"])
async def test_actual_transport_payload_redaction_and_usage(provider, monkeypatch):
    captured = []
    config = ChatEndpointConfig(provider, "http://localhost:11434/v1", "PRIVATE-KEY", "test-model", True)
    monkeypatch.setattr(basic_chat, "get_config", lambda: config)

    async def handler(request):
        captured.append(json.loads(request.content))
        if provider == "anthropic":
            events = [
                {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
                {"type": "content_block_delta", "delta": {"text": "PCA answer PRIVATE-"}},
                {"type": "content_block_delta", "delta": {"text": "KEY"}},
                {"type": "message_delta", "usage": {"output_tokens": 3}},
            ]
        else:
            events = [
                {"choices": [{"delta": {"content": "PCA answer PRIVATE-"}}]},
                {"choices": [{"delta": {"content": "KEY"}}]},
                {"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 3}},
            ]
        return httpx.Response(200, text="\n".join("data: " + json.dumps(e) for e in events))

    client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: client(transport=httpx.MockTransport(handler), **kw))
    output = [
        chunk
        async for chunk in basic_chat.stream_chat(
            "Explain PCA",
            verbose=False,
            exchange_owner=7,
            metadata={"workflow_context": {"workflow_name": "My model", "private_extra": "NEVER-STORE"}},
        )
    ]
    assert "PCA answer" in "".join(output)
    entry = chat_exchange.history(7)[0]
    assert json.loads(entry["request"]) == captured[0]
    assert "My model" in entry["request"] and "short paragraphs" in entry["request"]
    assert "NEVER-STORE" not in json.dumps(entry)
    assert "PRIVATE-KEY" not in json.dumps(entry)
    assert entry["response"] == "PCA answer [REDACTED]"
    assert entry["status"] == "completed" and entry["duration_ms"] >= 0
    assert entry["usage"] is not None
    assert chat_exchange.history(8) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["failed", "interrupted", "refused"])
async def test_partial_failure_cancellation_refusal(outcome, monkeypatch):
    config = ChatEndpointConfig("ollama", "http://localhost/v1", "", "model", True)
    monkeypatch.setattr(basic_chat, "get_config", lambda: config)
    from spectra_sherpa.app.services.chat_providers.openai_compatible import OllamaProvider

    async def stream(*args):
        chat_exchange.observe_payload({"messages": [{"role": "user", "content": "question"}]})
        yield REFUSAL if outcome == "refused" else "partial"
        if outcome == "failed":
            raise ValueError("provider error with SECRET diagnostic")

    monkeypatch.setattr(OllamaProvider, "stream", stream)
    generator = basic_chat.stream_chat("question", exchange_owner=1)
    if outcome == "failed":
        with pytest.raises(ValueError):
            _ = [item async for item in generator]
    elif outcome == "interrupted":
        await anext(generator)
        await generator.aclose()
    else:
        _ = [item async for item in generator]
    entry = chat_exchange.history(1)[0]
    assert entry["status"] == outcome
    assert "SECRET" not in json.dumps(entry)
    assert entry["usage"] is None
    assert chat_exchange._active.get() is None


def test_retention_redaction_and_snapshot_isolation():
    for i in range(25):
        entry = chat_exchange.Exchange(1, "ollama", "model", ("configured-secret",))
        entry.payload({"messages": [{"content": 'password="private" https://user:pass@host/x?key=value'}]})
        entry.append("configured-secret" + "x" * 60_000)
        entry.finish("completed")
    entries = chat_exchange.history(1)
    assert len(entries) == 20
    assert entries[0]["truncated"]
    assert len(entries[0]["response"]) <= chat_exchange.MAX_TEXT
    text = json.dumps(entries)
    for secret in ("configured-secret", "private", "user:pass", "key=value"):
        assert secret not in text
    entries[0]["status"] = "tampered"
    assert chat_exchange.history(1)[0]["status"] == "completed"
    chat_exchange.clear(2)
    assert len(chat_exchange.history(1)) == 20
    chat_exchange.clear(1)
    assert chat_exchange.history(1) == []


@pytest.mark.parametrize(
    "header",
    [
        "authorization: bearer abc123",
        "Authorization: Basic dXNlcjpwYXNz",
        "Cookie: session=abc; csrftoken=def",
        "Set-Cookie: session=abc; Path=/; Secure",
    ],
)
def test_complete_credential_headers_removed_from_request_response_and_export(header):
    entry = chat_exchange.Exchange(1, "ollama", "model", ())
    entry.payload({"messages": [{"role": "user", "content": header + "\nExplain PCA"}]})
    midpoint = len(header) // 2
    entry.append(header[:midpoint])
    entry.append(header[midpoint:] + "\nExplain PCA")
    entry.finish("completed")
    exported = json.dumps(chat_exchange.history(1)[0])
    for secret in ("abc123", "dXNlcjpwYXNz", "session=abc", "csrftoken=def"):
        assert secret not in exported
    assert "Explain PCA" in exported


@pytest.mark.asyncio
async def test_history_route_refuses_hosted_and_remote_and_filters_user(monkeypatch):
    from spectra_sherpa.app.api.v1.routes.chat import exchanges

    def request(host):
        return Request({"type": "http", "client": (host, 1234), "headers": []})

    entry = chat_exchange.Exchange(1, "ollama", "model", ())
    entry.finish("completed")
    assert (await exchanges(request("127.0.0.1"), SimpleNamespace(id=2)))["exchanges"] == []
    with pytest.raises(HTTPException):
        await exchanges(request("8.8.8.8"), SimpleNamespace(id=1))
    monkeypatch.setattr(app_config, "mode", "enterprise")
    with pytest.raises(HTTPException):
        await exchanges(request("127.0.0.1"), SimpleNamespace(id=1))
