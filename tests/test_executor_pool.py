"""Tests for ProcessPoolExecutor offloading in the DAG executor."""

from __future__ import annotations

import multiprocessing
from concurrent.futures import ProcessPoolExecutor
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
        p.shutdown(wait=True)

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
    with pytest.raises(TimeoutError):
        await pool.run(_slow_worker, str(started), str(finished), timeout=10)
    assert started.exists(), "The test must time out a running child, not merely its startup"
    assert int(started.read_text()) not in [p.pid for p in multiprocessing.active_children()]
    assert not finished.exists()
    assert not pool._active
    # A fresh request can immediately use the only capacity slot.
    pid = await pool.run(os.getpid, timeout=30)
    assert pid != os.getpid()
    pool.shutdown()


@pytest.mark.asyncio
async def test_cancelling_one_isolated_worker_preserves_other_request(tmp_path):
    import asyncio
    import os

    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool

    pool = IsolatedWorkerPool(2)
    started, finished = tmp_path / "started", tmp_path / "finished"
    task = asyncio.create_task(pool.run(_slow_worker, str(started), str(finished), timeout=60))
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
        pool.shutdown()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


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


def test_isolated_worker_cannot_outlive_abrupt_backend_exit(tmp_path):
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
    context = multiprocessing.get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    worker = context.Process(target=_isolated_call, args=('unused-result', slow_analysis, (sender,)))
    worker.start()
    assert receiver.recv()
    print('worker-started', flush=True)
    os._exit(7)
""",
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
