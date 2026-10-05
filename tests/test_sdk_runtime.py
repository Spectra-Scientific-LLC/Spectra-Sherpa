from __future__ import annotations

import ast
import asyncio
import hashlib
import io
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.sdk as ss
from spectra_sherpa.app.services.dag.executor import DAGExecutor
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.core.execution_runtime import ExecutionRuntime


def _dataset() -> ss.SherpaDataset:
    return ss.data.from_array(
        np.array(
            [
                [1.0, 2.0, 4.0, 8.0, 16.0],
                [2.0, 4.0, 7.0, 15.0, 31.0],
                [1.5, 2.5, 5.0, 9.0, 17.0],
            ],
            dtype=np.float64,
        ),
        x=np.arange(1000.0, 1005.0),
        samples=["a", "b", "c"],
        units="cm-1",
        data_units="absorbance",
    )


def _matrix(value):
    return np.asarray(getattr(value, "data", value), dtype=np.float64)


class _ArtifactWriter:
    def save(self, artifact_uid, manifest, arrays):
        del artifact_uid, manifest
        payload = io.BytesIO()
        np.savez_compressed(payload, **arrays)
        return hashlib.sha256(payload.getvalue()).hexdigest()

    def artifact_directory(self, artifact_uid):
        return f"memory://workbench-parity/{artifact_uid}"


def _direct_workbench_execution(workflow, payloads, *, runtime=None):
    executor = DAGExecutor(runtime=runtime)
    for node in workflow.payload["nodes"]:
        executor.add_node(
            WorkflowNode(
                node_id=node["node_id"],
                node_type=node["node_type"],
                parameters=dict(node["parameters"]),
            )
        )
    for edge in workflow.payload["edges"]:
        executor.add_edge(
            WorkflowEdge(
                from_node=edge["from_node_id"],
                to_node=edge["to_node_id"],
                from_output=edge["from_output"],
                to_input=edge["to_input"],
            )
        )
    for node_id, node in executor.nodes.items():
        if node.metadata is None or node.metadata.node_type != "deploy.input":
            continue
        stream_name = node.parameters["stream_name"]
        executor.inject_deployment_input(node_id, payloads[stream_name], stream_name=stream_name)
    return asyncio.run(executor.execute())


def test_operation_workflow_binds_content_addressed_deployment_input() -> None:
    workflow, payloads, digests = ss.runtime.operation_workflow(
        "preprocess.normalize",
        parameters={"method": "snv"},
        inputs={"default": _dataset()},
    )

    source = next(node for node in workflow.payload["nodes"] if node["node_type"] == "deploy.input")
    assert source["parameters"]["stream_name"].endswith(next(iter(digests.values()))[:16])
    assert set(payloads) == set(digests) == {source["parameters"]["stream_name"]}
    assert {node["node_type"] for node in workflow.payload["nodes"]} == {
        "deploy.input",
        "preprocess.normalize",
    }
    assert workflow.payload["edges"] == [
        {
            "from_node_id": source["node_id"],
            "to_node_id": "sdk.operation",
            "from_output": "default",
            "to_input": "default",
        }
    ]


def test_sdk_and_workbench_execute_the_same_native_graph() -> None:
    workflow, payloads, _ = ss.runtime.operation_workflow(
        "preprocess.normalize",
        parameters={"method": "snv"},
        inputs={"default": _dataset()},
    )

    sdk_execution = ss.runtime.execute_workflow(workflow, deployment_inputs=payloads)
    workbench_results = _direct_workbench_execution(workflow, payloads)

    sdk_output = sdk_execution.output()
    workbench_output = workbench_results["sdk.operation"]["default"]
    np.testing.assert_array_equal(np.asarray(sdk_output.data), np.asarray(workbench_output.data))
    sdk_provenance = sdk_output.provenance.to_list()
    workbench_provenance = workbench_output.provenance.to_list()
    for record in (*sdk_provenance, *workbench_provenance):
        record.pop("timestamp")
    assert sdk_provenance == workbench_provenance
    assert sdk_output.units == workbench_output.units == "dimensionless"


