"""Fail-closed tests for the canonical scientific transport boundary."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from functools import partial
from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.services.dag.executor import DAGExecutor, WorkflowNode
from spectra_sherpa.app.services.dag.executor_pool import WorkerExecutionContext, _run_node_in_worker
from spectra_sherpa.app.services.dag.io_contracts import coerce_to_sherpa
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from spectra_sherpa.app.services.dag.node_base import Node, NodeMetadata, NodeResult, node_registry
from spectra_sherpa.app.services.dag.serialize import serialize_for_api
from spectra_sherpa.app.services.dag.transport import (
    is_spectrochempy_runtime_object,
    reject_spectrochempy_transport,
    require_raw_matrix_container,
)
from spectra_sherpa.app.services.model_application import _loaded_files_to_sherpa
from spectra_sherpa.app.services.serialization import serialize_result
from spectra_sherpa.core.execution_runtime import ExecutionRuntime
from spectra_sherpa.sdk.deployment import admit_deployment_input, format_deployment_output


def _foreign_runtime_value() -> object:
    foreign_type = type("ScientificDataset", (), {"__module__": "spectrochempy.core.dataset"})
    return foreign_type()


@dataclass
class _Envelope:
    payload: object


class _SlotsEnvelope:
    __slots__ = ("model",)

    def __init__(self, model: object) -> None:
        self.model = model


class _ArrayEnvelope(np.ndarray):
    pass


class _MappingEnvelope(dict):
    pass


class _PassNode(Node):
    metadata = NodeMetadata(
        node_type="test.transport.pass",
        category="test",
        label="Transport pass",
        description="Return the input",
        parameters=[],
    )

    async def execute(self, value):
        return value


class _ForeignOutputNode(Node):
    metadata = NodeMetadata(
        node_type="test.transport.output",
        category="test",
        label="Transport output",
        description="Return a forbidden value",
        parameters=[],
    )

    async def execute(self):
        return {"nested": [_foreign_runtime_value()]}


def test_detection_uses_module_identity_without_importing_optional_runtime(monkeypatch) -> None:
    unrelated_type = type("NDDataset", (), {"__module__": "scientist_extension"})
    imported: list[str] = []

    def _unexpected_import(name: str, *args, **kwargs):
        imported.append(name)
        raise AssertionError(f"boundary imported {name}")

    monkeypatch.setattr("builtins.__import__", _unexpected_import)
    assert is_spectrochempy_runtime_object(_foreign_runtime_value()) is True
    assert is_spectrochempy_runtime_object(unrelated_type()) is False
    assert imported == []


def test_recursive_boundary_rejects_nested_dataclass_object_array_and_cycles() -> None:
    foreign = _foreign_runtime_value()
    cycle: list[object] = []
    cycle.append(cycle)
    payload = {
        "cycle": cycle,
        "envelope": _Envelope(payload=np.asarray([[foreign]], dtype=object)),
    }

    with pytest.raises(TypeError, match=r"SpectroChemPy runtime object .*\.flat\[0\]"):
        reject_spectrochempy_transport(payload, boundary="test boundary")


@pytest.mark.asyncio
async def test_recursive_boundary_rejects_slots_only_envelopes_at_every_shared_consumer() -> None:
    envelope = _SlotsEnvelope(_foreign_runtime_value())
    with pytest.raises(TypeError, match=r"SpectroChemPy runtime object .*\.model"):
        reject_spectrochempy_transport(envelope, boundary="test boundary")
    with pytest.raises(TypeError, match="workflow API serialization"):
        serialize_result(envelope)
    with pytest.raises(TypeError, match="process-pool submission"):
        DAGExecutor._sanitize_for_pool(envelope)
    with pytest.raises(TypeError, match="node 'slots-input' input"):
        await _PassNode("slots-input").run(envelope)


@pytest.mark.asyncio
async def test_recursive_boundary_rejects_opaque_containers_at_every_shared_consumer() -> None:
    foreign = _foreign_runtime_value()
    record_array = np.empty(1, dtype=[("model", object)])
    record_array["model"][0] = foreign
    array_subclass = np.ones((2, 2)).view(_ArrayEnvelope)
    array_subclass.payload = foreign
    mapping_subclass = _MappingEnvelope()
    mapping_subclass.payload = foreign
    payloads = (deque([foreign]), record_array[0], array_subclass, mapping_subclass, partial(int, foreign))

    for index, payload in enumerate(payloads):
        with pytest.raises(TypeError, match="SpectroChemPy runtime object"):
            reject_spectrochempy_transport(payload, boundary="opaque test boundary")
        with pytest.raises(TypeError, match="workflow API serialization"):
            serialize_result(payload)
        with pytest.raises(TypeError, match="process-pool submission"):
            DAGExecutor._sanitize_for_pool(payload)
        with pytest.raises(TypeError, match=f"node 'opaque-input-{index}' input"):
            await _PassNode(f"opaque-input-{index}").run(payload)

    with pytest.raises(TypeError, match="deployment stream 'sample' admission"):
        admit_deployment_input(array_subclass, stream_name="sample")


def test_foreign_duck_array_is_rejected_before_array_coercion() -> None:
    converted = False

    class ForeignArray:
        def __array__(self, *args, **kwargs):
            nonlocal converted
            converted = True
            return np.ones((2, 2))

    with pytest.raises(TypeError, match="explicit numpy/list/tuple matrix"):
        require_raw_matrix_container(ForeignArray(), input_name="external input")
    assert converted is False


def test_io_and_sdk_helpers_do_not_translate_foreign_scientific_containers() -> None:
    foreign = _foreign_runtime_value()
    with pytest.raises(TypeError, match="canonical dataset admission"):
        coerce_to_sherpa(foreign, allow_array=True)
    with pytest.raises(TypeError, match="metadata helper admission"):
        add_processing_step(foreign, "test.operation", {})


def test_canonical_dataset_wrappers_cannot_smuggle_foreign_runtime_objects() -> None:
    foreign = _foreign_runtime_value()
    dataset = coerce_to_sherpa(np.ones((2, 2)), allow_array=True)
    dataset.meta["nested"] = foreign

    with pytest.raises(TypeError, match="deployment stream 'sample' admission"):
        admit_deployment_input(dataset, stream_name="sample")
    with pytest.raises(TypeError, match="canonical dataset admission"):
        coerce_to_sherpa(dataset)
    with pytest.raises(TypeError, match="metadata helper admission"):
        add_processing_step(dataset, "test.operation", {})

    target_wrapped = coerce_to_sherpa(np.ones((2, 2)), allow_array=True)
    target_wrapped.target = np.asarray([[foreign], [foreign]], dtype=object)
    with pytest.raises(TypeError, match=r"deployment stream 'sample' admission.*target\.flat\[0\]"):
        admit_deployment_input(target_wrapped, stream_name="sample")


def test_model_application_requires_native_loader_output() -> None:
    foreign_type = type("ScientificDataset", (), {"__module__": "spectrochempy.core.dataset"})
    foreign = foreign_type()
    foreign.shape = (2, 3)
    foreign.data = np.ones((2, 3))
    item = SimpleNamespace(dataset=foreign, file_name="foreign.spc")
    with pytest.raises(TypeError, match="model dataset-loader handoff"):
        _loaded_files_to_sherpa([item], "foreign")


def test_model_application_rejects_foreign_state_nested_in_native_loader_output() -> None:
    dataset = coerce_to_sherpa(np.ones((2, 3)), allow_array=True)
    dataset.meta["nested"] = _foreign_runtime_value()
    item = SimpleNamespace(dataset=dataset, file_name="foreign.spc")
    with pytest.raises(TypeError, match="model dataset-loader handoff"):
        _loaded_files_to_sherpa([item], "foreign")


def test_sdk_admission_and_response_reject_foreign_runtime_objects() -> None:
    foreign = _foreign_runtime_value()
    with pytest.raises(TypeError, match="deployment stream 'sample' admission"):
        admit_deployment_input(foreign, stream_name="sample")
    with pytest.raises(TypeError, match="deployment response formatting"):
        format_deployment_output({"nested": [foreign]}, output_format="json")


@pytest.mark.asyncio
async def test_direct_node_run_rejects_foreign_input_and_nested_output() -> None:
    foreign = _foreign_runtime_value()
    with pytest.raises(TypeError, match="node 'input' input"):
        await _PassNode("input").run(foreign)
    with pytest.raises(TypeError, match="node 'output' output"):
        await _ForeignOutputNode("output").run()


def test_executor_injection_and_pool_submission_reject_nested_foreign_values() -> None:
    foreign = _foreign_runtime_value()
    executor = DAGExecutor(process_pool=None)
    executor.add_node(WorkflowNode("snv", "preprocess.normalize", {"method": "snv"}))

    with pytest.raises(TypeError, match="executor injection"):
        executor.inject_result("snv", {"nested": foreign})
    with pytest.raises(TypeError, match="process-pool submission"):
        executor._sanitize_for_pool({"nested": [foreign]})


def test_worker_rejects_a_foreign_result_even_if_a_node_wrapper_is_bypassed(monkeypatch) -> None:
    foreign = _foreign_runtime_value()
    node = node_registry.create_node("preprocess.normalize", "worker-output", {"method": "snv"})

    async def _bypassed_run(*args, **kwargs):
        return NodeResult(outputs={"nested": [foreign]})

    monkeypatch.setattr(node, "run", _bypassed_run)
    monkeypatch.setattr(node_registry, "create_node", lambda *args, **kwargs: node)
    with pytest.raises(TypeError, match="worker output"):
        _run_node_in_worker(
            node_type="preprocess.normalize",
            node_id="worker-output",
            parameters={"method": "snv"},
            args=(),
            kwargs={},
            worker_context=WorkerExecutionContext(
                execution_id="transport-boundary-test",
                runtime=ExecutionRuntime(),
                capabilities=("read_dataset",),
            ),
        )


def test_api_serializers_reject_nested_foreign_runtime_objects() -> None:
    foreign = _foreign_runtime_value()
    with pytest.raises(TypeError, match="workflow API serialization"):
        serialize_result(SimpleNamespace(payload={"nested": [foreign]}))
    with pytest.raises(TypeError, match="dataset API serialization"):
        serialize_for_api(foreign)


@pytest.mark.asyncio
async def test_real_spectrochempy_dataset_is_rejected_when_optional_extra_is_installed() -> None:
    scp = pytest.importorskip("spectrochempy")
    dataset = scp.NDDataset(np.ones((2, 2)))

    with pytest.raises(TypeError, match="SpectroChemPy runtime object NDDataset"):
        admit_deployment_input(dataset, stream_name="sample")
    with pytest.raises(TypeError, match="SpectroChemPy runtime object NDDataset"):
        serialize_result({"nested": dataset})

    metadata_wrapped = coerce_to_sherpa(np.ones((2, 2)), allow_array=True)
    metadata_wrapped.meta["nested"] = dataset
    with pytest.raises(TypeError, match="deployment stream 'sample' admission"):
        admit_deployment_input(metadata_wrapped, stream_name="sample")

    target_wrapped = coerce_to_sherpa(np.ones((2, 2)), allow_array=True)
    object_target = np.empty((2, 1), dtype=object)
    object_target[:, 0] = [dataset, dataset]
    target_wrapped.target = object_target
    with pytest.raises(TypeError, match=r"deployment stream 'sample' admission.*target\.flat\[0\]"):
        admit_deployment_input(target_wrapped, stream_name="sample")

    with pytest.raises(TypeError, match=r"SpectroChemPy runtime object NDDataset.*\.model"):
        reject_spectrochempy_transport(_SlotsEnvelope(dataset), boundary="real slots boundary")

    record_array = np.empty(1, dtype=[("model", object)])
    record_array["model"][0] = dataset
    array_subclass = np.ones((2, 2)).view(_ArrayEnvelope)
    array_subclass.payload = dataset
    mapping_subclass = _MappingEnvelope()
    mapping_subclass.payload = dataset
    opaque_payloads = (
        deque([dataset]),
        record_array[0],
        array_subclass,
        mapping_subclass,
        partial(int, dataset),
    )
    for index, payload in enumerate(opaque_payloads):
        with pytest.raises(TypeError, match="SpectroChemPy runtime object NDDataset"):
            reject_spectrochempy_transport(payload, boundary="real opaque boundary")
        with pytest.raises(TypeError, match="workflow API serialization"):
            serialize_result(payload)
        with pytest.raises(TypeError, match="process-pool submission"):
            DAGExecutor._sanitize_for_pool(payload)
        with pytest.raises(TypeError, match=f"node 'real-opaque-{index}' input"):
            await _PassNode(f"real-opaque-{index}").run(payload)

    with pytest.raises(TypeError, match="deployment stream 'sample' admission"):
        admit_deployment_input(array_subclass, stream_name="sample")
