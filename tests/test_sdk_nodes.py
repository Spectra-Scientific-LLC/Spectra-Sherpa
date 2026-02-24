from __future__ import annotations

import uuid

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.executor import DAGExecutor, WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.meta_helpers import get_processing_history
from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodeResult,
    PortMetadata,
    node_registry,
    register_node,
)
from spectra_sherpa.sdk import ChemometricsNode, param_bool, param_number, param_select, param_text


class _ScaleNode(ChemometricsNode):
    node_type = "test.sdk.scale"
    category = "preprocessing"
    label = "Scale"
    description = "Scale test"
    parameters = [param_number("factor", default=2.0, min_value=0.0)]

    def process(self, dataset, factor: float = 2.0):
        return np.asarray(dataset.data, dtype=np.float64) * factor


def test_metadata_synthesis_from_explicit_parameters() -> None:
    meta = _ScaleNode.get_metadata()
    assert meta.node_type == "test.sdk.scale"
    assert meta.category == "preprocessing"
    assert meta.parameters[0].name == "factor"
    assert meta.parameters[0].param_type == "number"


class _InferredNode(ChemometricsNode):
    node_type = "test.sdk.infer"
    category = "preprocessing"
    label = "Infer"

    def process(self, dataset, factor: float = 2.0, enabled: bool = True, label: str = "x", count: int = 1):
        if enabled:
            return np.asarray(dataset.data, dtype=np.float64) * factor + count
        return np.asarray(dataset.data, dtype=np.float64)


def test_parameter_inference_from_process_signature() -> None:
    meta = _InferredNode.get_metadata()
    by_name = {p.name: p for p in meta.parameters}
    assert by_name["factor"].param_type == "number"
    assert by_name["enabled"].param_type == "boolean"
    assert by_name["label"].param_type == "text"
    assert by_name["count"].param_type == "number"


class _UnsupportedAnnotationNode(ChemometricsNode):
    node_type = "test.sdk.bad_ann"
    category = "preprocessing"
    label = "Bad"

    def process(self, dataset, values: list[int]):
        return dataset


def test_unsupported_inferred_annotation_raises() -> None:
    with pytest.raises(TypeError, match="Unsupported annotation"):
        _UnsupportedAnnotationNode.get_metadata()


class _MissingAttrsNode(ChemometricsNode):
    category = "preprocessing"
    label = "Missing"

    def process(self, dataset):
        return dataset


def test_missing_required_class_attrs_raise() -> None:
    with pytest.raises(ValueError, match="missing required class attribute"):
        _MissingAttrsNode.get_metadata()


@pytest.mark.asyncio
async def test_execute_wraps_ndarray_and_records_diagnostics() -> None:
    node = _ScaleNode("n1", {"factor": 3.0})
    ds = SherpaDataset(X=np.array([[1.0, 2.0], [3.0, 4.0]]))

    result = await node.run(ds)
    out = result.outputs["default"]

    assert isinstance(out, SherpaDataset)
    np.testing.assert_allclose(out.data, ds.data * 3.0)
    assert result.diagnostics["output_shape"] == [2, 2]
    assert "output_mean" in result.diagnostics

    history = get_processing_history(out)
    assert history[-1]["op_id"] == "test.sdk.scale"


@pytest.mark.asyncio
async def test_execute_accepts_dataset_return_from_process() -> None:
    class _DatasetReturnNode(ChemometricsNode):
        node_type = "test.sdk.ds_return"
        category = "preprocessing"
        label = "DatasetReturn"

        def process(self, dataset):
            cloned = dataset.copy()
            cloned.data[:] = cloned.data + 1.0
            return cloned

    node = _DatasetReturnNode("n2")
    ds = SherpaDataset(X=np.array([[1.0, 2.0]]))

    result = await node.run(ds)
    out = result.outputs["default"]
    assert isinstance(out, SherpaDataset)
    np.testing.assert_allclose(out.data, np.array([[2.0, 3.0]]))


def test_param_helpers_build_expected_shapes() -> None:
    p_num = param_number("alpha", default=0.5, min_value=0.0)
    p_bool = param_bool("center", default=True)
    p_text = param_text("label", default="demo")
    p_select = param_select("mode", options=["a", "b"], default="a")

    assert p_num.param_type == "number"
    assert p_bool.param_type == "boolean"
    assert p_text.param_type == "text"
    assert p_select.param_type == "select"
    assert p_select.options[0]["value"] == "a"


def test_numpy_expr_export_support() -> None:
    class _ExportNode(ChemometricsNode):
        node_type = "test.sdk.export"
        category = "preprocessing"
        label = "Export"
        numpy_expr = "_data * {factor}"

        def process(self, dataset, factor: float = 2.0):
            return np.asarray(dataset.data, dtype=np.float64) * factor

    node = _ExportNode("n3", {"factor": 4.0})
    assert node.supports_python_export() is True

    lines = node.generate_python({"default": "results['src']"})
    joined = "\n".join(lines)
    assert "_result = _data * 4.0" in joined


@pytest.mark.asyncio
async def test_facade_node_executes_in_dag_executor() -> None:
    source_type = f"test.sdk.source_{uuid.uuid4().hex[:8]}"
    proc_type = f"test.sdk.proc_{uuid.uuid4().hex[:8]}"

    @register_node
    class _SourceNode(Node):
        metadata = NodeMetadata(
            node_type=source_type,
            category="data",
            label="Source",
            description="source",
            parameters=[],
            input_types=[],
            output_type="NDDataset",
            output_ports=[
                PortMetadata(
                    name="default",
                    type_ref="spectrasherpa://types/SpectralDataset/1.0",
                    required=True,
                    label="Data",
                )
            ],
        )

        async def execute(self):
            dataset = self.parameters.get("dataset")
            if dataset is None:
                raise ValueError("dataset missing")
            return NodeResult(outputs={"default": dataset})

    @register_node
    class _ProcNode(ChemometricsNode):
        node_type = proc_type
        category = "preprocessing"
        label = "Proc"

        def process(self, dataset, factor: float = 2.0):
            return np.asarray(dataset.data, dtype=np.float64) * factor

    try:
        ds = SherpaDataset(X=np.array([[1.0, 2.0], [3.0, 4.0]]))
        ex = DAGExecutor(process_pool=None)
        ex.add_node(WorkflowNode(node_id="src", node_type=source_type, parameters={}))
        ex.add_node(WorkflowNode(node_id="proc", node_type=proc_type, parameters={"factor": 2.0}))
        ex.add_edge(WorkflowEdge(from_node="src", to_node="proc"))

        results = await ex.execute(initial_data={"src": {"dataset": ds}})
        out = results["proc"]["default"]

        assert isinstance(out, SherpaDataset)
        np.testing.assert_allclose(out.data, ds.data * 2.0)
    finally:
        node_registry.unregister(source_type)
        node_registry.unregister(proc_type)
