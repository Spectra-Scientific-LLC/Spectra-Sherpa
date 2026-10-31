import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from spectra_sherpa.app.services.ws_action_registry import WebSocketActionRegistry
from spectra_sherpa.app.services.ws_requests import RequestPolicy


def report_late_request_failure(task):
    if not task.cancelled():
        error = task.exception()
        if error is not None:
            task.get_loop().call_exception_handler(
                {"message": "Late failure after WebSocket cleanup deadline", "exception": error, "task": task}
            )


@asynccontextmanager
async def owned_requests(registry, cleanup_timeout=5):
    """Own observed operations and this registry's requests, never other tests' tasks."""
    observed = set()

    async def observe(awaitable, timeout=5):
        task = asyncio.ensure_future(awaitable)
        observed.add(task)
        done, _ = await asyncio.wait({task}, timeout=timeout)
        if not done:
            raise TimeoutError("WebSocket test operation did not complete")
        observed.discard(task)
        return task.result()

    try:
        yield observe
    finally:
        tasks = observed | {task for _, task in registry.requests.tasks.values()}
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=cleanup_timeout)
            errors = []
            for task in done:
                if not task.cancelled():
                    error = task.exception()
                    if error is not None:
                        errors.append(error)
            if pending:
                for task in pending:
                    task.add_done_callback(report_late_request_failure)
                errors.append(TimeoutError("Owned WebSocket tasks did not settle after cancellation"))
            if errors:
                raise BaseExceptionGroup("WebSocket test cleanup failed", errors)


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
    async with owned_requests(registry) as observe:
        await observe(registry.dispatch("chat", socket, payload, actor, None, background=True))
        await observe(started.wait())
        await observe(
            registry.dispatch(
                "cancel_request", SimpleNamespace(send_json=AsyncMock()), {"request_id": "turn"}, actor, None
            )
        )
        await observe(registry.dispatch("cancel_request", socket, {"request_id": "turn"}, SimpleNamespace(id=8), None))
        await asyncio.sleep(0)
        assert not cancelled.is_set()
        await observe(registry.dispatch("cancel_request", socket, {"request_id": "turn"}, actor, None))
        await observe(cancelled.wait(), timeout=1)
        await observe(registry.requests.close(socket))
        assert socket.send_json.call_args.args[0]["code"] == "interrupted"
        assert not registry.requests.tasks


@pytest.mark.asyncio
async def test_heartbeats_do_not_extend_deadline_or_retry_and_stop_after_completion(monkeypatch):
    registry = WebSocketActionRegistry()
    calls = 0
    cleaned = asyncio.Event()
    three_beats = asyncio.Event()
    deadline_handles = []
    real_timeout = asyncio.timeout

    def capture_timeout(seconds):
        handle = real_timeout(seconds)
        deadline_handles.append((handle, handle.when()))
        return handle

    monkeypatch.setattr(asyncio, "timeout", capture_timeout)
    beat_count = 0

    async def record_event(event):
        nonlocal beat_count
        if event.get("payload", {}).get("heartbeat"):
            beat_count += 1
            if beat_count == 3:
                three_beats.set()

    async def work(ws, *_):
        nonlocal calls
        calls += 1
        try:
            await ws.send_json({"type": "sherpa_tool_start", "tool_name": "validate_workflow"})
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    registry.register("chat", work, request_policy=RequestPolicy(timeout_seconds=60, heartbeat_seconds=0.01))
    socket = SimpleNamespace(send_json=AsyncMock(side_effect=record_event))
    async with owned_requests(registry) as observe:
        await observe(registry.dispatch("chat", socket, {"payload": {"request_id": "a"}}, None, None, background=True))
        # Synchronize on events instead of assuming a loaded CI runner schedules
        # three heartbeats inside an 80 ms wall-clock window.
        await observe(three_beats.wait())
        assert len(deadline_handles) == 1
        deadline, original_when = deadline_handles[0]
        assert deadline.when() == original_when
        assert not cleaned.is_set()
        task = next(iter(registry.requests.tasks.values()))[1]
        # Expire the real asyncio deadline after observing the unchanged deadline.
        deadline.reschedule(asyncio.get_running_loop().time())
        await observe(task)
        assert cleaned.is_set()
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
    async with owned_requests(registry) as observe:
        await observe(registry.dispatch("chat", socket, payload, None, None, background=True))
        await observe(started.wait())
        first = list(registry.requests.tasks.values())
        await observe(registry.dispatch("chat", socket, payload, None, None, background=True))
        assert list(registry.requests.tasks.values()) == first
        await observe(registry.requests.close(socket))
        assert stopped.is_set()
        assert not registry.requests.tasks


@pytest.mark.asyncio
async def test_capability_rejection_never_starts_background_work():
    registry = WebSocketActionRegistry()
    handler = AsyncMock()
    registry.register("chat", handler, capability="paid", request_policy=RequestPolicy())
    socket = SimpleNamespace(send_json=AsyncMock())
    async with owned_requests(registry) as observe:
        await observe(registry.dispatch("chat", socket, {"payload": {"request_id": "a"}}, None, None, background=True))
        handler.assert_not_awaited()
        assert not registry.requests.tasks
        assert socket.send_json.call_args.args[0]["detail"] == "Action capability is unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["readiness", "assertion"])
