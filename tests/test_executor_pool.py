"""Tests for ProcessPoolExecutor offloading in the DAG executor."""

from __future__ import annotations

import asyncio
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from contextvars import Context
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock

import numpy as np
import pytest

# Import node modules to trigger @register_node decorators
import spectra_sherpa.app.services.dag.nodes.data  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
from spectra_sherpa.app.services.dag.executor import (
    DAGExecutor,
    WorkflowEdge,
    WorkflowNode,
    _run_node_in_worker,
    set_default_pool,
)
from spectra_sherpa.app.services.dag.executor_pool import WorkerExecutionContext
from spectra_sherpa.app.services.dag.node_base import NodeResult, node_registry, resolved_runtime_worker_capabilities
from spectra_sherpa.core.execution_runtime import ExecutionRuntime

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snv_workflow(executor: DAGExecutor) -> str:
    """Add an exact-file source -> SNV workflow with injected source bytes."""
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

    executor.add_node(
        WorkflowNode(
            node_id="src",
            node_type="data.file_load",
            parameters={"experiment_id": 1, "file_id": 1},
        )
    )
    executor.add_node(
        WorkflowNode(
            node_id="snv",
            node_type="preprocess.normalize",
            parameters={"method": "snv"},
        )
    )
    executor.add_edge(
        WorkflowEdge(
            from_node="src",
            to_node="snv",
            from_output="default",
            to_input="default",
        )
    )
    executor.inject_result("src", SherpaDataset(X=np.random.default_rng(42).normal(size=(10, 50))))
    return "snv"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRunNodeInWorker:
    """Test the top-level worker function directly."""

    def test_snv_in_worker(self, tmp_path):
        """A preprocessing node can execute in a fresh worker context."""
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        ds = SherpaDataset(X=np.random.default_rng(42).normal(size=(10, 50)))
        result = _run_node_in_worker(
            node_type="preprocess.normalize",
            node_id="snv_w",
            parameters={"method": "snv"},
            args=(),
            kwargs={"default": ds},
            worker_context=WorkerExecutionContext(
                execution_id="snv-worker-test",
                runtime=ExecutionRuntime(),
                capabilities=("read_dataset",),
            ),
        )
        assert isinstance(result, NodeResult)
        out = result.outputs
        if isinstance(out, dict) and "default" in out:
            out = out["default"]
        assert hasattr(out, "shape")
        assert out.shape == (10, 50)

    def test_runtime_capability_request_cannot_expand_immutable_authority(self, monkeypatch) -> None:
        """A hostile node override cannot manufacture artifact-read authority."""

        node = node_registry.create_node("model.fitted_pls", "hostile-capability-request", {"n_components": 1})
        monkeypatch.setattr(node, "requires_worker_capability_at_runtime", lambda _capability: True)

        assert resolved_runtime_worker_capabilities(node) == ("read_dataset",)
        context = DAGExecutor(process_pool=False)._worker_context(node)
        assert context.capabilities == ("read_dataset",)
        assert context.runtime.canonical_artifact_reader is None
        assert context.runtime.model_artifact_reader is None

    def test_worker_projection_strips_write_authority_and_runtime_is_frozen(self) -> None:
        """A worker receives only admitted reads and cannot mutate its authority."""

        reader = MagicMock()
        writer = MagicMock()
        runtime = ExecutionRuntime(
            model_artifact_writer=writer,
            worker_model_artifact_reader=reader,
        )

        projected = runtime.for_worker(("read_model_artifact",))

        assert projected.model_artifact_reader is reader
        assert projected.model_artifact_writer is None
        assert projected.worker_model_artifact_reader is None
        with pytest.raises(FrozenInstanceError):
            projected.model_artifact_writer = writer  # type: ignore[misc]

    @pytest.mark.asyncio
    async def test_missing_artifact_capability_fails_before_node_execution(self, monkeypatch) -> None:
        node = node_registry.create_node("model.load_apply", "missing-authority", {"model_id": "model-1"})
        executed = False

        async def _must_not_execute(*args, **kwargs):
            nonlocal executed
            del args, kwargs
            executed = True
            raise AssertionError("node execution started without admitted authority")

        monkeypatch.setattr(node, "execute", _must_not_execute)
        executor = DAGExecutor(process_pool=None)
        executor.nodes[node.node_id] = node
        with pytest.raises(PermissionError, match="model-artifact read capability is unavailable"):
            await executor._run_one_node(
                node,
                [],
                {"X_new": np.ones((1, 2))},
                30.0,
            )
        assert executed is False


