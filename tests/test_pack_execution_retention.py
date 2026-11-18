"""Pack identity crosses SDK and producing-artifact boundaries before execution."""

import json
import pickle
from copy import deepcopy

import numpy as np
import pytest

from spectra_sherpa.app.services.dag.executor import DAGExecutor
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.pack_execution_access import PackExecutionDenied, use_pack_execution_authorizer
from spectra_sherpa.app.services.dag.pack_requirements import PackBindingAdmissionError, capture_pack_graph_binding
from spectra_sherpa.core.execution_runtime import ExecutionRuntime
from spectra_sherpa.core.pack_requirements import parse_pack_graph_binding
from spectra_sherpa.sdk import data, runtime
from spectra_sherpa.sdk.workflow import WorkflowSchemaError, WorkflowSpec, workflow_spec
from tests.pack_retention_fixtures import make_retained_registry
from tests.test_pack_manifest import pack


@pytest.fixture
def retained_registry(monkeypatch):
    return make_retained_registry(monkeypatch)


async def allow_reference_pack(required):
    assert required == (pack().reference,)


def test_sdk_pack_spec_preserves_build_identity_and_legacy_oss_wire(retained_registry):
    spec = workflow_spec(nodes=[{"node_id": "p", "node_type": "pro.reference.record"}], edges=[])
    assert spec.payload["schema_version"] == "spectra-sherpa-workflow/2"
    assert WorkflowSpec.from_dict(spec.as_dict()) == spec
    assert workflow_spec(nodes=[{"node_id": "o", "node_type": "preprocess.clip_floor"}], edges=[]).payload == {
        "schema_version": "spectra-sherpa-workflow/1",
        "nodes": [{"node_id": "o", "node_type": "preprocess.clip_floor", "parameters": {}}],
        "edges": [],
    }
    retained_registry._pack_manifests = (pack(build_sha256="b" * 64),)
    with pytest.raises(WorkflowSchemaError, match="pack binding"):
        WorkflowSpec.from_dict(spec.as_dict())
    assert spec.payload["pack_binding"]["nodes"][0]["required"][0]["build_sha256"] == "a" * 64


async def test_actual_sdk_pack_operation_and_stripped_identity_refusal(retained_registry):
    dataset = data.from_array(np.array([[-1.0, 2.0, -3.0], [4.0, -5.0, 6.0]]), x=np.arange(3.0), units="cm-1")
    spec, inputs, _ = runtime.operation_workflow(
        "pro.reference.record", parameters={"floor": 0.0}, inputs={"default": dataset}
    )
    with pytest.raises(PackExecutionDenied, match="reference"):
        await runtime.execute_workflow_async(spec, deployment_inputs=inputs)
    with use_pack_execution_authorizer(allow_reference_pack):
        execution = await runtime.execute_workflow_async(spec, deployment_inputs=inputs)
    np.testing.assert_array_equal(execution.output().data, [[0.0, 2.0, 0.0], [4.0, 0.0, 6.0]])
    copied = pickle.loads(pickle.dumps(execution.output().copy()))
    recorded = [entry.pack_binding for entry in copied.provenance if entry.pack_binding is not None]
    assert len(recorded) == 1
    assert recorded[0].required == (pack().reference,)
    retained_registry._pack_manifests = ()
    retained_registry._nodes.pop("pro.reference.record")
    ordinary, ordinary_inputs, _ = runtime.operation_workflow(
        "preprocess.clip_floor", parameters={"floor": 1.0}, inputs={"default": copied}
    )
    assert "pack_binding" not in ordinary.payload
    reused = await runtime.execute_workflow_async(ordinary, deployment_inputs=ordinary_inputs)
    assert [entry.pack_binding for entry in reused.output().provenance if entry.pack_binding] == recorded
    np.testing.assert_array_equal(reused.output().data, [[1.0, 2.0, 1.0], [4.0, 1.0, 6.0]])
    spec.payload.pop("pack_binding")
    with pytest.raises(WorkflowSchemaError):
        await runtime.execute_workflow_async(spec, deployment_inputs=inputs)


async def test_retained_pack_values_remain_readable_without_pack_code(retained_registry, tmp_path, monkeypatch):
    from dataclasses import replace

    from spectra_sherpa.app.schemas.run_evidence import RunEvidence
    from spectra_sherpa.app.services import run_output_retention as retention
    from spectra_sherpa.app.services.serialization import serialize_result

    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    dataset = data.from_array(
        np.array([[-1.0, 2.0], [3.0, -4.0]]), x=np.array([1000.0, 1100.0]), units="cm-1", data_units="absorbance"
    )
    spec, inputs, _ = runtime.operation_workflow(
        "pro.reference.record", parameters={"floor": 0.0}, inputs={"default": dataset}
    )
    with use_pack_execution_authorizer(allow_reference_pack):
        execution = await runtime.execute_workflow_async(spec, deployment_inputs=inputs)
    output = execution.output()
    expected = json.loads(json.dumps(serialize_result(output, owner_user_id=1, retain_full=True)))
    evidence = RunEvidence.model_validate(retention.retain_run_outputs(1, {"pack": {"default": output}}, {}))
    receipt = evidence.outputs["pack"]["default"]
    assert receipt.state == "exact"
    retained_registry._pack_manifests = ()
    retained_registry._nodes.pop("pro.reference.record")

    def no_executable_admission(*args, **kwargs):
        raise AssertionError("reading retained values must not construct pack code")

    monkeypatch.setattr(retained_registry, "create_node", no_executable_admission)
    restored = retention.read_output(1, receipt)
    assert restored == expected
    assert restored["data"] == [[0.0, 2.0], [3.0, 0.0]]
    history = restored["metadata"]["processing_history"]
    assert history[-1]["pack_binding"]["required"][0]["build_sha256"] == "a" * 64