def test_sdk_execution_rejects_implicit_or_wrong_external_inputs() -> None:
    workflow, payloads, _ = ss.runtime.operation_workflow(
        "preprocess.normalize",
        parameters={"method": "snv"},
        inputs={"default": _dataset()},
    )

    with pytest.raises(ValueError, match="does not match workflow"):
        ss.runtime.execute_workflow(workflow, deployment_inputs={})
    with pytest.raises(ValueError, match="does not match workflow"):
        ss.runtime.execute_workflow(workflow, deployment_inputs={**payloads, "unexpected": _dataset()})

    implicit = ss.workflow.workflow_spec(
        nodes=[{"node_id": "normalize", "node_type": "preprocess.normalize", "parameters": {"method": "snv"}}],
        edges=[],
    )
    with pytest.raises(ValueError, match="only explicit deploy.input sources"):
        ss.runtime.execute_workflow(implicit, deployment_inputs={})


def test_deployment_input_exposes_only_an_explicit_embedded_target() -> None:
    dataset = _dataset()
    dataset.target = np.array([1.0, 2.0, 3.0])
    workflow = ss.workflow.workflow_spec(
        nodes=[
            {
                "node_id": "source",
                "node_type": "deploy.input",
                "parameters": {
                    "stream_name": "calibration",
                    "schema_version": ss.deployment.DEPLOYMENT_INPUT_SCHEMA,
                },
            }
        ],
        edges=[],
    )
    execution = ss.runtime.execute_workflow(workflow, deployment_inputs={"calibration": dataset})

    np.testing.assert_array_equal(execution.results["source"]["target"], dataset.target)
    assert execution.output("source") is execution.results["source"]["default"]

    without_target = _dataset()
    source_only = ss.runtime.execute_workflow(workflow, deployment_inputs={"calibration": without_target})
    assert set(source_only.results["source"]) == {"default"}


def test_sync_runtime_bridge_is_safe_inside_an_event_loop() -> None:
    async def invoke() -> np.ndarray:
        return np.asarray(
            ss.runtime.execute_operation(
                "preprocess.normalize",
                parameters={"method": "snv"},
                inputs={"default": _dataset()},
            )
            .output()
            .data
        )

    output = asyncio.run(invoke())
    np.testing.assert_allclose(np.mean(output, axis=1), 0.0, atol=1e-12)


def test_sdk_and_workbench_execute_the_same_native_pca_graph_with_explicit_artifact_sinks() -> None:
    workflow, payloads, _ = ss.runtime.operation_workflow(
        "model.pca",
        parameters={"n_components": "2", "standardized": False, "scaled": False},
        inputs={"default": _dataset()},
    )
    result = ss.explore.pca(_dataset(), n_components=2)
    workbench = _direct_workbench_execution(
        workflow,
        payloads,
        runtime=ExecutionRuntime(model_artifact_writer=_ArtifactWriter()),
    )["sdk.operation"]

    assert result.scores.shape == (3, 2)
    assert result.loadings.shape == (2, 5)
    assert len(result.artifacts) == 1
    assert result.artifacts[0]["artifact_dir"].startswith("memory://spectra-sherpa-sdk/")
    assert result.outputs["model_id"] == result.artifacts[0]["artifact_uid"]
    np.testing.assert_allclose(np.abs(_matrix(result.scores)), np.abs(_matrix(workbench["scores"])))
    np.testing.assert_allclose(np.abs(_matrix(result.loadings)), np.abs(_matrix(workbench["loadings"])))
    np.testing.assert_allclose(result.explained_variance, workbench["explained_variance"])


def test_sdk_scientific_conveniences_have_no_direct_node_or_estimator_authority() -> None:
    sdk_dir = Path(__file__).parents[1] / "src" / "spectra_sherpa" / "sdk"
    for filename in ("preprocess.py", "regression.py", "explore.py", "validate.py"):
        source = (sdk_dir / filename).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=filename)
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)
                imports.update(alias.name for alias in node.names)
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert not any("app.services.dag.nodes" in name for name in imports)
        assert calls.isdisjoint({"execute", "fit", "predict", "fit_transform", "transform"})
        if filename != "validate.py":
            assert "execute_operation" in source

    validate_source = (sdk_dir / "validate.py").read_text(encoding="utf-8")
    for retired_authority in ("GridSearchCV", "sklearn.base", "sklearn.pipeline"):
        assert retired_authority not in validate_source