class TestShouldOffload:
    """Test the offload decision logic."""

    def test_no_pool_never_offloads(self):
        executor = DAGExecutor(process_pool=None)
        executor.add_node(WorkflowNode("snv", "preprocess.normalize", {"method": "snv"}))
        assert executor._should_offload(executor.nodes["snv"]) is False

    def test_data_node_stays_in_process(self):
        pool = MagicMock(spec=ProcessPoolExecutor)
        executor = DAGExecutor(process_pool=pool)
        executor.add_node(WorkflowNode("src", "data.file_load", {"experiment_id": 1, "file_id": 1}))
        assert executor._should_offload(executor.nodes["src"]) is False

    def test_preprocessing_offloads(self):
        pool = MagicMock(spec=ProcessPoolExecutor)
        executor = DAGExecutor(process_pool=pool)
        executor.add_node(WorkflowNode("snv", "preprocess.normalize", {"method": "snv"}))
        assert executor._should_offload(executor.nodes["snv"]) is True

    def test_modeling_offloads(self):
        pool = MagicMock(spec=ProcessPoolExecutor)
        executor = DAGExecutor(process_pool=pool)
        executor.add_node(WorkflowNode("km", "model.kmeans", {"n_clusters": 2}))
        assert executor._should_offload(executor.nodes["km"]) is True


class TestSanitizeForPool:
    """Test fail-closed scientific transport before pool dispatch."""

    def test_analysis_dataset_passes_through(self):
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        ds = SherpaDataset(X=np.ones((3, 5)))
        result = DAGExecutor._sanitize_for_pool(ds)
        assert result is ds  # same object, not copied

    def test_plain_value_passes_through(self):
        assert DAGExecutor._sanitize_for_pool(42) == 42
        assert DAGExecutor._sanitize_for_pool("hello") == "hello"

    def test_nddataset_rejected(self):
        """If SCP is installed, NDDataset is rejected at pool boundary."""
        from tests._optional_scp import HAS_SCP

        if not HAS_SCP:
            pytest.skip("SpectroChemPy not installed")
        import spectrochempy as scp

        nds = scp.NDDataset(np.random.default_rng(0).normal(size=(5, 10)))
        with pytest.raises(TypeError, match="NDDataset reached process-pool submission"):
            DAGExecutor._sanitize_for_pool(nds)


class TestDefaultPool:
    """Test the module-level default pool mechanism."""

    def test_default_pool_used_when_no_explicit_pool(self):
        pool = MagicMock(spec=ProcessPoolExecutor)
        set_default_pool(pool)
        try:
            executor = DAGExecutor()
            assert executor._process_pool is pool
        finally:
            set_default_pool(None)

    def test_explicit_pool_overrides_default(self):
        default = MagicMock(spec=ProcessPoolExecutor)
        explicit = MagicMock(spec=ProcessPoolExecutor)
        set_default_pool(default)
        try:
            executor = DAGExecutor(process_pool=explicit)
            assert executor._process_pool is explicit
        finally:
            set_default_pool(None)

    def test_no_pool_when_cleared(self):
        set_default_pool(None)
        executor = DAGExecutor()
        assert executor._process_pool is None