async def test_owned_request_failure_cleans_handler_and_heartbeat_but_not_unrelated_task(failure):
    registry = WebSocketActionRegistry()
    stopped, beat_seen = asyncio.Event(), asyncio.Event()
    heartbeat_tasks = set()

    async def handler(*_):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    async def record(event):
        if event.get("payload", {}).get("heartbeat"):
            heartbeat_tasks.add(asyncio.current_task())
            beat_seen.set()

    registry.register("chat", handler, request_policy=RequestPolicy(heartbeat_seconds=0.01))
    socket = SimpleNamespace(send_json=AsyncMock(side_effect=record))
    unrelated = asyncio.create_task(asyncio.sleep(5))
    try:
        expected = TimeoutError if failure == "readiness" else AssertionError
        with pytest.raises(expected):
            async with owned_requests(registry) as observe:
                await observe(registry.dispatch("chat", socket, {"request_id": "failure"}, None, None, background=True))
                request = next(iter(registry.requests.tasks.values()))[1]
                await observe(beat_seen.wait())
                if failure == "readiness":
                    await observe(asyncio.Event().wait(), timeout=0.05)
                else:
                    raise AssertionError("injected assertion failure")
        assert stopped.is_set()
        assert request.done()
        assert heartbeat_tasks and all(task.done() for task in heartbeat_tasks)
        assert not registry.requests.tasks
        assert not unrelated.done()
        count = socket.send_json.call_count
        await asyncio.sleep(0.03)
        assert socket.send_json.call_count == count
    finally:
        unrelated.cancel()
        done, pending = await asyncio.wait({unrelated}, timeout=1)
        assert done and not pending


@pytest.mark.asyncio
async def test_observation_timeout_does_not_itself_cancel_a_live_request():
    registry = WebSocketActionRegistry()
    started, release, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def handler(*_):
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    registry.register("chat", handler, request_policy=RequestPolicy())
    socket = SimpleNamespace(send_json=AsyncMock())
    async with owned_requests(registry) as observe:
        await observe(registry.dispatch("chat", socket, {"request_id": "observe"}, None, None, background=True))
        await observe(started.wait())
        task = next(iter(registry.requests.tasks.values()))[1]
        with pytest.raises(TimeoutError):
            await observe(task, timeout=0.05)
        assert not task.done() and not task.cancelling() and not cancelled.is_set()
        release.set()
        await observe(task)
    assert not cancelled.is_set()
    assert not registry.requests.tasks


@pytest.mark.asyncio
async def test_close_timeout_reports_resistant_owned_tasks_and_finite_fixture_can_release_them():
    registry = WebSocketActionRegistry()
    started, release, stopping = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def handler(*_):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopping.set()
            # Model a cancellation-resistant cleanup with an independent finite
            # escape hatch. Do not let a broken test observer hang this proof.
            while not release.is_set():
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    pass

    registry.register("chat", handler, request_policy=RequestPolicy())
    socket = SimpleNamespace(send_json=AsyncMock())
    escape = asyncio.get_running_loop().call_later(5, release.set)
    request = close = None
    try:
        with pytest.raises(ExceptionGroup) as caught:
            async with owned_requests(registry, cleanup_timeout=0.05) as observe:
                await observe(
                    registry.dispatch("chat", socket, {"request_id": "resistant"}, None, None, background=True)
                )
                await observe(started.wait())
                request = next(iter(registry.requests.tasks.values()))[1]
                close = asyncio.create_task(registry.requests.close(socket))
                await observe(close, timeout=0.05)
        assert caught.value.subgroup(TimeoutError) is not None
        assert stopping.is_set()
        assert not request.done()
    finally:
        release.set()
        tasks = {task for task in (request, close) if task is not None}
        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=2)
            assert not pending
            for task in done:
                if not task.cancelled():
                    task.result()
        escape.cancel()
    assert not registry.requests.tasks


@pytest.mark.asyncio
async def test_late_observed_operation_error_is_reported_after_cleanup_deadline():
    registry = WebSocketActionRegistry()
    loop = asyncio.get_running_loop()
    old_handler = loop.get_exception_handler()
    release, reported = asyncio.Event(), asyncio.Event()
    errors = []

    def record_error(_loop, context):
        errors.append(context)
        reported.set()

    async def delayed_failure():
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
            raise ValueError("late WebSocket operation cleanup failure")

    task = asyncio.create_task(delayed_failure())
    escape = loop.call_later(5, release.set)
    loop.set_exception_handler(record_error)
    try:
        with pytest.raises(ExceptionGroup) as caught:
            async with owned_requests(registry, cleanup_timeout=0.05) as observe:
                await observe(task, timeout=0.05)
        assert caught.value.subgroup(TimeoutError) is not None
        release.set()
        done, pending = await asyncio.wait({task}, timeout=1)
        assert not pending
        # Done callbacks run on the next loop turn; do not infer reporting from
        # task completion alone.
        async with owned_requests(registry) as observe:
            await observe(reported.wait(), timeout=1)
        assert len(errors) == 1
        assert errors[0]["task"] is task
        assert isinstance(errors[0]["exception"], ValueError)
        assert "WebSocket cleanup deadline" in errors[0]["message"]
    finally:
        release.set()
        done, pending = await asyncio.wait({task}, timeout=2)
        escape.cancel()
        loop.set_exception_handler(old_handler)
        assert not pending
        for finished in done:
            if not finished.cancelled():
                finished.exception()
