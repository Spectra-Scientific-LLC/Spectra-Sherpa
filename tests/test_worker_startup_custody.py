"""Cold process startup cannot starve the loop or escape cancellation custody."""

import asyncio
import os
import threading
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest

from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool


class DelayedProcess:
    def __init__(self, process, entered, release, *, failure=None):
        self.process = process
        self.entered = entered
        self.release = release
        self.failure = failure

    def start(self):
        self.entered.set()
        if not self.release.wait(5):
            raise RuntimeError("Test safety deadline: startup blocked the event loop")
        if self.failure == "before":
            raise RuntimeError("Injected startup failure")
        self.process.start()
        if self.failure == "after":
            raise RuntimeError("Injected partial startup failure")

    def __getattr__(self, name):
        return getattr(self.process, name)


@pytest.fixture
def delayed_pool():
    pool = IsolatedWorkerPool(1)
    context = pool._context
    entered, release = threading.Event(), threading.Event()
    created = []
    faults = [None]

    def process(**kwargs):
        value = DelayedProcess(context.Process(**kwargs), entered, release, failure=faults[0])
        created.append(value)
        return value

    pool._context = SimpleNamespace(Process=process, Pipe=context.Pipe)
    try:
        yield pool, entered, release, created, faults
    finally:
        release.set()
        pool.shutdown()


async def wait_entered(event):
    async with asyncio.timeout(3):
        while not event.is_set():
            await asyncio.sleep(0.001)


def touch(path):
    Path(path).write_text("executed")
    return os.getpid()


async def invoke(pool, workflow, *, function=os.getpid, args=(), timeout=30):
    if workflow:
        async with pool.workflow():
            return await pool.run(function, *args, timeout=timeout)
    return await pool.run(function, *args, timeout=timeout)


@pytest.mark.parametrize("workflow", [False, True])
async def test_slow_start_keeps_loop_responsive_and_capacity_owned(delayed_pool, workflow):
    pool, entered, release, created, _ = delayed_pool
    task = asyncio.create_task(invoke(pool, workflow))
    try:
        await wait_entered(entered)
        await asyncio.sleep(0.02)
        assert not task.done() and pool._slots._value == 0 and len(pool._owned) == 1
        release.set()
        assert await task != os.getpid()
        assert not pool._owned and not pool._active and pool._slots._value == 1
        assert created[0].process._closed
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("workflow", [False, True])
@pytest.mark.parametrize("cancellation", ["asyncio", "anyio"])
async def test_cancel_during_start_drains_then_reaps(delayed_pool, workflow, cancellation, tmp_path):
    pool, entered, release, created, _ = delayed_pool
    scopes = []
    marker = tmp_path / "must-not-run"

    async def run():
        with anyio.CancelScope() as scope:
            scopes.append(scope)
            return await invoke(pool, workflow, function=touch, args=(str(marker),))

    task = asyncio.create_task(run())
    try:
        await wait_entered(entered)
        if cancellation == "asyncio":
            task.cancel()
            await asyncio.sleep(0.01)
            task.cancel()
        else:
            scopes[0].cancel()
        await asyncio.sleep(0.02)
        assert not task.done() and len(pool._owned) == 1 and pool._slots._value == 0
        release.set()
        if cancellation == "asyncio":
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task
            assert scopes[0].cancelled_caught
        assert not marker.exists()
        assert created[0].process._closed
        assert not pool._owned and not pool._active and pool._slots._value == 1
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("workflow", [False, True])
async def test_shutdown_during_start_waits_for_thread_then_refuses_dispatch(delayed_pool, workflow):
    pool, entered, release, created, _ = delayed_pool
    task = asyncio.create_task(invoke(pool, workflow))
    shutdown = None
    try:
        await wait_entered(entered)
        shutdown = asyncio.create_task(asyncio.to_thread(pool.shutdown))
        await asyncio.sleep(0.02)
        assert not shutdown.done()
        release.set()
        await shutdown
        with pytest.raises(RuntimeError, match="shut down|exited"):
            await task
        assert created[0].process._closed
        assert not pool._owned and not pool._active and pool._slots._value == 1
    finally:
        release.set()
        await asyncio.gather(task, *([shutdown] if shutdown else []), return_exceptions=True)


@pytest.mark.parametrize("failure", ["before", "after"])
@pytest.mark.parametrize("workflow", [False, True])
async def test_start_failure_reaps_partial_child(delayed_pool, workflow, failure):
    pool, _, release, created, faults = delayed_pool
    faults[0] = failure
    release.set()
    with pytest.raises(RuntimeError, match="Injected"):
        await invoke(pool, workflow)
    assert created[0].process._closed
    assert not pool._owned and not pool._active and pool._slots._value == 1


@pytest.mark.parametrize("workflow", [False, True])
async def test_deadline_during_start_never_dispatches_work(delayed_pool, workflow, tmp_path):
    pool, entered, release, _, _ = delayed_pool
    marker = tmp_path / "must-not-run"
    task = asyncio.create_task(invoke(pool, workflow, function=touch, args=(str(marker),), timeout=0.1))
    try:
        await wait_entered(entered)
        await asyncio.sleep(0.2)
        assert not task.done() and pool._slots._value == 0
        release.set()
        with pytest.raises(TimeoutError):
            await task
        assert not marker.exists() and not pool._owned and not pool._active
        assert pool._slots._value == 1
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("workflow", [False, True])
async def test_shutdown_before_start_thread_runs_refuses_child(delayed_pool, workflow, monkeypatch):
    pool, entered, release, _, _ = delayed_pool
    original = asyncio.to_thread
    scheduled, dispatch = asyncio.Event(), asyncio.Event()

    async def delayed(function, *args, **kwargs):
        if function.__name__ == "start":
            scheduled.set()
            await dispatch.wait()
        return await original(function, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", delayed)
    task = asyncio.create_task(invoke(pool, workflow))
    try:
        await asyncio.wait_for(scheduled.wait(), 3)
        pool.shutdown()
        dispatch.set()
        with pytest.raises(RuntimeError, match="withdrawn"):
            await task
        assert not entered.is_set() and not pool._owned and not pool._active
        assert pool._slots._value == 1
    finally:
        dispatch.set()
        release.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("workflow", [False, True])
async def test_other_worker_can_start_and_close_while_first_start_is_blocked(workflow):
    pool = IsolatedWorkerPool(2)
    context = pool._context
    entered, release = threading.Event(), threading.Event()
    created = []

    def process(**kwargs):
        real = context.Process(**kwargs)
        if not created:
            value = DelayedProcess(real, entered, release)
        else:
            value = real
        created.append(value)
        return value

    pool._context = SimpleNamespace(Process=process, Pipe=context.Pipe)
    first = asyncio.create_task(invoke(pool, workflow))
    second = None
    try:
        await wait_entered(entered)
        second = asyncio.create_task(invoke(pool, workflow))
        async with asyncio.timeout(4):
            assert await second != os.getpid()
        assert not release.is_set() and not first.done()
        assert len(pool._owned) == 1 and not pool._active and pool._slots._value == 1
        release.set()
        assert await first != os.getpid()
        assert not pool._owned and not pool._active and pool._slots._value == 2
    finally:
        release.set()
        await asyncio.gather(first, *([second] if second else []), return_exceptions=True)
        pool.shutdown()