def _shutdown_legacy_test_pool(pool):
    from multiprocessing.connection import wait

    # Python 3.11's executor has no public terminate-workers API. These are
    # ONLY this test fixture's handles, not multiprocessing.active_children().
    pending = tuple(pool._pending_work_items.values())
    abandoned = any(not item.future.done() for item in pending)
    workers = tuple((pool._processes or {}).values()) if abandoned else ()
    try:
        for worker in workers:
            worker.terminate()
        for worker in workers:
            # The executor manager owns join/waitpid. Concurrent is_alive/join
            # can see ECHILD before that thread publishes the exit status.
            # Sentinels observe exit without competing to reap the process.
            if not wait([worker.sentinel], timeout=5):
                worker.kill()
                assert wait([worker.sentinel], timeout=5), "Owned legacy test worker did not stop"
    finally:
        # Cancelling a Future does not stop running work. Keep actual executor
        # shutdown, after stopping abandoned workers rather than wait=False.
        pool.shutdown(wait=True, cancel_futures=abandoned)
    for worker in workers:
        assert not worker.is_alive() and worker.exitcode is not None, "Owned legacy test worker was not reaped"


async def _finish_owned_pool_tasks(pool, *tasks):
    owned = [task for task in tasks if task is not None]
    try:
        for task in owned:
            if not task.done():
                task.cancel()
        if owned:
            await asyncio.gather(*owned, return_exceptions=True)
    finally:
        pool.shutdown()


@pytest.mark.asyncio
class TestPoolExecution:
    """Integration tests: run workflows with a real ProcessPoolExecutor."""

    @staticmethod
    def _create_pool(max_workers: int) -> ProcessPoolExecutor:
        """Create a process pool or skip when the runtime lacks semaphore support."""
        try:
            return ProcessPoolExecutor(
                max_workers=max_workers,
                mp_context=multiprocessing.get_context("spawn"),
            )
        except (NotImplementedError, PermissionError, OSError) as exc:
            pytest.skip(f"ProcessPoolExecutor unavailable in this environment: {exc}")

    @pytest.fixture()
    def pool(self):
        p = self._create_pool(max_workers=2)
        yield p
        _shutdown_legacy_test_pool(p)

    async def test_workflow_with_pool_matches_in_process(self, pool, patch_eigenvector_loader):
        """Results from pool execution must match in-process execution."""
        # In-process run
        exec_ip = DAGExecutor(process_pool=None)
        _make_snv_workflow(exec_ip)
        results_ip = await exec_ip.execute()

        # Pool run
        exec_pool = DAGExecutor(process_pool=pool)
        _make_snv_workflow(exec_pool)
        results_pool = await exec_pool.execute()

        # Both should have the same node IDs
        assert set(results_ip.keys()) == set(results_pool.keys())

        # SNV output should be numerically identical
        def _get_data(result_dict, key):
            val = result_dict[key]
            if isinstance(val, dict) and "default" in val:
                val = val["default"]
            return np.asarray(val.data if hasattr(val, "data") else val)

        ip_data = _get_data(results_ip, "snv")
        pool_data = _get_data(results_pool, "snv")
        np.testing.assert_array_almost_equal(ip_data, pool_data)

    async def test_data_node_runs_in_process_with_pool(self, pool):
        """Data source nodes should execute in-process even with a pool."""
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        executor = DAGExecutor(process_pool=pool)
        executor.add_node(WorkflowNode("src", "data.file_load", {"experiment_id": 1, "file_id": 1}))
        executor.inject_result("src", SherpaDataset(X=np.ones((3, 4))))
        results = await executor.execute()
        assert "src" in results

    async def test_execute_node_uses_pool(self, pool, patch_eigenvector_loader):
        """execute_node() should also offload to the pool."""
        executor = DAGExecutor(process_pool=pool)
        _make_snv_workflow(executor)
        results = await executor.execute_node("snv")
        assert "snv" in results

    async def test_broken_pool_never_falls_back(self, patch_eigenvector_loader):
        """A broken pool must not execute scientific work in the API process."""
        # Use a pool that's already been shut down (simulates broken pool)
        broken = self._create_pool(max_workers=1)
        broken.shutdown(wait=True)

        executor = DAGExecutor(process_pool=broken)
        _make_snv_workflow(executor)
        with pytest.raises(ValueError, match="after shutdown"):
            await executor.execute()


