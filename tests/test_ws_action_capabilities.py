"""An action's declared capability is enforced before its handler runs."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from spectra_sherpa.app.services.ws_action_registry import WebSocketActionRegistry, build_default_ws_action_registry


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", [None, False, True, RuntimeError("unavailable")])
async def test_declared_capability_is_authoritative(decision):
    registry = WebSocketActionRegistry()
    handler = AsyncMock()
    registry.register("protected", handler, capability="science")
    socket = SimpleNamespace(send_json=AsyncMock())
    if decision is not None:
        authorizer = (
            AsyncMock(side_effect=decision) if isinstance(decision, Exception) else AsyncMock(return_value=decision)
        )
        registry.set_authorizer(authorizer)
    assert await registry.dispatch("protected", socket, {"project_id": 7}, "actor", None)
    if decision is True:
        handler.assert_awaited_once_with(socket, {"project_id": 7}, "actor", None)
        socket.send_json.assert_not_awaited()
    else:
        handler.assert_not_awaited()
        socket.send_json.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [False, True])
async def test_oss_chat_uses_its_configured_capability(monkeypatch, configured):
    from spectra_sherpa.app.contracts.capabilities import CHAT_ASSISTANT
    from spectra_sherpa.app.core.config import app_config

    monkeypatch.setattr(type(app_config), "to_client_safe", lambda self: {"features": {CHAT_ASSISTANT: configured}})
    registry = build_default_ws_action_registry()
    handler = AsyncMock()
    registry.register("llm_chat", handler, capability=CHAT_ASSISTANT, replace=True)
    await registry.dispatch("llm_chat", SimpleNamespace(send_json=AsyncMock()), {}, None, None)
    assert handler.await_count == int(configured)
