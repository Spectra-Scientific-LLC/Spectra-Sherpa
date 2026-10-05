"""Scientific branch admission is independent of UI and model provider."""

from copy import deepcopy

import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.services.dag.executor import DAGExecutor
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.population_authority import analyze_populations
from spectra_sherpa.app.services.tools.builtin.workflow import validate_workflow


def graph():
    nodes = [
        {"id": "source", "type": "data.file_load", "parameters": {"experiment_id": 1, "file_id": 1}},
        {"id": "split", "type": "data.train_test_split", "parameters": {"test_size": 0.25}},
        {"id": "fit", "type": "model.fitted_pls", "parameters": {"n_components": 2}},
        {"id": "apply", "type": "model.apply_fitted_pls", "parameters": {}},
        {"id": "eval", "type": "diagnostics.regression_evaluator", "parameters": {}},
    ]
    edges = [
        edge("source", "split", inp="X"),
        edge("split", "fit", "X_train"),
        edge("fit", "apply", "fitted_state", "fitted_state"),
        edge("split", "apply", "X_test"),
        edge("apply", "eval"),
        edge("split", "eval", "y_test", "y_true"),
    ]
    return nodes, edges


def edge(source, target, out="default", inp="default"):
    return {"source": source, "target": target, "from_output": out, "to_input": inp}


def authority(nodes, edges):
    executor = DAGExecutor()
    for node in nodes:
        executor.add_node(WorkflowNode(node["id"], node["type"], node["parameters"]))
    for item in edges:
        executor.add_edge(WorkflowEdge(item["source"], item["target"], item["from_output"], item["to_input"]))
    return analyze_populations(executor.nodes, executor.edges)


def test_valid_held_out_graph_has_exact_split_and_training_receipt():
    nodes, edges = graph()
    assert validate_workflow(nodes, edges)["valid"]
    issues, receipts = authority(nodes, edges)
    assert not issues
    assert receipts["eval"]["role"] == "held_out_test"
    assert receipts["eval"]["population"] == ["split", "test"]
    assert receipts["eval"]["fitted_populations"] == [["split", "train"]]


@pytest.mark.parametrize("case", ["test_fit", "full_fit", "wrong_y", "different_split", "fit_wrong_y", "test_scale"])
def test_leaking_or_misaligned_graphs_are_refused_by_shared_admission(case):
    nodes, edges = graph()
    if case == "test_fit":
        edges[1] = edge("split", "fit", "X_test")
    elif case == "full_fit":
        edges[1] = edge("source", "fit")
    elif case == "wrong_y":
        edges[-1] = edge("split", "eval", "y_train", "y_true")
    elif case == "different_split":
        nodes.append({**deepcopy(nodes[1]), "id": "other_split"})
        edges.append(edge("source", "other_split", inp="X"))
        edges[-2] = edge("other_split", "eval", "y_test", "y_true")
    elif case == "fit_wrong_y":
        edges.append(edge("split", "fit", "y_test", "y"))
    else:
        nodes.append({"id": "scale", "type": "preprocess.scale", "parameters": {}})
        edges[3] = edge("scale", "apply")
        edges.append(edge("split", "scale", "X_test"))
    result = validate_workflow(nodes, edges)
    assert not result["valid"], result
    assert any("Population authority" in issue["message"] for issue in result["issues"]), result


def test_reference_fitted_test_scaling_is_admitted():
    nodes, edges = graph()
    nodes.append({"id": "scale", "type": "preprocess.scale", "parameters": {}})
    edges[3] = edge("scale", "apply")
    edges.extend([edge("split", "scale", "X_test"), edge("split", "scale", "X_train", "reference")])
    assert validate_workflow(nodes, edges)["valid"]
    assert authority(nodes, edges)[1]["eval"]["role"] == "held_out_test"


def test_calibration_is_labeled_without_claiming_holdout():
    nodes, edges = graph()
    edges[3] = edge("split", "apply", "X_train")
    edges[-1] = edge("split", "eval", "y_train", "y_true")
    assert validate_workflow(nodes, edges)["valid"]
    assert authority(nodes, edges)[1]["eval"]["role"] == "calibration"


@pytest.mark.asyncio
async def test_bare_prediction_truth_pair_does_not_assert_holdout():
    from spectra_sherpa.app.services.dag.node_base import node_registry

    result = await node_registry.create_node("diagnostics.regression_evaluator", "eval", {}).execute(
        [1.1, 2.1, 3.1], y_true=[1.0, 2.0, 3.0]
    )
    assert result.outputs["comparison"]["metadata"]["role"] == "unqualified_evaluation"