def _slow_worker(started, finished):
    import os
    import time
    from pathlib import Path

    Path(started).write_text(str(os.getpid()))
    time.sleep(60)
    Path(finished).write_text("unexpected completion")


def _crash_worker():
    import os

    os._exit(17)


@pytest.mark.asyncio
async def test_isolated_worker_timeout_reaps_and_releases_capacity(tmp_path):
    import os

    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

    pool = IsolatedWorkerPool(1)
    started, finished = tmp_path / "started", tmp_path / "finished"
    try:
        with pytest.raises(TimeoutError):
            await pool.run(_slow_worker, str(started), str(finished), timeout=10)
        assert started.exists(), "The test must time out a running child, not merely its startup"
        assert int(started.read_text()) not in [p.pid for p in multiprocessing.active_children()]
        assert not finished.exists()
        assert not pool._active
        # A fresh request can immediately use the only capacity slot.
        pid = await pool.run(os.getpid, timeout=30)
        assert pid != os.getpid()
    finally:
        pool.shutdown()


@pytest.mark.asyncio
async def test_cancelling_one_isolated_worker_preserves_other_request(tmp_path):
    import asyncio
    import os

    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

    pool = IsolatedWorkerPool(2)
    started, finished = tmp_path / "started", tmp_path / "finished"
    task = asyncio.create_task(pool.run(_slow_worker, str(started), str(finished), timeout=60))
    other = None
    try:
        async with asyncio.timeout(30):
            while not started.exists():
                await asyncio.sleep(0.02)
        other = asyncio.create_task(pool.run(os.getpid, timeout=30))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await other != os.getpid()
        assert not finished.exists()
        assert not pool._active
    finally:
        await _finish_owned_pool_tasks(pool, task, other)


@pytest.mark.asyncio
async def test_isolated_worker_crash_and_serialization_failure_do_not_retry_locally():
    import os

    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

    pool = IsolatedWorkerPool(1)
    try:
        with pytest.raises(RuntimeError, match="exited without a result"):
            await pool.run(_crash_worker, timeout=30)
        with pytest.raises((AttributeError, TypeError), match="pickle|local object"):
            await pool.run(lambda: None, timeout=30)
        assert await pool.run(os.getpid, timeout=30) != os.getpid()
    finally:
        pool.shutdown()


@pytest.mark.asyncio
async def test_isolated_scientific_node_matches_local_result():
    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

    pool = IsolatedWorkerPool(1)
    try:
        executor = DAGExecutor(process_pool=pool)
        _make_snv_workflow(executor)
        result = await executor.execute_node("snv")
        assert "snv" in result
        assert executor.diagnostics["snv"]["worker_execution"]["mode"] == "spawned_worker"
    finally:
        pool.shutdown()


@pytest.mark.parametrize("method", ["spawn", "forkserver"] if __import__("sys").platform == "linux" else ["spawn"])
def test_isolated_worker_cannot_outlive_abrupt_backend_exit(tmp_path, method):
    """stdout stays inherited by the worker: communicate reaches EOF only when
    both backend and worker have exited, including on Windows without kill(0).
    """
    import os
    import subprocess
    import sys
    from pathlib import Path

    import spectra_sherpa

    script = tmp_path / "owned_worker.py"
    script.write_text(
        """
import multiprocessing, os, time
from spectra_sherpa.app.services.dag.executor_pool import _isolated_call

def slow_analysis(ready):
    ready.send(True)
    time.sleep(45)

if __name__ == '__main__':
    multiprocessing.set_forkserver_preload(['spectra_sherpa.worker_preload'])
    context = multiprocessing.get_context('METHOD')
    receiver, sender = context.Pipe(duplex=False)
    worker = context.Process(target=_isolated_call, args=('unused-result', slow_analysis, (sender,)))
    worker.start()
    assert receiver.recv()
    print('worker-started', flush=True)
    os._exit(7)
""".replace("METHOD", method),
        encoding="utf-8",
    )
    env = os.environ.copy()
    source = str(Path(spectra_sherpa.__file__).resolve().parent.parent)
    extras = [str(Path(item).resolve()) for item in env.get("PYTHONPATH", "").split(os.pathsep) if item]
    env["PYTHONPATH"] = os.pathsep.join([source, *extras])
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 7
    assert result.stdout.strip() == "worker-started"
    assert not (tmp_path / "unused-result").exists()


