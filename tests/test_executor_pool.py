"""Tests for ProcessPoolExecutor offloading in the DAG executor."""

from __future__ import annotations

import multiprocessing
from concurrent.futures import ProcessPoolExecutor
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
from spectra_sherpa.app.services.dag.node_base import NodeResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snv_workflow(executor: DAGExecutor) -> str:
    """Add a DataSource -> SNV two-node workflow and return the SNV node id."""
    executor.add_node(
        WorkflowNode(
            node_id="src",
            node_type="data.source",
            parameters={"source": "eigenvector", "eigenvector_dataset": "diesel_nir"},
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
    return "snv"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRunNodeInWorker:
    """Test the top-level worker function directly."""

    def test_snv_in_worker(self):
        """A preprocessing node can execute in a fresh worker context."""
        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        ds = SherpaDataset(X=np.random.default_rng(42).normal(size=(10, 50)))
        result = _run_node_in_worker(
            node_type="preprocess.normalize",
            node_id="snv_w",
            parameters={"method": "snv"},
            args=(),
            kwargs={"default": ds},
        )
        assert isinstance(result, NodeResult)
        out = result.outputs
        if isinstance(out, dict) and "default" in out:
            out = out["default"]
        assert hasattr(out, "shape")
        assert out.shape == (10, 50)


class TestShouldOffload:
    """Test the offload decision logic."""

    def test_no_pool_never_offloads(self):
        executor = DAGExecutor(process_pool=None)
        executor.add_node(WorkflowNode("snv", "preprocess.normalize", {"method": "snv"}))
        assert executor._should_offload(executor.nodes["snv"]) is False

    def test_data_node_stays_in_process(self):
        pool = MagicMock(spec=ProcessPoolExecutor)
        executor = DAGExecutor(process_pool=pool)
        executor.add_node(WorkflowNode("src", "data.source", {"source": "sklearn", "dataset_name": "iris"}))
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
    """Test NDDataset -> SherpaDataset conversion before pool dispatch."""

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
        from spectra_sherpa.app.lib.scp_compat import HAS_SCP

        if not HAS_SCP:
            pytest.skip("SpectroChemPy not installed")
        import spectrochempy as scp

        nds = scp.NDDataset(np.random.default_rng(0).normal(size=(5, 10)))
        with pytest.raises(TypeError, match="NDDataset reached pool boundary"):
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

    async def test_workflow_with_pool_matches_in_process(self, pool):
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
        executor = DAGExecutor(process_pool=pool)
        executor.add_node(
            WorkflowNode(
                "src",
                "data.source",
                {"source": "sklearn", "dataset_name": "iris"},
            )
        )
        results = await executor.execute()
        assert "src" in results

    async def test_execute_node_uses_pool(self, pool):
        """execute_node() should also offload to the pool."""
        executor = DAGExecutor(process_pool=pool)
        _make_snv_workflow(executor)
        results = await executor.execute_node("snv")
        assert "snv" in results

    async def test_pool_fallback_on_broken_pool(self):
        """If the pool breaks, execution falls back to in-process."""
        # Use a pool that's already been shut down (simulates broken pool)
        broken = self._create_pool(max_workers=1)
        broken.shutdown(wait=True)

        executor = DAGExecutor(process_pool=broken)
        _make_snv_workflow(executor)
        # Should succeed via in-process fallback
        results = await executor.execute()
        assert "snv" in results
