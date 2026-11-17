"""Transport admission is narrower than arbitrary local HTTP access."""

import json

import httpx
import pytest

from spectra_sherpa.mcp import bridge_client as module

CLIENT = "fb54eea9-177d-44fa-9e34-de62b1493d59"
TOKEN = "ssmcp_" + "A" * 43


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1",
        "http://localhost:8000",
        "http://example.org",
        "http://127.0.0.1@evil.test",
        "http://127.0.0.1/other",
        "http://127.0.0.1?token=secret",
        "http://127.0.0.1:0",
    ],
)
def test_connection_never_accepts_remote_or_ambiguous_origins(url):
    with pytest.raises(ValueError):
        module.Connection(url, 1, CLIENT, TOKEN)


def test_secret_is_not_in_connection_representation():
    assert TOKEN not in repr(module.Connection("http://127.0.0.1:8001", 1, CLIENT, TOKEN))


async def test_bounded_request_and_redirect_refusal(monkeypatch):
    connection = module.Connection("http://127.0.0.1:8001", 1, CLIENT, TOKEN)
    seen = []
    original = httpx.AsyncClient

    def factory(**kwargs):
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False

        def handle(request):
            seen.append(request)
            return httpx.Response(302, headers={"location": "https://remote.example"}, text=TOKEN)

        return original(**kwargs, transport=httpx.MockTransport(handle))

    monkeypatch.setattr(module.httpx, "AsyncClient", factory)
    with pytest.raises(module.BridgeUnavailable, match="Unsupported"):
        await module.inspect(connection, "run_workflow", {})
    with pytest.raises(module.BridgeUnavailable, match="request exceeds"):
        await module.inspect(connection, "list_node_types", {"category": "a" * 8192})
    assert seen == []
    with pytest.raises(module.BridgeUnavailable) as error:
        await module.inspect(connection, "list_node_types", {})
    assert len(seen) == 1
    assert TOKEN not in str(error.value)


@pytest.mark.parametrize(
    "body,valid",
    [(json.dumps({"items": [], "next_offset": None}), True), ("a" * 65537, False), ("not-json", False), ("[]", False)],
)
async def test_response_limits(monkeypatch, body, valid):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))),
    )
    connection = module.Connection("http://127.0.0.1:8001", 1, CLIENT, TOKEN)
    if valid:
        assert await module.inspect(connection, "list_node_types", {}) == {"items": [], "next_offset": None}
    else:
        with pytest.raises(module.BridgeUnavailable):
            await module.inspect(connection, "list_node_types", {})