@pytest.mark.asyncio
async def test_real_execution_retains_population_and_cached_rewire_changes_scope(tmp_path):
    import numpy as np

    from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, TargetContext

    rng = np.random.default_rng(24)
    data = SherpaDataset(
        X=rng.normal(size=(40, 8)),
        target=rng.normal(size=40),
        sample_axis=SampleAxis(labels=[f"s{i}" for i in range(40)]),
        target_context=TargetContext(target_type="continuous", target_name="noise", target_names=["noise"]),
    )
    from spectra_sherpa.app.services.model_store import ModelStore
    from spectra_sherpa.core.execution_runtime import ExecutionRuntime

    nodes, edges = graph()
    executor = DAGExecutor(runtime=ExecutionRuntime(model_artifact_writer=ModelStore(tmp_path)))
    for node in nodes:
        executor.add_node(WorkflowNode(node["id"], node["type"], node["parameters"]))
    for item in edges:
        executor.add_edge(WorkflowEdge(item["source"], item["target"], item["from_output"], item["to_input"]))

    async def synthetic_source():
        return data

    executor.nodes["source"].execute = synthetic_source
    results = await executor.execute()
    assert results["eval"]["comparison"]["metadata"]["role"] == "held_out_test"
    # Same cached nodes but new edges must recompute, not reuse held-out rows.
    executor.edges[3].from_output = "X_train"
    executor.edges[-1].from_output = "y_train"
    results = await executor.execute_node("eval")
    assert results["eval"]["comparison"]["metadata"]["role"] == "calibration"
    assert results["eval"]["default"]["n_samples"] == 30
    executor.edges[-1].from_output = "y_test"
    with pytest.raises(ValueError, match="populations come from different branches"):
        await executor.execute_node("eval")


def test_classification_uses_identical_split_authority():
    nodes, edges = graph()
    nodes[2].update(type="classification.plsda")
    nodes[3].update(type="classification.apply_plsda")
    nodes[4].update(type="diagnostics.classification_evaluator")
    edges[1]["to_input"] = "X"
    edges[4]["from_output"] = "y_pred"
    assert validate_workflow(nodes, edges)["valid"]
    assert authority(nodes, edges)[1]["eval"]["role"] == "held_out_test"
    edges[1]["from_output"] = "X_test"
    assert not validate_workflow(nodes, edges)["valid"]


def test_fitted_variable_selection_cannot_consume_test_population():
    nodes, edges = graph()
    nodes.append({"id": "selector", "type": "selection.spa", "parameters": {}})
    edges[3] = edge("selector", "apply")
    edges.append(edge("split", "selector", "X_test", "X"))
    issues, _ = authority(nodes, edges)
    assert any(issue.node_id == "selector" and "fitting on an explicit test" in issue.message for issue in issues)


def test_external_model_application_does_not_invent_independence():
    nodes, edges = graph()
    nodes = [node for node in nodes if node["id"] != "fit"]
    edges = [item for item in edges if item["source"] != "fit" and item["target"] != "fit"]
    # Missing state is refused by execution; the population analyzer must not
    # confer a held-out label merely because prediction and truth align.
    assert authority(nodes, edges)[1]["eval"]["role"] == "unqualified_evaluation"


def test_training_reference_scaling_does_not_qualify_external_model():
    nodes, edges = graph()
    nodes = [node for node in nodes if node["id"] != "fit"]
    nodes[2].update(type="model.load_apply", parameters={"model_id": "external-model"})
    nodes.append({"id": "scale", "type": "preprocess.scale", "parameters": {}})
    edges = [item for item in edges if item["source"] != "fit" and item["target"] != "fit"]
    edges[1] = edge("scale", "apply", inp="X_new")
    edges[2]["from_output"] = "result"
    edges.extend([edge("split", "scale", "X_test"), edge("split", "scale", "X_train", "reference")])
    issues, receipts = authority(nodes, edges)
    assert not issues
    assert receipts["eval"]["fitted_populations"] == [["split", "train"]]
    assert receipts["eval"]["role"] == "unqualified_evaluation"
    assert receipts["eval"]["qualification"] == "unverified_lineage"


def test_peak_guided_pls_retains_training_mask_lineage_for_held_out_evaluation():
    nodes, edges = graph()
    nodes.extend(
        [
            {
                "id": "peak_train",
                "type": "selection.variable_select",
                "parameters": {
                    "method": "peak_window",
                    "peak_prominence": 0.05,
                    "peak_half_window": 15,
                    "include_negative_extrema": True,
                },
            },
            {"id": "peak_test", "type": "selection.variable_select", "parameters": {"method": "apply_mask"}},
        ]
    )
    edges[1] = edge("peak_train", "fit", "X_selected")
    edges[3] = edge("peak_test", "apply", "X_selected")
    edges.extend(
        [
            edge("split", "peak_train", "X_train", "X"),
            edge("split", "peak_test", "X_test", "X"),
            edge("peak_train", "peak_test", "mask", "mask"),
        ]
    )

    issues, receipts = authority(nodes, edges)

    assert not issues
    assert receipts["eval"]["role"] == "held_out_test"
    assert receipts["eval"]["qualification"] == "graph_verified"
    assert receipts["eval"]["fitted_populations"] == [["split", "train"]]