def _worker_local_state():
    import os

    import spectra_sherpa.app.services.dag.executor_pool as module

    previous = getattr(module, "_test_user_state", None)
    module._test_user_state = "private result from this task"
    return os.getpid(), previous, float(np.random.random())


@pytest.mark.asyncio
async def test_consecutive_tasks_do_not_reuse_user_state():
    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

    pool = IsolatedWorkerPool(1)
    try:
        first = await pool.run(_worker_local_state, timeout=30)
        second = await pool.run(_worker_local_state, timeout=30)
        assert first[0] != second[0]
        assert first[1] is second[1] is None
        assert first[2] != second[2]
    finally:
        pool.shutdown()


@pytest.mark.asyncio
async def test_workflow_worker_reuses_bootstrap_only_inside_one_execution():
    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

    pool = IsolatedWorkerPool(1)
    try:
        async with pool.workflow():
            first = await pool.run(_worker_local_state, timeout=30)
            second = await pool.run(_worker_local_state, timeout=30)
            assert first[0] == second[0]
            assert first[1] is None
            assert second[1] == "private result from this task"
        assert not pool._active
        async with pool.workflow():
            other = await pool.run(_worker_local_state, timeout=30)
        assert other[0] != first[0]
        assert other[1] is None
        assert not pool._active
    finally:
        pool.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("single_node", [False, True])
async def test_executor_owns_one_worker_for_dependency_chain_and_disposes_on_return(single_node):
    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

    pool = IsolatedWorkerPool(1)
    try:
        executor = DAGExecutor(process_pool=pool)
        _make_snv_workflow(executor)
        executor.add_node(WorkflowNode("snv2", "preprocess.normalize", {"method": "snv"}))
        executor.add_edge(WorkflowEdge("snv", "snv2", from_output="default", to_input="default"))
        result = await (executor.execute_node("snv2") if single_node else executor.execute())
        np.testing.assert_allclose(result["snv"]["default"].X, result["snv2"]["default"].X, atol=1e-14)
        first = executor.diagnostics["snv"]["worker_execution"]
        second = executor.diagnostics["snv2"]["worker_execution"]
        assert first["worker_pid"] == second["worker_pid"]
        assert first["execution_id"] != second["execution_id"]
        assert first["lifetime"] == second["lifetime"] == "workflow"
        assert first["dispatch_seconds"] >= first["execution_seconds"]
        assert not pool._active
        executor.invalidate_node("snv")
        await executor.execute_node("snv2")
        assert executor.diagnostics["snv"]["worker_execution"]["worker_pid"] != first["worker_pid"]
        assert not pool._active
    finally:
        pool.shutdown()


@pytest.mark.asyncio
async def test_workflow_worker_rechecks_each_nodes_capabilities_and_disposes_on_refusal():
    import os

    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

    pool = IsolatedWorkerPool(1)
    ds = SherpaDataset(X=np.random.default_rng(42).normal(size=(10, 5)))
    context = WorkerExecutionContext(
        execution_id="authorized-node", runtime=ExecutionRuntime(), capabilities=("read_dataset",)
    )
    try:
        async with pool.workflow():
            await pool.run(
                _run_node_in_worker,
                "preprocess.normalize",
                "first",
                {"method": "snv"},
                (),
                {"default": ds},
                context,
                timeout=30,
            )
            with pytest.raises(PermissionError, match="worker execution context"):
                await pool.run(
                    _run_node_in_worker,
                    "preprocess.normalize",
                    "second",
                    {"method": "snv"},
                    (),
                    {"default": ds},
                    timeout=30,
                )
            assert not pool._active
            with pytest.raises(RuntimeError, match="shut down"):
                await pool.run(os.getpid, timeout=30)
        assert await pool.run(os.getpid, timeout=30) != os.getpid()
    finally:
        pool.shutdown()


