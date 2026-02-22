"""Integration tests for the headless prediction API.

Tests Issue #1: Headless API must support executor deepcopy for concurrent requests.
"""

from __future__ import annotations

import copy
from concurrent.futures import ProcessPoolExecutor
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# Import node modules to trigger @register_node decorators
import spectra_sherpa.app.services.dag.nodes.data  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
from spectra_sherpa.app.services.dag.executor import (
    DAGExecutor,
    WorkflowEdge,
    WorkflowNode,
    set_default_pool,
)


def _make_simple_workflow(executor: DAGExecutor) -> None:
    """Create a minimal workflow: DataSource -> SNV"""
    executor.add_node(
        WorkflowNode(
            node_id="src",
            node_type="data.source",
            parameters={"source": "sklearn", "dataset_name": "iris"},
        )
    )
    executor.add_node(
        WorkflowNode(
            node_id="snv",
            node_type="normalize.snv",
            parameters={},
        )
    )
    executor.add_edge(
        WorkflowEdge(
            from_node="src",
            to_node="snv",
        )
    )


def test_executor_pickle_without_pool():
    """Test that executor can be pickled/deepcopied when no pool is set."""
    executor = DAGExecutor(process_pool=None)
    _make_simple_workflow(executor)

    # Should succeed without error
    cloned = copy.deepcopy(executor)

    # Verify structure is preserved
    assert len(cloned.nodes) == len(executor.nodes)
    assert len(cloned.edges) == len(executor.edges)
    assert cloned.nodes.keys() == executor.nodes.keys()


def test_executor_pickle_with_pool():
    """Test that executor can be pickled/deepcopied even with a process pool.

    This is the critical fix for Issue #1: headless API HTTP 500 errors.
    """
    # Create a process pool (simulating app startup)
    pool = ProcessPoolExecutor(max_workers=2)

    try:
        # Create executor with pool (as happens in production)
        executor = DAGExecutor(process_pool=pool)
        _make_simple_workflow(executor)

        # This should NOT raise TypeError about unpicklable locks
        cloned = copy.deepcopy(executor)

        # Verify structure is preserved
        assert len(cloned.nodes) == len(executor.nodes)
        assert len(cloned.edges) == len(executor.edges)
        assert cloned.nodes.keys() == executor.nodes.keys()

        # Verify pool reference is excluded from pickle
        # (cloned executor should have None pool after unpickling)
        assert cloned._process_pool is None or cloned._process_pool is pool

    finally:
        pool.shutdown(wait=False)


def test_executor_pickle_with_global_pool():
    """Test that executor restores global pool after unpickling.

    The headless API relies on sharing a global pool across all cloned executors.
    """
    # Set global pool (as happens at app startup)
    global_pool = ProcessPoolExecutor(max_workers=2)
    set_default_pool(global_pool)

    try:
        # Create executor without explicit pool (uses global)
        executor = DAGExecutor()
        _make_simple_workflow(executor)

        # Verify executor picked up global pool
        assert executor._process_pool is global_pool

        # Clone executor (as happens in headless API)
        cloned = copy.deepcopy(executor)

        # Verify cloned executor also has reference to global pool
        assert cloned._process_pool is global_pool

        # Verify structure is preserved
        assert len(cloned.nodes) == len(executor.nodes)
        assert len(cloned.edges) == len(executor.edges)

    finally:
        global_pool.shutdown(wait=False)
        set_default_pool(None)


def test_executor_pickle_preserves_results():
    """Test that cached results survive deepcopy."""
    executor = DAGExecutor(process_pool=None)
    _make_simple_workflow(executor)

    # Inject some cached results (as happens in prediction API)
    mock_dataset = MagicMock()
    executor.inject_result("src", mock_dataset)

    # Clone executor
    cloned = copy.deepcopy(executor)

    # Verify cached results are preserved
    assert "src" in cloned.results
    assert cloned._param_hashes["src"] == "__injected__"


def test_executor_pickle_preserves_state():
    """Test that all executor state survives deepcopy."""
    executor = DAGExecutor(process_pool=None)
    _make_simple_workflow(executor)

    # Set various state fields
    executor._param_hashes["src"] = "abc123"
    executor._dirty_nodes.add("snv")

    # Clone executor
    cloned = copy.deepcopy(executor)

    # Verify all state is preserved
    assert cloned._param_hashes == executor._param_hashes
    assert cloned._dirty_nodes == executor._dirty_nodes
    assert cloned.status == executor.status


@pytest.mark.asyncio
async def test_headless_api_concurrent_requests_simulation():
    """Simulate concurrent requests to headless API with executor cloning.

    This is the production scenario that was failing before the fix.
    """
    # Global executor (loaded at startup)
    global_pool = ProcessPoolExecutor(max_workers=2)
    set_default_pool(global_pool)

    try:
        global_executor = DAGExecutor()
        _make_simple_workflow(global_executor)

        # Simulate 3 concurrent requests (each clones the global executor)
        cloned_executors = []
        for _ in range(3):
            # This is what headless_app.py:106 does
            cloned = copy.deepcopy(global_executor)
            cloned_executors.append(cloned)

        # Verify all clones are independent but valid
        assert len(cloned_executors) == 3
        for cloned in cloned_executors:
            assert len(cloned.nodes) == 2
            assert len(cloned.edges) == 1
            assert cloned._process_pool is global_pool

    finally:
        global_pool.shutdown(wait=False)
        set_default_pool(None)


def test_executor_getstate_setstate():
    """Test the pickle protocol methods directly."""
    pool = ProcessPoolExecutor(max_workers=2)

    try:
        executor = DAGExecutor(process_pool=pool)
        _make_simple_workflow(executor)

        # Get state (as pickle does)
        state = executor.__getstate__()

        # Verify pool is excluded
        assert state["_process_pool"] is None

        # Verify other state is preserved
        assert "nodes" in state
        assert "edges" in state
        assert "results" in state

        # Create new executor and restore state
        new_executor = DAGExecutor.__new__(DAGExecutor)
        new_executor.__setstate__(state)

    finally:
        pool.shutdown(wait=False)


@pytest.fixture
def test_client():
    from fastapi.testclient import TestClient
    from spectra_sherpa.app.api.headless_app import app

    return TestClient(app)


def test_predict_with_array_payload(test_client):
    from unittest.mock import patch
    import spectra_sherpa.app.api.headless_app as headless_app

    executor = DAGExecutor(process_pool=None)
    executor.add_node(
        WorkflowNode(
            node_id="deploy_in",
            node_type="deploy.input",
            parameters={"stream_name": "sample"},
        )
    )
    executor.add_node(
        WorkflowNode(
            node_id="deploy_out",
            node_type="deploy.output",
            parameters={"output_format": "json"},
        )
    )
    executor.add_edge(
        WorkflowEdge(
            from_node="deploy_in",
            to_node="deploy_out",
        )
    )

    with patch.object(headless_app, "_executor", executor):
        # Valid JSON payload containing lists of floats (array coercion)
        payload = {"sample": [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]}

        response = test_client.post("/predict", json=payload)

        # Must be 200 OK, not 400 Bad Request
        assert response.status_code == 200, response.text

        # Verify JSON response contains the array data via the mock executor pass-through
        data = response.json()
        assert data == payload["sample"]
