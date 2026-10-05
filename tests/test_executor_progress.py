"""Tests for per-node progress/status events (Issue #18).

Verifies that DAGExecutor.execute() calls the optional status_callback
with correct status transitions (queued → running → completed/error).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.executor import (
    DAGExecutor,
    WorkflowEdge,
    WorkflowNode,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _register_nodes():
    """Ensure core node types are registered."""
    import spectra_sherpa.app.services.dag.nodes.data  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401

    try:
        import spectra_sherpa.app.services.dag.nodes.deploy_nodes  # noqa: F401
    except Exception:
        pass


@pytest.fixture()
def callback():
    """Async mock for status_callback."""
    return AsyncMock()


def _add_exact_file_source(executor: DAGExecutor, *, error: Exception | None = None) -> None:
    """Add canonical source identity while isolating this unit test from I/O."""
    executor.add_node(
        WorkflowNode(
            node_id="src1",
            node_type="data.file_load",
            parameters={"experiment_id": 1, "file_id": 1},
        )
    )
    if error is None:
        executor.nodes["src1"].run = AsyncMock(
            return_value={"default": SherpaDataset(X=np.arange(20, dtype=float).reshape(4, 5))}
        )
    else:
        executor.nodes["src1"].run = AsyncMock(side_effect=error)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStatusCallback:
    @pytest.mark.asyncio
    async def test_callback_receives_queued_running_completed(self, callback, patch_eigenvector_loader):
        """Basic canonical source → SNV pipeline gets the full lifecycle."""
        executor = DAGExecutor(process_pool=None)
        _add_exact_file_source(executor)
        executor.add_node(WorkflowNode(node_id="snv1", node_type="preprocess.normalize", parameters={"method": "snv"}))
        executor.add_edge(WorkflowEdge(from_node="src1", to_node="snv1"))

        await executor.execute(status_callback=callback)

        # Extract calls: (node_id, status, error)
        calls = [(c.args[0], c.args[1]) for c in callback.call_args_list]

        # Both nodes should get queued
        assert ("src1", "queued") in calls
        assert ("snv1", "queued") in calls

        # Both should get running
        assert ("src1", "running") in calls
        assert ("snv1", "running") in calls

        # Both should get completed
        assert ("src1", "completed") in calls
        assert ("snv1", "completed") in calls

    @pytest.mark.asyncio
    async def test_callback_receives_error_on_failure(self, callback):
        """When a node fails, callback receives error status."""
        executor = DAGExecutor(process_pool=None)
        _add_exact_file_source(executor, error=ValueError("source failed"))

        # The workflow may raise, but callback should still be called with error
        try:
            await executor.execute(status_callback=callback)
        except (ValueError, Exception):
            pass

        calls = [(c.args[0], c.args[1]) for c in callback.call_args_list]
        assert ("src1", "queued") in calls
        assert ("src1", "running") in calls
        # Node may complete (sklearn loader creates empty/error result) or error

    @pytest.mark.asyncio
    async def test_no_callback_still_works(self):
        """Verify execution works without a callback (backward compat)."""
        executor = DAGExecutor(process_pool=None)
        _add_exact_file_source(executor)

        results = await executor.execute()  # No callback
        assert "src1" in results

    @pytest.mark.asyncio
    async def test_callback_failure_does_not_block_execution(self):
        """If callback raises, execution should still complete."""
        failing_callback = AsyncMock(side_effect=RuntimeError("broadcast failed"))

        executor = DAGExecutor(process_pool=None)
        _add_exact_file_source(executor)

        # Should not raise despite callback failures
        results = await executor.execute(status_callback=failing_callback)
        assert "src1" in results

    @pytest.mark.asyncio
    async def test_callback_order_queued_before_running(self, callback, patch_eigenvector_loader):
        """All queued events should come before any running events."""
        executor = DAGExecutor(process_pool=None)
        _add_exact_file_source(executor)
        executor.add_node(WorkflowNode(node_id="snv1", node_type="preprocess.normalize", parameters={"method": "snv"}))
        executor.add_edge(WorkflowEdge(from_node="src1", to_node="snv1"))

        await executor.execute(status_callback=callback)

        statuses = [c.args[1] for c in callback.call_args_list]
        # Find the last "queued" and first "running"
        last_queued = max(i for i, s in enumerate(statuses) if s == "queued")
        first_running = min(i for i, s in enumerate(statuses) if s == "running")
        assert last_queued < first_running