@pytest.mark.asyncio
async def test_cancelling_workflow_worker_does_not_cancel_other_workflow(tmp_path):
    import asyncio
    import os

    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

    pool = IsolatedWorkerPool(2)
    started, finished = tmp_path / "started", tmp_path / "finished"

    async def slow():
        async with pool.workflow():
            await pool.run(_slow_worker, str(started), str(finished), timeout=60)

    async def other():
        async with pool.workflow():
            return await pool.run(os.getpid, timeout=30)

    task = asyncio.create_task(slow())
    surviving = None
    try:
        async with asyncio.timeout(30):
            while not started.exists():
                await asyncio.sleep(0.02)
        surviving = asyncio.create_task(other())
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await surviving != os.getpid()
        assert not finished.exists()
        assert not pool._active
    finally:
        await _finish_owned_pool_tasks(pool, task, surviving)


@pytest.mark.asyncio
async def test_workflow_timeout_includes_capacity_wait_without_releasing_another_lease():
    import asyncio
    import os

    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

    pool = IsolatedWorkerPool(1)
    try:
        async with pool.workflow():
            original_pid = await pool.run(os.getpid, timeout=30)

            async def queued():
                async with pool.workflow():
                    await pool.run(os.getpid, timeout=0.05)

            with pytest.raises(TimeoutError):
                await asyncio.create_task(queued(), context=Context())
            assert pool._slots.locked()
            assert await pool.run(os.getpid, timeout=30) == original_pid
        assert not pool._active
        assert not pool._slots.locked()
    finally:
        pool.shutdown()


@pytest.mark.asyncio
async def test_closed_workflow_cannot_start_a_previously_queued_worker():
    import asyncio
    import os

    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

    pool = IsolatedWorkerPool(1)
    ready, release = asyncio.Event(), asyncio.Event()

    async def holder():
        async with pool.workflow():
            await pool.run(os.getpid, timeout=30)
            ready.set()
            await release.wait()

    holding = asyncio.create_task(holder())
    queued = None
    try:
        await asyncio.wait_for(ready.wait(), 30)
        async with pool.workflow():
            queued = asyncio.create_task(pool.run(os.getpid, timeout=30))
            await asyncio.sleep(0)
            assert not queued.done()
        release.set()
        await holding
        with pytest.raises(RuntimeError, match="shut down"):
            await queued
        assert not pool._active
        assert not pool._slots.locked()
        assert await pool.run(os.getpid, timeout=30) != os.getpid()
    finally:
        release.set()
        for task in (holding, queued):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(*(t for t in (holding, queued) if t is not None), return_exceptions=True)
        pool.shutdown()


@pytest.mark.asyncio
async def test_nested_execution_releases_outer_lease_and_resumes_with_fresh_state():
    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

    pool = IsolatedWorkerPool(1)
    try:
        async with pool.workflow():
            outer = await pool.run(_worker_local_state, timeout=30)
            executor = DAGExecutor(process_pool=pool)
            _make_snv_workflow(executor)
            await executor.execute_node("snv")
            inner_pid = executor.diagnostics["snv"]["worker_execution"]["worker_pid"]
            assert not pool._active
            resumed = await pool.run(_worker_local_state, timeout=30)
            assert len({outer[0], inner_pid, resumed[0]}) == 3
            assert resumed[1] is None
        assert not pool._active
        assert not pool._slots.locked()
    finally:
        pool.shutdown()