async def test_direct_executor_refuses_unbound_pack_before_node_code(retained_registry):
    executor = DAGExecutor(process_pool=False)
    executor.add_node(WorkflowNode(node_id="p", node_type="pro.reference.record", parameters={}))
    with pytest.raises(PackBindingAdmissionError) as error:
        await executor.execute_node("p")
    assert error.value.problems[0].reason == "missing_binding"
    assert executor.results == {}


async def test_model_publication_binds_only_producing_ancestors_before_writer(retained_registry):
    nodes = [
        {"node_id": "producer", "node_type": "model.pca"},
        {"node_id": "parent", "node_type": "pro.reference.record"},
        {"node_id": "unrelated", "node_type": "pro.reference.record"},
    ]
    binding = capture_pack_graph_binding(nodes, registry=retained_registry)
    published = []

    class Writer:
        def save(self, uid, manifest, arrays):
            published.append(deepcopy(manifest))
            return "a" * 64

        def artifact_directory(self, uid):
            return f"memory://{uid}"

    executor = DAGExecutor(
        process_pool=False, runtime=ExecutionRuntime(model_artifact_writer=Writer()), pack_binding=binding
    )
    for node in nodes:
        executor.add_node(WorkflowNode(**node, parameters={}))
    executor.add_edge(WorkflowEdge(from_node="parent", to_node="producer"))
    executor._admit_pack_bindings()
    executor.results["producer"] = {"_model_artifact": {"metadata": {"model_type": "pca"}, "arrays": {}}}
    await executor._process_model_artifact("producer")
    assert len(published) == 1
    retained = parse_pack_graph_binding(json.dumps(published[0]["pack_production_binding"]).encode())
    assert [node.node_id for node in retained.nodes] == ["parent"]
    assert published[0]["producer_node_type"] == "model.pca"
    assert "model_id" in executor.results["producer"]


@pytest.mark.parametrize("has_unrelated_pack", [False, True])
async def test_model_publication_refuses_forged_pack_production_before_writer(retained_registry, has_unrelated_pack):
    binding = capture_pack_graph_binding(
        [{"node_id": "unrelated", "node_type": "pro.reference.record"}], registry=retained_registry
    )
    published = []

    class Writer:
        def save(self, *args):
            published.append(args)
            raise AssertionError("contradictory provenance reached publication")

    executor = DAGExecutor(
        process_pool=False,
        runtime=ExecutionRuntime(model_artifact_writer=Writer()),
        pack_binding=binding if has_unrelated_pack else None,
    )
    executor.add_node(WorkflowNode(node_id="producer", node_type="model.pca", parameters={}))
    if has_unrelated_pack:
        executor.add_node(WorkflowNode(node_id="unrelated", node_type="pro.reference.record", parameters={}))
    executor.results["producer"] = {
        "_model_artifact": {
            "metadata": {"model_type": "pca", "pack_production_binding": binding.model_dump(mode="json")},
            "arrays": {},
        }
    }
    with pytest.raises(ValueError, match="executing pack provenance"):
        await executor._process_model_artifact("producer")
    assert published == []
    assert "_model_artifact" in executor.results["producer"]


def test_imported_processing_provenance_cannot_claim_another_node(retained_registry):
    from spectra_sherpa.app.lib.sherpa_dataset import ProvenanceEntry

    binding = capture_pack_graph_binding(
        [{"node_id": "actual", "node_type": "pro.reference.record"}], registry=retained_registry
    ).nodes[0]
    for node_id in (None, "different"):
        with pytest.raises(ValueError, match="recorded processing node"):
            ProvenanceEntry(op_id="preprocess.clip_floor", node_id=node_id, pack_binding=binding)
    assert (
        ProvenanceEntry(op_id="preprocess.clip_floor", node_id="actual", pack_binding=binding).pack_binding == binding
    )


