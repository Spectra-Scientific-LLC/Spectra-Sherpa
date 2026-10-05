"""Partial inspection must not require completion of unrelated canvas branches."""

from pathlib import Path
from unittest.mock import AsyncMock

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.executor import DAGExecutor
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge as Edge
from spectra_sherpa.app.services.dag.executor_types import WorkflowNode as Node
from spectra_sherpa.app.services.dag.workflow_preflight import preflight_workflow
from spectra_sherpa.app.types import type_registry


@pytest.fixture(autouse=True)
def registry():
    import spectra_sherpa.app.services.dag.nodes  # noqa: F401

    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src/spectra_sherpa/app/types")


def graph(output="X_train", consumer="output.data_table"):
    nodes = [
        Node("source", "data.file_load", {"experiment_id": 1, "file_id": 1}),
        Node("split", "data.train_test_split", {"split_method": "random", "test_size": 0.25}),
        Node("inspect", consumer, {}),
        Node("eval", "diagnostics.labeled_regression_evaluator", {}),
    ]
    edges = [Edge("source", "split", to_input="X"), Edge("split", "inspect", output)]
    return nodes, edges


@pytest.mark.parametrize("output", ["X_train", "X_test", "y_train", "y_test"])
def test_all_split_outputs_admitted_for_table_without_unrelated_evaluator(output):
    nodes, edges = graph(output)
    partial = preflight_workflow(nodes, edges, target_node_id="inspect")
    assert partial.is_valid, partial.issues
    full = preflight_workflow(nodes, edges)
    assert not full.is_valid
    assert any(issue.node_id == "eval" for issue in full.issues)


@pytest.mark.parametrize("consumer", ["output.plot", "stats.summary", "preprocess.normalize"])
def test_scope_is_not_specific_to_data_table(consumer):
    nodes, edges = graph(consumer=consumer)
    partial = preflight_workflow(nodes, edges, target_node_id="inspect")
    assert partial.is_valid, partial.issues


def test_required_upstream_inputs_still_block_inspection():
    nodes, edges = graph()
    result = preflight_workflow(nodes, edges[1:], target_node_id="inspect")
    assert not result.is_valid
    assert any(issue.node_id == "split" for issue in result.issues)


def test_missing_target_and_dangling_upstream_are_rejected():
    nodes, edges = graph()
    assert not preflight_workflow(nodes, edges, target_node_id="missing").is_valid
    assert not preflight_workflow(nodes[1:], edges, target_node_id="inspect").is_valid


@pytest.mark.anyio
@pytest.mark.parametrize("output", ["X_train", "X_test", "y_train", "y_test"])
async def test_actual_split_outputs_render_in_table(output):
    nodes, edges = graph(output)
    nodes.append(Node("bad_fit", "model.fitted_pls", {"n_components": 2}))
    edges.append(Edge("split", "bad_fit", "X_test"))
    executor = DAGExecutor(process_pool=None)
    for node in nodes:
        executor.add_node(node)
    for edge in edges:
        executor.add_edge(edge)
    dataset = SherpaDataset(X=np.arange(80, dtype=float).reshape(20, 4), target=np.arange(20, dtype=float))
    executor.nodes["source"].run = AsyncMock(return_value={"default": dataset})
    results = await executor.execute_node("inspect")
    assert set(results) == {"source", "split", "inspect"}
    rows = results["inspect"]["visualization"]["data"]
    assert len(rows) == (15 if output.endswith("train") else 5)
    assert len(rows[0]) == (4 if output.startswith("X_") else 1)
    assert executor.nodes["eval"].status.value == "pending"
    assert executor.nodes["bad_fit"].status.value == "pending"


def test_population_errors_are_scoped_not_disabled():
    nodes, edges = graph()
    nodes.append(Node("bad_fit", "model.fitted_pls", {"n_components": 2}))
    edges.append(Edge("split", "bad_fit", "X_test"))
    assert preflight_workflow(nodes, edges, target_node_id="inspect").is_valid
    result = preflight_workflow(nodes, edges, target_node_id="bad_fit")
    assert not result.is_valid
    assert any("Population authority" in issue.message for issue in result.issues)


def test_only_cycles_in_the_dependency_path_block_partial_execution():
    nodes, edges = graph()
    nodes.append(Node("cycle", "preprocess.normalize", {}))
    edges.append(Edge("cycle", "cycle"))
    assert preflight_workflow(nodes, edges, target_node_id="inspect").is_valid
    edges.append(Edge("cycle", "inspect"))
    assert not preflight_workflow(nodes, edges, target_node_id="inspect").is_valid