@pytest.mark.asyncio
async def test_scope_exit_reaps_inflight_child_and_refuses_nested_dispatch(tmp_path):
    import asyncio

    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

    pool = IsolatedWorkerPool(1)
    started, finished = tmp_path / "started", tmp_path / "finished"
    task = None
    try:
        async with pool.workflow():
            task = asyncio.create_task(pool.run(_slow_worker, str(started), str(finished), timeout=60))
            async with asyncio.timeout(30):
                while not started.exists():
                    await asyncio.sleep(0.02)
            with pytest.raises(RuntimeError, match="active node dispatch"):
                async with pool.workflow():
                    pytest.fail("Nested scope must not discard an active node")
        with pytest.raises(RuntimeError, match="shut down"):
            await task
        assert not finished.exists()
        assert not pool._active
        assert not pool._slots.locked()
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        pool.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["crash", "serialization", "timeout"])
async def test_workflow_worker_failure_reaps_and_releases_capacity(tmp_path, failure):
    import os

    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

    pool = IsolatedWorkerPool(1)
    try:
        async with pool.workflow():
            # Ensure a running child, not a cold-start timeout.
            await pool.run(os.getpid, timeout=30)
            if failure == "crash":
                with pytest.raises(RuntimeError, match="exited without"):
                    await pool.run(_crash_worker, timeout=30)
            elif failure == "serialization":
                with pytest.raises((AttributeError, TypeError), match="pickle|local object"):
                    await pool.run(lambda: None, timeout=30)
            else:
                with pytest.raises(TimeoutError):
                    await pool.run(_slow_worker, str(tmp_path / "started"), str(tmp_path / "finished"), timeout=1)
                assert (tmp_path / "started").exists()
                assert not (tmp_path / "finished").exists()
            assert not pool._active
            assert not pool._slots.locked()
        assert await pool.run(os.getpid, timeout=30) != os.getpid()
    finally:
        pool.shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["send", "poll", "recv"])
async def test_workflow_pipe_failure_is_normalized_and_releases_capacity(monkeypatch, operation):
    import os

    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

    pool = IsolatedWorkerPool(1)
    try:
        async with pool.workflow():
            await pool.run(os.getpid, timeout=30)
            worker = pool._workflow.get()
            directory = worker._directory.name

            def broken_pipe(*args, **kwargs):
                raise BrokenPipeError("The pipe has been ended")

            # Windows can report a dead peer from PeekNamedPipe (poll), not
            # only recv. Force each transport boundary on every test platform.
            monkeypatch.setattr(worker._control, operation, broken_pipe)
            with pytest.raises(RuntimeError, match="exited without") as caught:
                await pool.run(os.getpid, timeout=30)
            assert isinstance(caught.value.__cause__, BrokenPipeError)
            assert not os.path.exists(directory)
            assert not pool._active
            assert not pool._slots.locked()
            with pytest.raises(RuntimeError, match="shut down"):
                await pool.run(os.getpid, timeout=30)
        assert await pool.run(os.getpid, timeout=30) != os.getpid()
    finally:
        pool.shutdown()