@pytest.mark.parametrize("recorded_node_id", [None, "different"])
async def test_actual_pack_run_cannot_silently_drop_producer_identity(retained_registry, monkeypatch, recorded_node_id):
    from spectra_sherpa.app.lib.sherpa_dataset import Provenance
    from spectra_sherpa.core.pack_execution_context import current_pack_producer

    history = Provenance()
    node = retained_registry.create_node("pro.reference.record", "actual", {})

    async def execute():
        history.append("preprocess.clip_floor", node_id=recorded_node_id)
        return {"recorded": True}

    monkeypatch.setattr(node, "execute", execute)
    if recorded_node_id is None:
        await node.run()
        entry = next(iter(history))
        assert entry.node_id == "actual"
        assert entry.pack_binding.node_id == "actual"
        assert entry.pack_binding.required == (pack().reference,)
    else:
        with pytest.raises(ValueError, match="executing processing node"):
            await node.run()
        assert not history
    assert current_pack_producer(None) is None


async def test_model_replay_keeps_processing_pack_identity_when_dataset_moves(monkeypatch):
    from spectra_sherpa.app.services.dag.nodes.modeling._artifact_builder import _enrich_with_preprocessing
    from spectra_sherpa.app.services.dag.nodes.preprocessing.normalize_node import NormalizeNode
    from spectra_sherpa.app.services.dag.pack_execution_access import use_admitted_pack_replay
    from spectra_sherpa.app.services.model_application import _prepare_artifact_input
    from spectra_sherpa.core.pack_requirements import read_pack_preprocessing_binding

    retained_registry = make_retained_registry(monkeypatch, base_node=NormalizeNode)
    original = data.from_array(np.array([[-1.0, 2.0, -3.0], [4.0, -5.0, 6.0]]), x=np.arange(3.0), units="cm-1")
    spec, inputs, _ = runtime.operation_workflow(
        "pro.reference.record", parameters={"method": "snv"}, inputs={"default": original}
    )
    with use_pack_execution_authorizer(allow_reference_pack):
        execution = await runtime.execute_workflow_async(spec, deployment_inputs=inputs)
    moved = pickle.loads(pickle.dumps(execution.output().copy()))
    manifest = {}
    _enrich_with_preprocessing(manifest, moved)
    recorded = read_pack_preprocessing_binding(manifest)
    assert recorded is not None and recorded.steps[0].producer.required == (pack().reference,)
    assert all(set(step) == {"op_id", "parameters"} for step in manifest["preprocessing_chain"])
    with use_admitted_pack_replay((pack().reference,)):
        replayed = _prepare_artifact_input(original.X, None, manifest, scope="all", source_dataset=original)[0]
    np.testing.assert_allclose(replayed, moved.X)
    retained_registry._pack_manifests = (pack(build_sha256="b" * 64),)
    assert read_pack_preprocessing_binding(manifest) == recorded  # Inert reading remains available.
    with use_admitted_pack_replay((pack().reference,)), pytest.raises(PackBindingAdmissionError):
        _prepare_artifact_input(original.X, None, manifest, scope="all", source_dataset=original)
    changed = deepcopy(manifest)
    changed["preprocessing_chain"][0]["parameters"]["method"] = "scale"
    with pytest.raises(ValueError, match="preprocessing chain"):
        read_pack_preprocessing_binding(changed)


def test_stale_sdk_binding_is_refused_before_parameter_callbacks(retained_registry, monkeypatch):
    spec = workflow_spec(nodes=[{"node_id": "p", "node_type": "pro.reference.record"}], edges=[])
    reached = []

    def forbidden_constructor(*args, **kwargs):
        reached.append(True)
        raise AssertionError("stale artifact reached a constructor")

    monkeypatch.setattr(retained_registry, "create_node", forbidden_constructor)
    retained_registry._pack_manifests = (pack(build_sha256="b" * 64),)
    with pytest.raises(WorkflowSchemaError, match="pack binding"):
        WorkflowSpec.from_dict(spec.as_dict())
    stripped = spec.as_dict()
    stripped.pop("pack_binding")
    stripped["schema_version"] = "spectra-sherpa-workflow/1"
    with pytest.raises(WorkflowSchemaError, match="pack binding"):
        WorkflowSpec.from_dict(stripped)
    assert reached == []


async def test_sdk_uses_compact_utf8_at_binding_size_boundary(retained_registry):
    from spectra_sherpa.core.pack_requirements import MAX_BINDING_BYTES

    spec = workflow_spec(
        nodes=[{"node_id": "界" * 230 + str(index), "node_type": "pro.reference.record"} for index in range(850)],
        edges=[],
    )
    binding = spec.payload["pack_binding"]
    compact = json.dumps(binding, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(compact) <= MAX_BINDING_BYTES < len(json.dumps(binding).encode("utf-8"))
    assert WorkflowSpec.from_dict(spec.as_dict()) == spec
    # Binding parsing succeeds; this deliberately incomplete graph then reaches
    # the established SDK rule requiring explicit deployment-input sources.
    with use_pack_execution_authorizer(allow_reference_pack):
        with pytest.raises(ValueError, match="deploy.input"):
            await runtime.execute_workflow_async(spec, deployment_inputs={})
