import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from spectra_sherpa.app.services.ws_action_registry import WebSocketActionRegistry
from spectra_sherpa.app.services.ws_requests import RequestPolicy


@pytest.mark.asyncio
async def test_stop_is_connection_and_actor_scoped_and_interrupts_provider():
    registry = WebSocketActionRegistry()
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def handler(ws, *_):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    registry.register("chat", handler, request_policy=RequestPolicy())
    socket = SimpleNamespace(send_json=AsyncMock())
    actor = SimpleNamespace(id=7)
    payload = {"payload": {"request_id": "turn"}}
    await registry.dispatch("chat", socket, payload, actor, None, background=True)
    await started.wait()
    await registry.dispatch(
        "cancel_request", SimpleNamespace(send_json=AsyncMock()), {"request_id": "turn"}, actor, None
    )
    await registry.dispatch("cancel_request", socket, {"request_id": "turn"}, SimpleNamespace(id=8), None)
    await asyncio.sleep(0)
    assert not cancelled.is_set()
    await registry.dispatch("cancel_request", socket, {"request_id": "turn"}, actor, None)
    await asyncio.wait_for(cancelled.wait(), 1)
    await registry.requests.close(socket)
    assert socket.send_json.call_args.args[0]["code"] == "interrupted"
    assert not registry.requests.tasks


@pytest.mark.asyncio
async def test_heartbeats_do_not_extend_deadline_or_retry_and_stop_after_completion():
    registry = WebSocketActionRegistry()
    calls = 0
    cleaned = asyncio.Event()

    async def work(ws, *_):
        nonlocal calls
        calls += 1
        try:
            await ws.send_json({"type": "sherpa_tool_start", "tool_name": "validate_workflow"})
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    registry.register("chat", work, request_policy=RequestPolicy(timeout_seconds=0.08, heartbeat_seconds=0.015))
    socket = SimpleNamespace(send_json=AsyncMock())
    await registry.dispatch("chat", socket, {"payload": {"request_id": "a"}}, None, None, background=True)
    await asyncio.wait_for(cleaned.wait(), 1)
    await asyncio.sleep(0.02)
    events = [c.args[0] for c in socket.send_json.call_args_list]
    assert calls == 1
    beats = [e for e in events if e.get("payload", {}).get("heartbeat")]
    assert len(beats) >= 3
    assert all("validate_workflow" in e["payload"]["detail"] for e in beats)
    assert events[-1]["code"] == "timeout"
    count = len(events)
    await asyncio.sleep(0.03)
    assert socket.send_json.call_count == count
    assert not registry.requests.tasks


@pytest.mark.asyncio
async def test_disconnect_cancels_all_work_and_duplicate_id_does_not_dispatch():
    registry = WebSocketActionRegistry()
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def handler(*_):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    registry.register("chat", handler, request_policy=RequestPolicy())
    socket = SimpleNamespace(send_json=AsyncMock())
    payload = {"payload": {"request_id": "a"}}
    await registry.dispatch("chat", socket, payload, None, None, background=True)
    await started.wait()
    first = list(registry.requests.tasks.values())
    await registry.dispatch("chat", socket, payload, None, None, background=True)
    assert list(registry.requests.tasks.values()) == first
    await registry.requests.close(socket)
    assert stopped.is_set()
    assert not registry.requests.tasks


@pytest.mark.asyncio
async def test_capability_rejection_never_starts_background_work():
    registry = WebSocketActionRegistry()
    handler = AsyncMock()
    registry.register("chat", handler, capability="paid", request_policy=RequestPolicy())
    socket = SimpleNamespace(send_json=AsyncMock())
    await registry.dispatch("chat", socket, {"payload": {"request_id": "a"}}, None, None, background=True)
    handler.assert_not_awaited()
    assert not registry.requests.tasks
    assert socket.send_json.call_args.args[0]["detail"] == "Action capability is unavailable"