def test_workflow_worker_cannot_outlive_abrupt_backend_exit(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    import spectra_sherpa

    script = tmp_path / "owned_workflow.py"
    script.write_text(
        """
import asyncio, os, time
from pathlib import Path
from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

def slow_analysis():
    Path("started").write_text("ready")
    time.sleep(45)
    Path("finished").write_text("unexpected")

async def main():
    pool = IsolatedWorkerPool(1)
    async with pool.workflow():
        task = asyncio.create_task(pool.run(slow_analysis, timeout=60))
        async with asyncio.timeout(20):
            while not Path("started").exists():
                await asyncio.sleep(.02)
        print("worker-started", flush=True)
        os._exit(7)

if __name__ == "__main__":
    asyncio.run(main())
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    source = str(Path(spectra_sherpa.__file__).resolve().parent.parent)
    extras = [str(Path(item).resolve()) for item in env.get("PYTHONPATH", "").split(os.pathsep) if item]
    env["PYTHONPATH"] = os.pathsep.join([source, *extras])
    result = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 7
    assert result.stdout.strip() == "worker-started"
    assert not (tmp_path / "finished").exists()


def _finite_ownership_worker(started, finished):
    """A real started worker with a finite escape hatch for cleanup regressions."""
    import os
    import time
    from pathlib import Path

    marker = Path(started)
    pending = marker.with_suffix(".pending")
    pending.write_text(str(os.getpid()))
    pending.replace(marker)
    time.sleep(20)
    Path(finished).write_text("work ran to completion")
    return os.getpid()


@pytest.mark.asyncio
@pytest.mark.parametrize("workflow", [False, True])
async def test_assertion_failure_collects_both_owned_pool_tasks(tmp_path, workflow):
    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

    pool = IsolatedWorkerPool(2)
    tasks = []
    started = [tmp_path / f"started-{index}" for index in range(2)]
    finished = [tmp_path / f"finished-{index}" for index in range(2)]
    unrelated = asyncio.create_task(asyncio.sleep(60))

    async def run(index):
        if workflow:
            async with pool.workflow():
                return await pool.run(_finite_ownership_worker, str(started[index]), str(finished[index]), timeout=60)
        return await pool.run(_finite_ownership_worker, str(started[index]), str(finished[index]), timeout=60)

    try:
        with pytest.raises(AssertionError, match="injected before companion await"):
            try:
                for index in range(2):
                    tasks.append(asyncio.create_task(run(index)))
                async with asyncio.timeout(30):
                    while not all(path.exists() for path in started):
                        await asyncio.sleep(0.02)
                pids = {int(path.read_text()) for path in started}
                assert len(pids) == 2
                raise AssertionError("injected before companion await")
            finally:
                await _finish_owned_pool_tasks(pool, *tasks)
        assert all(task.done() and task.cancelled() for task in tasks)
        assert not pool._active
        assert pool._slots._value == 2
        assert pids.isdisjoint({child.pid for child in multiprocessing.active_children()})
        assert not any(path.exists() for path in finished)
        assert not unrelated.done()
    finally:
        unrelated.cancel()
        await asyncio.gather(unrelated, return_exceptions=True)
        pool.shutdown()


@pytest.mark.asyncio
async def test_legacy_assertion_failure_stops_only_owned_running_workers(tmp_path, monkeypatch):
    import os
    import threading

    pool = TestPoolExecution._create_pool(1)
    independent = TestPoolExecution._create_pool(1)
    started, finished = tmp_path / "legacy-started", tmp_path / "legacy-finished"
    work = None
    try:
        loop = asyncio.get_running_loop()
        independent_pid = await asyncio.wait_for(loop.run_in_executor(independent, os.getpid), 30)
        with pytest.raises(AssertionError, match="injected after future cancellation"):
            try:
                work = loop.run_in_executor(pool, _finite_ownership_worker, str(started), str(finished))
                async with asyncio.timeout(30):
                    while not started.exists():
                        await asyncio.sleep(0.02)
                # Same narrow Python 3.11 owned-handle boundary as fixture cleanup.
                workers = tuple(pool._processes.values())
                assert {worker.pid for worker in workers} == {int(started.read_text())}
                work.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await work
                assert all(worker.is_alive() for worker in workers), "Future cancellation must not fake worker exit"
                manager = pool._executor_manager_thread
                assert manager is not None and manager.is_alive()
                for worker in workers:
                    original_poll = worker._popen.poll

                    def manager_only_poll(*args, _poll=original_poll, **kwargs):
                        assert (
                            threading.current_thread() is manager or not manager.is_alive()
                        ), "Only the executor manager may reap a worker before shutdown completes"
                        return _poll(*args, **kwargs)

                    monkeypatch.setattr(worker._popen, "poll", manager_only_poll)
                raise AssertionError("injected after future cancellation")
            finally:
                _shutdown_legacy_test_pool(pool)
        assert all(not worker.is_alive() and worker.exitcode is not None for worker in workers)
        assert not finished.exists(), "Failure cleanup must stop the work, not wait for its natural completion"
        assert await asyncio.wait_for(loop.run_in_executor(independent, os.getpid), 30) == independent_pid
    finally:
        if work is not None and not work.done():
            work.cancel()
        try:
            _shutdown_legacy_test_pool(pool)
        finally:
            _shutdown_legacy_test_pool(independent)
