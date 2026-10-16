"""Immutable pre-change model proofs, not fixtures relabeled with old hashes."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.historical_contracts import HistoricalReconstructionContext
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.modeling.saved_native_model import STATE_ARRAY, apply_saved_native_model
from spectra_sherpa.app.services.dag.validation_graph import (
    ValidationGraphError,
    assert_admitted_validation_graph,
    validation_graph_from_dict,
)
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.core.canonical_artifact import CanonicalArtifactStoreError, ReadOnlyCanonicalArtifactReader
from spectra_sherpa.core.contract_compatibility import (
    predecessor_catalog,
    saved_state_compatibilities,
    saved_state_predecessor_is_compatible,
)
from spectra_sherpa.core.execution_runtime import ExecutionRuntime
from spectra_sherpa.core.node_identity import node_contract_digest_is_compatible
from spectra_sherpa.execution_contract_vocabulary import NodeExecutionContract
from spectra_sherpa.sdk.canonical_capsule import CanonicalWorkflowCapsule
from spectra_sherpa.sdk.canonical_fitted_artifact import CanonicalFittedArtifact
from spectra_sherpa.sdk.fitted_state_custody import fitted_state_custody_capability

_FIXTURE = Path(__file__).parent / "fixtures/batch_predecessor_models.json"
_FIXTURE_SHA256 = "ad629f833b50177335b35d5681196f515e85558dc7e26057155955cee6ba2f58"
_OPERATIONS = ("model.fitted_pls", "model.fitted_pcr", "model.fitted_svr", "model.fitted_linear_regression")


@pytest.fixture
def historical():
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src/spectra_sherpa/app/types")
    raw = _FIXTURE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == _FIXTURE_SHA256
    return json.loads(raw)


def _dataset(fixture):
    return SherpaDataset(
        X=np.asarray(fixture["X"]),
        target=np.asarray(fixture["y"]),
        feature_axis=SpectralAxis(values=np.asarray(fixture["axis"]), units="cm-1"),
    )


@pytest.mark.parametrize("entry", saved_state_compatibilities(), ids=lambda e: e.operation_id)
def test_exact_directional_application_compatibility(entry):
    assert node_contract_digest_is_compatible(entry.operation_id, entry.predecessor_digest, entry.consumer_digest)
    assert saved_state_predecessor_is_compatible(
        entry.predecessor_digest, entry.consumer_digest, serializer=entry.serializer
    )
    assert not saved_state_predecessor_is_compatible(
        entry.consumer_digest, entry.predecessor_digest, operation_id=entry.operation_id
    )
    for predecessor, consumer, operation, serializer in (
        ("f" * 64, entry.consumer_digest, entry.operation_id, entry.serializer),
        (entry.predecessor_digest, "f" * 64, entry.operation_id, entry.serializer),
        (entry.predecessor_digest, entry.consumer_digest, "model.other", entry.serializer),
        (entry.predecessor_digest, entry.consumer_digest, entry.operation_id, "wrong/1"),
    ):
        assert not saved_state_predecessor_is_compatible(
            predecessor, consumer, operation_id=operation, serializer=serializer
        )


def test_only_reviewed_source_component_changed_and_all_current_identities_remain_truthful():
    catalog = predecessor_catalog()
    context = HistoricalReconstructionContext()
    component_phase_digests = {
        "classification.plsda": "a42f6b7a15955e08e7ec4c63fd335b17634454e21ff34b02f07a2077bea67cdb",
        "model.load_apply": "afdc60000a14991380335ab9e97c9440df38649caf47cc8e27457cb5f4d7c6c7",
        "model.apply_fitted_linear_regression": "7867e5992747564b3fe46215d0f7d2d199b3a5c2af40531b38d480d82465530b",
        "model.apply_fitted_pcr": "14d71c0447ba121bdd0b53911bb4f804d8b39ec1c0cdeb0a28228b8022aec5a8",
        "model.apply_fitted_pls": "6e4dad65e323401e8fa1e0dee0714892e3f2a9316489113db478e75cee42d9de",
        "model.apply_fitted_svr": "ad5a2b2901255e5ac252da8081fa9b727ce6aceefd5513d25285beec7824545c",
        "model.fitted_linear_regression": "63501135129058b92cd8b6d0db33d5d61d3407c0be4f25a53f984d4a0101e27a",
        "model.fitted_pcr": "7f6040c174cae2889250e6a4bc22620af172207109a1d6ff0fe66ad35937f9de",
        "model.fitted_pls": "3939dc715653c735c11d3993942bd8e8baf5343fd42e21341d5cde130dafdde3",
        "model.fitted_svr": "6015b47482335d0931239f6a52fea6825979c43c055e319c69deb3129b344c67",
    }
    reviewed_changes = {
        "model.apply_fitted_linear_regression": [
            "spectra_sherpa.app.lib.fitted_state",
            "spectra_sherpa.app.services.dag.nodes.modeling._artifact_builder",
            "spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node",
            "spectra_sherpa.app.services.dag.nodes.modeling.regression_nodes",
            "spectra_sherpa.app.services.dag.nodes.modeling.saved_native_model",
        ],
        "model.apply_fitted_pcr": [
            "spectra_sherpa.app.lib.fitted_state",
            "spectra_sherpa.app.services.dag.nodes.modeling._artifact_builder",
            "spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node",
            "spectra_sherpa.app.services.dag.nodes.modeling.regression_nodes",
            "spectra_sherpa.app.services.dag.nodes.modeling.saved_native_model",
        ],
        "model.apply_fitted_svr": [
            "spectra_sherpa.app.lib.fitted_state",
            "spectra_sherpa.app.services.dag.nodes.modeling._artifact_builder",
            "spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node",
            "spectra_sherpa.app.services.dag.nodes.modeling.regression_nodes",
            "spectra_sherpa.app.services.dag.nodes.modeling.saved_native_model",
        ],
        "model.dbscan": ["spectra_sherpa.app.services.dag.nodes.modeling.saved_native_model"],
        "model.fitted_linear_regression": [
            "spectra_sherpa.app.lib.fitted_state",
            "spectra_sherpa.app.services.dag.nodes.modeling._artifact_builder",
            "spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node",
            "spectra_sherpa.app.services.dag.nodes.modeling.regression_nodes",
            "spectra_sherpa.app.services.dag.nodes.modeling.saved_native_model",
        ],
        "model.fitted_pcr": [
            "spectra_sherpa.app.lib.fitted_state",
            "spectra_sherpa.app.services.dag.nodes.modeling._artifact_builder",
            "spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node",
            "spectra_sherpa.app.services.dag.nodes.modeling.regression_nodes",
            "spectra_sherpa.app.services.dag.nodes.modeling.saved_native_model",
        ],
        "model.fitted_pls": [
            "distribution.scipy",
            "spectra_sherpa.app.lib.numerical_scaling",
            "spectra_sherpa.app.lib.pca_numerics",
            "spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node",
            "spectra_sherpa.app.services.dag.nodes.modeling.pls_applicability",
            "spectra_sherpa.app.services.dag.nodes.modeling.pls_core",
            "spectra_sherpa.app.services.dag.nodes.modeling.saved_native_model",
            "spectra_sherpa.app.services.dag.nodes.selection._vip",
        ],
        "model.fitted_svr": [
            "spectra_sherpa.app.lib.fitted_state",
            "spectra_sherpa.app.services.dag.nodes.modeling._artifact_builder",
            "spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node",
            "spectra_sherpa.app.services.dag.nodes.modeling.regression_nodes",
            "spectra_sherpa.app.services.dag.nodes.modeling.saved_native_model",
        ],
        "model.hca": ["spectra_sherpa.app.services.dag.nodes.modeling.saved_native_model"],
        "model.kmeans": ["spectra_sherpa.app.services.dag.nodes.modeling.saved_native_model"],
        "model.load_apply": [
            "spectra_sherpa.app.lib.fitted_state",
            "spectra_sherpa.app.lib.pca",
            "spectra_sherpa.app.services.dag.nodes.classification.plsda_state",
            "spectra_sherpa.app.services.dag.nodes.modeling.load_apply_node",
            "spectra_sherpa.app.services.dag.nodes.modeling.saved_native_model",
            "spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node",
            "spectra_sherpa.app.services.dag.nodes.selection.variable_select_node",
            "spectra_sherpa.app.services.legacy_model_application",
        ],
        "model.parafac": [
            "spectra_sherpa.app.services.dag.io_contracts",
            "spectra_sherpa.app.services.dag.nodes.modeling.saved_native_model",
        ],
    }
    for operation, archived in catalog["contracts"].items():
        current = node_registry.get_metadata(operation).resolved_execution_contract()
        assert current.digest == component_phase_digests.get(operation, catalog["current_contracts"][operation])
        if operation in component_phase_digests:
            # Exact reviewed consumers admit read-only historical inspection,
            # never graph execution or a live predecessor implementation.
            historical = context.contract(operation, archived["digest"])
        else:
            historical = context.contract(operation, archived["digest"])
        old = {c["component_id"]: c["digest"] for c in historical.payload["implementation_components"]}
        new = {c["component_id"]: c["digest"] for c in current.payload["implementation_components"]}
        assert old.keys() <= new.keys()
        assert sorted(k for k in new if old.get(k) != new[k]) == reviewed_changes[operation]
    assert context.profile().digest == catalog["profile"]["profile_digest"]
    assert not {e.operation_id for e in saved_state_compatibilities()} & {
        "model.hca",
        "model.dbscan",
        "model.load_apply",
    }


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_previous_custody_is_unchanged_and_current_custody_is_explicit(operation):
    entry = next(e for e in saved_state_compatibilities() if e.operation_id == operation)
    old = fitted_state_custody_capability(entry.serializer, entry.predecessor_digest)
    new = fitted_state_custody_capability(entry.serializer, entry.consumer_digest)
    assert new.custody_class == old.custody_class
    assert (new.custody_class == "retains_training_rows") == (operation == "model.fitted_svr")


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_real_predecessor_native_model_predicts_without_refitting(historical, operation, monkeypatch):
    case = historical["cases"][operation]
    original = deepcopy(case)
    producer = type(node_registry.create_node(operation, "refit-forbidden", {}))
    monkeypatch.setattr(producer, "fit_fitted_state", lambda *a, **k: pytest.fail("application attempted refit"))
    dataset = _dataset(historical)
    arrays = {STATE_ARRAY: np.frombuffer(case["native_state_utf8"].encode(), dtype=np.uint8)}
    result = apply_saved_native_model(case["manifest"], arrays, dataset, dataset.X)
    np.testing.assert_allclose(result["predictions"].ravel(), np.asarray(case["predictions"]).ravel(), rtol=1e-12)
    assert case == original


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", _OPERATIONS)
async def test_real_predecessor_canonical_artifact_executes_through_reader(
    historical, operation, tmp_path, monkeypatch
):
    case = historical["cases"][operation]
    manifest = json.dumps(case["canonical_artifact"], sort_keys=True, separators=(",", ":")).encode()
    artifact = CanonicalFittedArtifact.from_serialized(manifest, {k: v.encode() for k, v in case["state_utf8"].items()})
    root = tmp_path / "artifacts"
    root.mkdir(mode=0o700)
    path = artifact.write_new(root / artifact.artifact_digest)
    before = {p.relative_to(path): p.read_bytes() for p in path.rglob("*") if p.is_file()}
    reader = ReadOnlyCanonicalArtifactReader(
        tmp_path, artifact_root=root, allowed_artifact_digests=(artifact.artifact_digest,)
    )
    member = artifact.payload["state_members"][0]
    binding = {
        "artifact_digest": artifact.artifact_digest,
        "state_node_id": member["node_id"],
        "state_digest": member["state_digest"],
        "state_content_digest": member["state_content_digest"],
        "serializer": member["serializer"],
        "source_contract_digest": member["contract_digest"],
    }
    producer = type(node_registry.create_node(operation, "refit-forbidden", {}))
    monkeypatch.setattr(producer, "fit_fitted_state", lambda *a, **k: pytest.fail("application attempted refit"))
    node = node_registry.create_node(operation.replace("model.fitted_", "model.apply_fitted_"), "apply", binding)
    node.bind_execution_runtime(ExecutionRuntime(canonical_artifact_reader=reader))
    result = await node.execute(_dataset(historical))
    np.testing.assert_allclose(result.outputs["default"].ravel(), np.asarray(case["predictions"]).ravel(), rtol=1e-12)
    assert {p.relative_to(path): p.read_bytes() for p in path.rglob("*") if p.is_file()} == before
    current = node_registry.get_metadata(operation).resolved_execution_contract()
    for field in ("source_contract_digest", "state_content_digest", "serializer"):
        damaged = {**binding, field: "f" * 64}
        with pytest.raises(CanonicalArtifactStoreError):
            reader.load_bound_state(
                damaged, expected_source_contract_digest=current.digest, expected_serializer=binding["serializer"]
            )


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_historical_graph_preserves_identity_but_cannot_execute(historical, operation):
    wire = historical["cases"][operation]["graph"]
    restored = HistoricalReconstructionContext().graph(wire)
    assert restored.as_dict() == wire
    with pytest.raises(ValidationGraphError, match="historical or noncanonical"):
        assert_admitted_validation_graph(restored, require_live_runtime=False)
    with pytest.raises(ValidationGraphError):
        validation_graph_from_dict(wire, require_live_runtime=False)
    altered = deepcopy(wire)
    altered["nodes"][0]["contract_digest"] = "f" * 64
    with pytest.raises(ValidationGraphError):
        HistoricalReconstructionContext().graph(altered)
    if operation == "model.fitted_pls":
        altered = deepcopy(wire)
        model = next(node for node in altered["nodes"] if node["operation_id"] == operation)
        model["parameters"]["component_selection_rule"] = "manual_parameter"
        altered["graph_digest"] = hashlib.sha256(
            json.dumps(
                {key: value for key, value in altered.items() if key != "graph_digest"},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode()
        ).hexdigest()
        with pytest.raises(ValidationGraphError, match="post-profile controls"):
            HistoricalReconstructionContext().graph(altered)


def test_real_predecessor_capsule_reads_without_rewriting_any_identity(historical):
    assert CanonicalWorkflowCapsule.from_dict(historical["capsule"]).as_dict() == historical["capsule"]


def test_historical_execution_evidence_requires_explicit_context_and_rejects_changed_witness(historical):
    from spectra_sherpa.sdk.canonical_execution_evidence import (
        CanonicalExecutionEvidence,
        CanonicalExecutionEvidenceError,
    )

    wire = historical["capsule"]["execution_evidence"]
    with pytest.raises(CanonicalExecutionEvidenceError):
        CanonicalExecutionEvidence.from_dict(wire)
    assert (
        CanonicalExecutionEvidence.from_dict(wire, historical_context=HistoricalReconstructionContext()).as_dict()
        == wire
    )
    forged = deepcopy(wire)
    node = forged["node_execution_traces"][0]["nodes"][0]
    node["contract"]["implementation_components"][0]["digest"] = "f" * 64
    with pytest.raises(CanonicalExecutionEvidenceError):
        CanonicalExecutionEvidence.from_dict(forged, historical_context=HistoricalReconstructionContext())

    # A self-consistent new source witness is still not trusted historical
    # authority. Rehash every affected trace and the enclosing evidence so the
    # refusal must come from the catalog, not an ordinary integrity mismatch.
    from spectra_sherpa.app.services.dag.stable_execution_contract import implementation_digest_for_components

    operation = node["operation_id"]
    altered_contract = node["contract"]
    altered_contract["implementation_digest"] = implementation_digest_for_components(
        altered_contract["implementation_components"]
    )
    altered_digest = NodeExecutionContract.from_dict(altered_contract).digest
    for fold in forged["node_execution_traces"]:
        for trace in fold["nodes"]:
            if trace["operation_id"] == operation:
                trace["contract"] = deepcopy(altered_contract)
                trace["contract_digest"] = altered_digest
    forged["content_digest"] = hashlib.sha256(
        json.dumps(
            {k: v for k, v in forged.items() if k != "content_digest"},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    with pytest.raises(CanonicalExecutionEvidenceError, match="unknown historical node execution trace"):
        CanonicalExecutionEvidence.from_dict(forged, historical_context=HistoricalReconstructionContext())


@pytest.mark.parametrize("operation", _OPERATIONS)
def test_native_application_refuses_unknown_predecessor_or_serializer(historical, operation):
    case = historical["cases"][operation]
    dataset = _dataset(historical)
    for field, value in (("serializer", "wrong/1"), ("source_contract_digest", "f" * 64)):
        payload = json.loads(case["native_state_utf8"])
        payload[field] = value
        arrays = {STATE_ARRAY: np.frombuffer(json.dumps(payload).encode(), dtype=np.uint8)}
        with pytest.raises(ValueError, match="contract is incompatible"):
            apply_saved_native_model(case["manifest"], arrays, dataset, dataset.X)
