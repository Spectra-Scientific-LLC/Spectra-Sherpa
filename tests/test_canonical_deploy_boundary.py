"""Release contract for the canonical deployed-DAG boundary."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest
from sklearn.model_selection import train_test_split

import spectra_sherpa.sdk as ss
from spectra_sherpa.app.lib.sherpa_dataset import DatasetLayoutContext, SherpaDataset, TargetContext
from spectra_sherpa.app.lib.sklearn_info import load_sklearn_reference_as_sherpa
from spectra_sherpa.app.services.dag.executor import DAGExecutor, WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.data.split_planner import bind_split_target
from spectra_sherpa.app.services.python_export import generate_python_code
from spectra_sherpa.sdk.deployment import (
    DEPLOYMENT_RESPONSE_SCHEMA,
    admit_deployment_input,
    deployment_target_output,
    format_deployment_output,
    validate_deployment_input_set,
)
from tests.performance_contract import PerformanceCeiling


def _workflow() -> SimpleNamespace:
    return SimpleNamespace(
        name="Canonical deployment boundary",
        description="",
        integrity_hash="deploy-boundary",
        nodes=[
            SimpleNamespace(node_id="request", node_type="deploy.input", parameters={"stream_name": "sample"}),
            SimpleNamespace(node_id="response", node_type="deploy.output", parameters={"output_format": "json"}),
        ],
        edges=[
            SimpleNamespace(
                from_node_id="request",
                to_node_id="response",
                from_output="default",
                to_input="default",
            )
        ],
    )


def _executor() -> DAGExecutor:
    executor = DAGExecutor(process_pool=None)
    executor.add_node(WorkflowNode(node_id="request", node_type="deploy.input", parameters={"stream_name": "sample"}))
    executor.add_node(WorkflowNode(node_id="response", node_type="deploy.output", parameters={"output_format": "json"}))
    executor.add_edge(WorkflowEdge(from_node="request", to_node="response"))
    return executor


@pytest.mark.asyncio
async def test_prediction_executes_downstream_data_filter() -> None:
    executor = DAGExecutor(process_pool=None)
    executor.add_node(WorkflowNode("source", "deploy.input", {}))
    executor.add_node(
        WorkflowNode(
            "filter",
            "data.filter_samples",
            {
                "field": "intensity",
                "intensity_metric": "max",
                "intensity_operator": "gte",
                "intensity_threshold": 5,
            },
        )
    )
    executor.add_edge(WorkflowEdge("source", "filter", "default", "X"))
    assert executor.find_entry_nodes() == ["source"]
    assert executor.find_prediction_entry_nodes() == ["source"]
    executor.inject_deployment_input("source", [[1.0, 2.0], [10.0, 20.0]], stream_name="sample")
    results = await executor.execute()
    np.testing.assert_array_equal(results["filter"]["default"].X, [[10.0, 20.0]])


def test_prediction_preserves_reference_roots_and_rejects_ambiguous_inputs() -> None:
    executor = _executor()
    executor.add_node(WorkflowNode("reference", "data.file_load", {"experiment_id": 1, "file_id": 1}))
    assert executor.find_prediction_entry_nodes() == ["request"]
    executor.add_node(WorkflowNode("second", "deploy.input", {"stream_name": "other"}))
    with pytest.raises(ValueError, match="exactly one input"):
        executor.find_prediction_entry_nodes()


def test_prediction_legacy_source_is_unambiguous() -> None:
    executor = DAGExecutor(process_pool=None)
    executor.add_node(WorkflowNode("source", "data.file_load", {"experiment_id": 1, "file_id": 1}))
    assert executor.find_prediction_entry_nodes() == ["source"]
    executor.add_node(WorkflowNode("reference", "data.file_load", {"experiment_id": 1, "file_id": 2}))
    with pytest.raises(ValueError, match="exactly one input"):
        executor.find_prediction_entry_nodes()


@pytest.mark.asyncio
async def test_prediction_preserves_split_output_ports() -> None:
    executor = DAGExecutor(process_pool=None)
    executor.add_node(WorkflowNode("source", "deploy.input", {}))
    executor.add_node(WorkflowNode("split", "data.train_test_split", {"test_size": 0.25}))
    executor.add_edge(WorkflowEdge("source", "split", "default", "X"))
    assert executor.find_prediction_entry_nodes() == ["source"]
    executor.inject_deployment_input("source", np.arange(24.0).reshape(8, 3), stream_name="sample")
    results = await executor.execute()
    assert results["split"]["X_train"].shape[0] == 6
    assert results["split"]["X_test"].shape[0] == 2


def _filter_workflow() -> SimpleNamespace:
    workflow = _workflow()
    workflow.project_id = 1
    workflow.nodes[1].node_type = "data.filter_samples"
    workflow.nodes[1].parameters = {
        "field": "intensity",
        "intensity_metric": "max",
        "intensity_operator": "gte",
        "intensity_threshold": 5,
    }
    workflow.edges[0].to_input = "X"
    for node in workflow.nodes:
        node.position_x = node.position_y = 0
    return workflow


def test_batch_prediction_keeps_filter_execution() -> None:
    from spectra_sherpa.app.services.batch_predict import _execute_workflow_dataset_blocking

    execution = _execute_workflow_dataset_blocking(
        _filter_workflow(),
        SherpaDataset(X=np.array([[1.0, 2.0], [10.0, 20.0]])),
        owner_user_id=1,
    )
    np.testing.assert_array_equal(execution.results["response"]["default"].X, [[10.0, 20.0]])


@pytest.mark.asyncio
async def test_deploy_input_never_fabricates_scientific_data() -> None:
    node = node_registry.create_node("deploy.input", "request", {"stream_name": "sample"})

    with pytest.raises(RuntimeError, match="cannot fabricate"):
        await node.run()


def test_external_input_admission_is_named_finite_and_two_dimensional() -> None:
    admitted = admit_deployment_input([[1.0, 2.0], [3.0, 4.0]], stream_name="sample")
    assert isinstance(admitted, SherpaDataset)
    np.testing.assert_array_equal(admitted.X, [[1.0, 2.0], [3.0, 4.0]])

    for invalid in ([1.0, 2.0], [[1.0, np.nan]], [], "not-a-matrix"):
        with pytest.raises(ValueError):
            admit_deployment_input(invalid, stream_name="sample")
    with pytest.raises(ValueError, match="portable identifier"):
        admit_deployment_input([[1.0]], stream_name="bad stream")


def test_external_input_admission_preserves_explicit_multiway_dataset() -> None:
    source = SherpaDataset(
        X=np.arange(24.0).reshape(2, 3, 4),
        layout=DatasetLayoutContext(
            kind="image",
            source_type="hyperspectral-image-cube",
            source_dtype="<f8",
            source_shape=(2, 3, 4),
            mode_roles=("spatial_y", "spatial_x", "spectral_feature"),
            image_size=(2, 3),
            image_mode=1,
            original_unfolded_shape=(6, 4),
        ),
        data_role="X_hsi",
    )

    admitted = admit_deployment_input(source, stream_name="image")

    assert admitted is source
    assert admitted.shape == (2, 3, 4)
    assert tuple(str(role) for role in admitted.layout.mode_roles) == (
        "spatial_y",
        "spatial_x",
        "spectral_feature",
    )
    with pytest.raises(ValueError, match="explicit dimension role"):
        admit_deployment_input(SherpaDataset(X=np.ones((2, 3, 4))), stream_name="untyped")
    with pytest.raises(ValueError, match="two-dimensional matrix"):
        admit_deployment_input(np.ones((2, 3, 4)), stream_name="raw")


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        ([0, 1, 0, 1], ["0", "1", "0", "1"]),
        (["01", "1", "01", "1"], ["01", "1", "01", "1"]),
        ([True, False, True, False], ["True", "False", "True", "False"]),
    ],
)
def test_deploy_categorical_target_port_matches_split_label_domain(labels, expected) -> None:
    dataset = SherpaDataset(
        X=np.arange(8.0).reshape(4, 2),
        target=np.asarray(labels),
        target_context=TargetContext(target_type="categorical"),
    )
    executor = DAGExecutor(process_pool=None)
    executor.add_node(WorkflowNode("source", "deploy.input", {"stream_name": "sample"}))
    executor.inject_deployment_input("source", dataset, stream_name="sample")

    admitted = executor.results["source"]
    assert admitted["default"] is dataset
    np.testing.assert_array_equal(admitted["default"].target, labels)
    np.testing.assert_array_equal(admitted["target"], expected)
    np.testing.assert_array_equal(deployment_target_output(dataset), expected)


def test_deploy_target_port_preserves_continuous_values_and_rejects_missing_class() -> None:
    continuous = SherpaDataset(
        X=np.arange(8.0).reshape(4, 2),
        target=np.asarray([1.5, 2.5, np.nan, 4.5]),
        target_context=TargetContext(target_type="continuous"),
    )
    assert deployment_target_output(continuous) is continuous.target

    categorical = SherpaDataset(
        X=np.arange(8.0).reshape(4, 2),
        target=np.asarray([0.0, 1.0, np.nan, 1.0]),
        target_context=TargetContext(target_type="categorical"),
    )
    with pytest.raises(ValueError, match="non-finite"):
        deployment_target_output(categorical)


def test_deploy_target_port_selects_declared_column_and_rejects_ambiguous_labels() -> None:
    dataset = SherpaDataset(
        X=np.arange(8.0).reshape(4, 2),
        target=np.asarray([[0, "wrong-a"], [1, "wrong-b"], [0, "wrong-c"], [1, "wrong-d"]], dtype=object),
        target_context=TargetContext(
            target_type="categorical",
            target_names=["Class", "Batch"],
            selected_target="Class",
        ),
    )
    executor = DAGExecutor(process_pool=None)
    executor.add_node(WorkflowNode("source", "deploy.input", {"stream_name": "sample"}))
    executor.inject_deployment_input("source", dataset, stream_name="sample")
    np.testing.assert_array_equal(executor.results["source"]["target"], ["0", "1", "0", "1"])
    np.testing.assert_array_equal(executor.results["source"]["default"].target, dataset.target)
    target, context = bind_split_target(dataset, executor.results["source"]["target"])
    np.testing.assert_array_equal(target, ["0", "1", "0", "1"])
    assert context is not None and context.selected_target == "Class"
    assert context.target_names == ["Class"]

    dataset.target_context = TargetContext(target_type="categorical", target_names=["Class", "Batch"])
    with pytest.raises(ValueError, match="requires a selected_target"):
        deployment_target_output(dataset)
    with pytest.raises(ValueError, match="requires a selected_target"):
        bind_split_target(dataset, dataset.target)

    mixed = SherpaDataset(
        X=np.arange(8.0).reshape(4, 2),
        target=np.asarray([1, "1", 2, "2"], dtype=object),
        target_context=TargetContext(target_type="categorical"),
    )
    with pytest.raises(ValueError, match="mixes source label domains"):
        deployment_target_output(mixed)
    _, unrelated_context = bind_split_target(mixed, np.asarray(["1", "1", "2", "2"]))
    assert unrelated_context is None


@pytest.mark.asyncio
async def test_deploy_x_only_path_keeps_invalid_optional_categorical_target_out_of_the_way() -> None:
    dataset = SherpaDataset(
        X=np.arange(8.0).reshape(4, 2),
        target=np.asarray([0.0, 1.0, np.nan, 1.0]),
        target_context=TargetContext(target_type="categorical"),
    )
    executor = DAGExecutor(process_pool=None)
    executor.add_node(WorkflowNode("source", "deploy.input", {"stream_name": "sample"}))
    executor.inject_deployment_input("source", dataset, stream_name="sample")
    assert executor.results["source"]["default"] is dataset
    assert "target" not in executor.results["source"]
    assert (await executor.execute())["source"]["default"] is dataset

    executor.add_node(WorkflowNode("split", "data.train_test_split", {"split_method": "stratified"}))
    executor.add_edge(WorkflowEdge("source", "split", "default", "X"))
    executor.add_edge(WorkflowEdge("source", "split", "target", "y"))
    with pytest.raises(ValueError, match="non-finite"):
        executor.inject_deployment_input("source", dataset, stream_name="sample")


@pytest.mark.asyncio
async def test_deploy_categorical_target_port_retains_authority_through_explicit_split() -> None:
    dataset = SherpaDataset(
        X=np.arange(24.0).reshape(8, 3),
        target=np.asarray([0, 0, 0, 0, 1, 1, 1, 1]),
        target_context=TargetContext(target_type="categorical", target_name="class"),
    )
    executor = DAGExecutor(process_pool=None)
    executor.add_node(WorkflowNode("source", "deploy.input", {"stream_name": "sample"}))
    executor.add_node(WorkflowNode("split", "data.train_test_split", {"test_size": 0.25, "split_method": "stratified"}))
    executor.add_edge(WorkflowEdge("source", "split", "default", "X"))
    executor.add_edge(WorkflowEdge("source", "split", "target", "y"))
    executor.inject_deployment_input("source", dataset, stream_name="sample")

    target, context = bind_split_target(dataset, executor.results["source"]["target"])
    np.testing.assert_array_equal(target, ["0", "0", "0", "0", "1", "1", "1", "1"])
    assert context is not None and context.target_type == "categorical"
    results = await executor.execute()
    assert results["split"]["X_train"].shape[0] == 6
    assert results["split"]["X_test"].shape[0] == 2

    unrelated_target, unrelated_context = bind_split_target(dataset, np.asarray(["1"] * 8))
    assert unrelated_context is None
    np.testing.assert_array_equal(unrelated_target, ["1"] * 8)


def test_exported_deploy_target_port_matches_live_categorical_projection() -> None:
    dataset = SherpaDataset(
        X=np.arange(8.0).reshape(4, 2),
        target=np.asarray([0, 1, 0, 1]),
        target_context=TargetContext(target_type="categorical"),
    )
    node = node_registry.create_node("deploy.input", "source", {"stream_name": "sample"})
    code = "\n".join([*node.python_extra_imports, *node.generate_python({}, indent="")])
    namespace: dict[str, object] = {"results": {}, "deployment_inputs": {"sample": dataset}}
    exec(code, namespace)
    projected = namespace["results"]["source"]  # type: ignore[index]
    assert projected["default"] is dataset
    np.testing.assert_array_equal(projected["target"], ["0", "1", "0", "1"])

    invalid = SherpaDataset(
        X=np.arange(8.0).reshape(4, 2),
        target=np.asarray([0.0, np.nan, 0.0, 1.0]),
        target_context=TargetContext(target_type="categorical"),
    )
    optional_namespace: dict[str, object] = {"results": {}, "deployment_inputs": {"sample": invalid}}
    exec(code, optional_namespace)
    optional_projection = optional_namespace["results"]["source"]  # type: ignore[index]
    assert optional_projection["default"] is invalid
    assert "target" not in optional_projection


@pytest.mark.parametrize("source_name", ["iris", "wine", "breast_cancer"])
def test_numeric_catalog_class_labels_complete_explicit_deploy_holdout(source_name: str) -> None:
    source = load_sklearn_reference_as_sherpa(source_name)
    train_rows, test_rows = train_test_split(
        np.arange(source.n_samples), test_size=0.25, random_state=19, stratify=source.target
    )
    graph = ss.workflow.workflow_spec(
        nodes=[
            {"node_id": "train", "node_type": "deploy.input", "parameters": {"stream_name": "train"}},
            {"node_id": "test", "node_type": "deploy.input", "parameters": {"stream_name": "test"}},
            {"node_id": "fit", "node_type": "classification.plsda", "parameters": {"n_components": 1, "scale": True}},
            {"node_id": "apply", "node_type": "classification.apply_plsda", "parameters": {}},
            {"node_id": "evaluate", "node_type": "diagnostics.classification_evaluator", "parameters": {}},
        ],
        edges=[
            {"from_node_id": "train", "to_node_id": "fit", "to_input": "X"},
            {"from_node_id": "train", "to_node_id": "fit", "from_output": "target", "to_input": "y"},
            {"from_node_id": "test", "to_node_id": "apply"},
            {"from_node_id": "fit", "to_node_id": "apply", "from_output": "fitted_state", "to_input": "fitted_state"},
            {"from_node_id": "apply", "to_node_id": "evaluate", "from_output": "y_pred", "to_input": "default"},
            {"from_node_id": "test", "to_node_id": "evaluate", "from_output": "target", "to_input": "y_true"},
        ],
    )
    result = ss.runtime.execute_workflow(
        graph,
        deployment_inputs={"train": source[train_rows], "test": source[test_rows]},
    )
    report = result.results["evaluate"]["default"]
    assert report["n_samples"] == len(test_rows)
    assert report["label_domain"] == "text"
    assert sum(map(sum, report["confusion_matrix"])) == len(test_rows)
    assert set(report["observed_labels"]) == set(np.asarray(source.target, dtype=str))


def test_raw_executor_injection_cannot_bypass_deployment_admission() -> None:
    executor = _executor()
    with pytest.raises(ValueError, match="inject_deployment_input"):
        executor.inject_result("request", SherpaDataset(X=np.ones((2, 3))))
    with pytest.raises(ValueError, match="declares stream"):
        executor.inject_deployment_input("request", [[1.0]], stream_name="other")


@pytest.mark.asyncio
async def test_live_deployment_boundary_returns_digest_bound_response() -> None:
    executor = _executor()
    payload = [[1.0, 2.0], [3.0, 4.0]]
    executor.inject_deployment_input("request", payload, stream_name="sample")

    results = await executor.execute()
    response = results["response"]
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert response == {
        "schema_version": DEPLOYMENT_RESPONSE_SCHEMA,
        "format": "json",
        "media_type": "application/json",
        "content": payload,
        "body": body.decode("utf-8"),
        "content_sha256": hashlib.sha256(body).hexdigest(),
    }


def test_exported_deployment_dag_requires_input_and_matches_live_contract() -> None:
    code = generate_python_code(_workflow())
    namespace: dict[str, object] = {"__name__": "canonical_deploy_test", "__file__": "/tmp/deploy.py"}
    exec(code, namespace)

    assert "def run_workflow(deployment_inputs=None):" in code
    assert code.count("ss.runtime.execute_workflow(") == 1
    assert "np.zeros" not in code
    results = namespace["run_workflow"]({"sample": [[1.0, 2.0], [3.0, 4.0]]})  # type: ignore[operator]
    assert results["response"] == format_deployment_output(
        [[1.0, 2.0], [3.0, 4.0]],
        output_format="json",
    )
    with pytest.raises(ValueError, match=r"unexpected=.*other"):
        namespace["run_workflow"]({"sample": [[1.0, 2.0]], "other": [[3.0, 4.0]]})  # type: ignore[operator]


def test_deployment_stream_set_is_one_shared_closed_contract() -> None:
    payload = {"sample": [[1.0]], "reference": [[2.0]]}
    assert validate_deployment_input_set(payload, expected_streams=("sample", "reference")) is payload

    with pytest.raises(ValueError, match="missing: reference"):
        validate_deployment_input_set({"sample": [[1.0]]}, expected_streams=("sample", "reference"))
    with pytest.raises(ValueError, match="duplicate input stream names"):
        validate_deployment_input_set(payload, expected_streams=("sample", "sample"))


def test_deploy_nodes_publish_closed_contracts_and_typed_response() -> None:
    input_metadata = node_registry.get_metadata("deploy.input")
    output_metadata = node_registry.get_metadata("deploy.output")

    input_contract = input_metadata.resolved_execution_contract()
    assert input_contract is not None
    assert input_contract.payload["implementation_version"] == "3.1.0"
    assert input_contract.payload["input_rank_policy"] == "preserves_nd"
    assert input_contract.payload["target_access"] == "optional"
    assert input_metadata.output_ports is not None
    assert [port.name for port in input_metadata.output_ports] == ["default", "target"]
    assert input_metadata.output_ports[1].required is False
    assert output_metadata.resolved_execution_contract() is not None
    assert output_metadata.output_ports is not None
    assert output_metadata.output_ports[0].type_ref == "spectrasherpa://types/DeploymentResponse/1.0"


def test_exported_deploy_input_accepts_portable_node_id_punctuation() -> None:
    workflow = _workflow()
    workflow.nodes[0].node_id = "request.with-hyphen"
    workflow.edges[0].from_node_id = "request.with-hyphen"

    code = generate_python_code(workflow)
    namespace: dict[str, object] = {"__name__": "portable_deploy_test", "__file__": "/tmp/deploy.py"}
    exec(code, namespace)

    results = namespace["run_workflow"]({"sample": [[1.0, 2.0]]})  # type: ignore[operator]
    assert np.asarray(results["request.with-hyphen"]["default"].X).shape == (1, 2)


def test_deployment_formatting_has_a_fixed_size_performance_ceiling() -> None:
    payload = np.arange(200 * 1600, dtype=np.float64).reshape(200, 1600)
    with PerformanceCeiling("deploy.output", "200x1600-json", 5.0).measure():
        response = format_deployment_output(payload, output_format="json")

    assert response["content_sha256"]
    assert hashlib.sha256(response["body"].encode("utf-8")).hexdigest() == response["content_sha256"]
