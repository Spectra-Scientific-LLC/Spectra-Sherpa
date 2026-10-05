"""OSS-only tests for the closed M4 canonical execution evidence record."""

from __future__ import annotations

import asyncio
import builtins
import importlib
from copy import deepcopy
from pathlib import Path

import pytest

import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.preprocessing.baseline_nodes  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.regression_evaluator_node  # noqa: F401
import spectra_sherpa.sdk.canonical_execution_evidence as canonical_execution_evidence
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.fold_graph_executor import execute_candidate_validation
from spectra_sherpa.app.services.dag.managed_optimization_profile import managed_optimization_profile
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.sdk.validate import make_split_plan

MANAGED_OPTIMIZATION_PROFILE = managed_optimization_profile()


@pytest.fixture(autouse=True)
def _load_type_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _execution():
    import numpy as np

    X = np.arange(96, dtype=float).reshape(12, 8)
    target = X[:, 0] * 0.3 + X[:, 1] * 0.1
    split = make_split_plan(X.shape[0], n_splits=3)
    capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(X=X, target=target),
        custody_id="public-fixture",
        dataset_ref_digest="a" * 64,
        split_plan_digest=split.digest,
    )
    nodes = [
        WorkflowNode("scale", "preprocess.scale", {"method": "autoscale", "center": True}),
        WorkflowNode("model", "model.fitted_pls", {"n_components": 2, "scale": True}),
        WorkflowNode("score", "diagnostics.regression_evaluator", {}),
    ]
    graph = admit_validation_graph(
        nodes,
        [WorkflowEdge(left.node_id, right.node_id) for left, right in zip(nodes, nodes[1:])],
    )
    return asyncio.run(execute_candidate_validation(graph, capability, split))


def _runtime_attestation(execution):
    operation_ids = ("preprocess.scale", "model.fitted_pls", "diagnostics.regression_evaluator")
    versions = {
        str(requirement["distribution"]): str(requirement["version"])
        for operation_id in operation_ids
        for requirement in MANAGED_OPTIMIZATION_PROFILE.operation(operation_id).payload["runtime_requirements"]
    }
    return MANAGED_OPTIMIZATION_PROFILE.runtime_attestation(
        operation_ids,
        version_resolver=versions.__getitem__,
    ).as_dict()


def test_round_trip_recomputes_the_executor_validation_digest_without_server_import(monkeypatch) -> None:
    execution = _execution()

    evidence = canonical_execution_evidence.CanonicalExecutionEvidence.from_validation_execution(
        execution,
        runtime_attestation=_runtime_attestation(execution),
    )
    loaded = canonical_execution_evidence.CanonicalExecutionEvidence.from_bytes(evidence.canonical_bytes())

    assert loaded.validation_execution_digest == execution.digest
    assert loaded.content_digest == evidence.content_digest

    original_import = builtins.__import__

    def reject_server_import(name, *args, **kwargs):
        if name == "spectrasherpa_server" or name.startswith("spectrasherpa_server."):
            raise AssertionError("OSS canonical evidence must not import the managed server")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_server_import)
    importlib.reload(canonical_execution_evidence)


def test_evidence_cannot_be_issued_from_a_duck_typed_forgery() -> None:
    execution = _execution()

    class ForgedExecution:
        digest = execution.digest

        @staticmethod
        def as_dict():
            return execution.as_dict()

    with pytest.raises(canonical_execution_evidence.CanonicalExecutionEvidenceError, match="not serializable"):
        canonical_execution_evidence.CanonicalExecutionEvidence.from_validation_execution(
            ForgedExecution(), runtime_attestation=_runtime_attestation(execution)
        )


def test_v2_trace_is_bound_to_actual_fold_lifecycle_without_sample_values() -> None:
    execution = _execution()
    evidence = canonical_execution_evidence.CanonicalExecutionEvidence.from_validation_execution(
        execution,
        runtime_attestation=_runtime_attestation(execution),
    )
    trace_fold = evidence.payload["node_execution_traces"][0]
    nodes = trace_fold["nodes"]

    assert evidence.payload["schema_version"] == canonical_execution_evidence.CANONICAL_EXECUTION_EVIDENCE_VERSION
    assert trace_fold["partition_digest"] == execution.folds[0].partition_digest
    assert [node["node_id"] for node in nodes] == list(execution.folds[0].node_ids)
    assert nodes[0]["role_envelopes"] == [
        {"role": "train", "input_shape": [8, 8], "output_shape": [8, 8]},
        {"role": "test", "input_shape": [4, 8], "output_shape": [4, 8]},
    ]
    assert nodes[0]["fitted_state_digest"] is not None
    assert nodes[-1]["role_envelopes"] == [{"role": "test", "input_shape": [4, 1], "output_shape": []}]
    encoded = evidence.canonical_bytes().decode("utf-8")
    for forbidden in ('"target":', '"predictions":', "fitted_state_bytes", "file://", "/Users/"):
        assert forbidden not in encoded


def test_retired_execution_evidence_is_rejected_without_translation() -> None:
    execution = _execution()
    legacy_payload = {
        "schema_version": "spectra-canonical-execution-evidence/2",
        "validation_execution": execution.as_dict(),
        "validation_execution_digest": execution.digest,
    }
    with pytest.raises(
        canonical_execution_evidence.CanonicalExecutionEvidenceError,
        match="schema is unsupported",
    ):
        canonical_execution_evidence.CanonicalExecutionEvidence.from_dict(
            {**legacy_payload, "content_digest": canonical_execution_evidence._digest(legacy_payload)}
        )


def test_rehashed_nested_parameter_payload_is_rejected_by_the_oss_verifier() -> None:
    execution = _execution()
    evidence = canonical_execution_evidence.CanonicalExecutionEvidence.from_validation_execution(
        execution,
        runtime_attestation=_runtime_attestation(execution),
    )
    payload = evidence.as_dict()
    trace = payload["node_execution_traces"][0]["nodes"][0]
    trace["parameters"] = {"raw_spectrum": [0.0, 1.0, 2.0]}
    trace["parameter_digest"] = canonical_execution_evidence._parameter_digest(trace["parameters"])
    payload["content_digest"] = canonical_execution_evidence._digest(
        {key: value for key, value in payload.items() if key != "content_digest"}
    )

    with pytest.raises(canonical_execution_evidence.CanonicalExecutionEvidenceError, match="parameters"):
        canonical_execution_evidence.CanonicalExecutionEvidence.from_dict(payload)


def test_retired_rubberband_range_parameter_is_rejected() -> None:
    """Current evidence cannot reintroduce the retired no-op SCP parameter."""

    execution = _execution()
    evidence = canonical_execution_evidence.CanonicalExecutionEvidence.from_validation_execution(
        execution,
        runtime_attestation=_runtime_attestation(execution),
    )
    payload = evidence.as_dict()
    trace = payload["node_execution_traces"][0]["nodes"][0]
    contract = node_registry.get_metadata("baseline.rubberband").resolved_execution_contract()
    trace["operation_id"] = "baseline.rubberband"
    trace["contract"] = contract.as_dict()
    trace["contract_digest"] = contract.digest
    trace["parameters"] = {"ranges": "[0.12, 0.34, 0.56]"}
    trace["parameter_digest"] = canonical_execution_evidence._parameter_digest(trace["parameters"])
    payload["content_digest"] = canonical_execution_evidence._digest(
        {key: value for key, value in payload.items() if key != "content_digest"}
    )

    with pytest.raises(canonical_execution_evidence.CanonicalExecutionEvidenceError, match="ranges"):
        canonical_execution_evidence.CanonicalExecutionEvidence.from_dict(payload)


def test_closed_select_text_cannot_smuggle_serialized_samples() -> None:
    """The standalone parser uses the same closed select grammar as admission."""

    execution = _execution()
    evidence = canonical_execution_evidence.CanonicalExecutionEvidence.from_validation_execution(
        execution,
        runtime_attestation=_runtime_attestation(execution),
    )
    payload = evidence.as_dict()
    trace = payload["node_execution_traces"][0]["nodes"][0]
    trace["parameters"]["method"] = "0.12,0.34,0.56,0.78"
    trace["parameter_digest"] = canonical_execution_evidence._parameter_digest(trace["parameters"])
    payload["content_digest"] = canonical_execution_evidence._digest(
        {key: value for key, value in payload.items() if key != "content_digest"}
    )

    with pytest.raises(canonical_execution_evidence.CanonicalExecutionEvidenceError, match="method"):
        canonical_execution_evidence.CanonicalExecutionEvidence.from_dict(payload)


def test_runtime_attestation_must_name_exactly_the_executed_operations() -> None:
    execution = _execution()
    evidence = canonical_execution_evidence.CanonicalExecutionEvidence.from_validation_execution(
        execution,
        runtime_attestation=_runtime_attestation(execution),
    )
    payload = evidence.as_dict()
    runtime = payload["runtime_attestation"]
    runtime["operation_ids"] = runtime["operation_ids"][:-1]
    requirements = tuple(
        canonical_execution_evidence.ManagedOptimizationRuntimeRequirement(item["distribution"], item["version"])
        for item in runtime["distributions"]
    )
    runtime["digest"] = canonical_execution_evidence.ManagedOptimizationRuntimeAttestation(
        profile_id=runtime["profile_id"],
        profile_version=runtime["profile_version"],
        profile_digest=runtime["profile_digest"],
        operation_ids=tuple(runtime["operation_ids"]),
        distributions=requirements,
    ).digest
    payload["content_digest"] = canonical_execution_evidence._digest(
        {key: value for key, value in payload.items() if key != "content_digest"}
    )

    with pytest.raises(
        canonical_execution_evidence.CanonicalExecutionEvidenceError,
        match="operations differ from executed node traces",
    ):
        canonical_execution_evidence.CanonicalExecutionEvidence.from_dict(payload)


def test_runtime_attestation_cannot_substitute_a_self_consistent_unapproved_profile() -> None:
    execution = _execution()
    evidence = canonical_execution_evidence.CanonicalExecutionEvidence.from_validation_execution(
        execution,
        runtime_attestation=_runtime_attestation(execution),
    )
    payload = evidence.as_dict()
    runtime = payload["runtime_attestation"]
    runtime["profile_id"] = "invented_profile"
    requirements = tuple(
        canonical_execution_evidence.ManagedOptimizationRuntimeRequirement(item["distribution"], item["version"])
        for item in runtime["distributions"]
    )
    runtime["digest"] = canonical_execution_evidence.ManagedOptimizationRuntimeAttestation(
        profile_id=runtime["profile_id"],
        profile_version=runtime["profile_version"],
        profile_digest=runtime["profile_digest"],
        operation_ids=tuple(runtime["operation_ids"]),
        distributions=requirements,
    ).digest
    payload["content_digest"] = canonical_execution_evidence._digest(
        {key: value for key, value in payload.items() if key != "content_digest"}
    )

    with pytest.raises(
        canonical_execution_evidence.CanonicalExecutionEvidenceError,
        match="live managed optimization profile",
    ):
        canonical_execution_evidence.CanonicalExecutionEvidence.from_dict(payload)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["validation_execution"]["folds"][0].__setitem__("partition_digest", "0" * 64),
        lambda payload: payload["validation_execution"]["folds"][0]["metrics"].__setitem__("rmse", float("nan")),
        lambda payload: payload["validation_execution"].__setitem__("unexpected", "value"),
        lambda payload: payload["node_execution_traces"][0]["nodes"][0].__setitem__("parameter_digest", "0" * 64),
    ],
)
def test_mutation_is_detected_before_evidence_is_accepted(mutate) -> None:
    execution = _execution()
    evidence = canonical_execution_evidence.CanonicalExecutionEvidence.from_validation_execution(
        execution,
        runtime_attestation=_runtime_attestation(execution),
    )
    payload = evidence.as_dict()
    mutate(payload)

    with pytest.raises(canonical_execution_evidence.CanonicalExecutionEvidenceError):
        canonical_execution_evidence.CanonicalExecutionEvidence.from_dict(payload)


def _rehash(payload: dict) -> dict:
    validation = payload["validation_execution"]
    payload["validation_execution_digest"] = canonical_execution_evidence._validation_execution_digest(validation)
    payload["content_digest"] = canonical_execution_evidence._digest(
        {key: value for key, value in payload.items() if key != "content_digest"}
    )
    return payload


@pytest.mark.parametrize("field", ["rmse", "mae"])
def test_rehashed_negative_error_metric_is_still_rejected(field: str) -> None:
    execution = _execution()
    payload = canonical_execution_evidence.CanonicalExecutionEvidence.from_validation_execution(
        execution, runtime_attestation=_runtime_attestation(execution)
    ).as_dict()
    payload["validation_execution"]["metrics"][field] = -1.0

    with pytest.raises(canonical_execution_evidence.CanonicalExecutionEvidenceError, match="cannot be negative"):
        canonical_execution_evidence.CanonicalExecutionEvidence.from_dict(_rehash(payload))


def test_rehashed_impossible_fold_sample_count_is_still_rejected() -> None:
    execution = _execution()
    payload = canonical_execution_evidence.CanonicalExecutionEvidence.from_validation_execution(
        execution, runtime_attestation=_runtime_attestation(execution)
    ).as_dict()
    payload["validation_execution"]["folds"][0]["metrics"]["n_samples"] += 1

    with pytest.raises(canonical_execution_evidence.CanonicalExecutionEvidenceError, match="sample counts"):
        canonical_execution_evidence.CanonicalExecutionEvidence.from_dict(_rehash(payload))


def test_rehashed_malformed_prediction_application_digest_is_rejected() -> None:
    execution = _execution()
    payload = canonical_execution_evidence.CanonicalExecutionEvidence.from_validation_execution(
        execution, runtime_attestation=_runtime_attestation(execution)
    ).as_dict()
    payload["validation_execution"]["folds"][0]["prediction_application_digest"] = "not-a-digest"

    with pytest.raises(
        canonical_execution_evidence.CanonicalExecutionEvidenceError,
        match="prediction_application_digest",
    ):
        canonical_execution_evidence.CanonicalExecutionEvidence.from_dict(_rehash(payload))


def test_rehashed_fold_graph_disagreement_is_still_rejected() -> None:
    execution = _execution()
    payload = deepcopy(
        canonical_execution_evidence.CanonicalExecutionEvidence.from_validation_execution(
            execution, runtime_attestation=_runtime_attestation(execution)
        ).as_dict()
    )
    payload["validation_execution"]["folds"][1]["node_ids"].reverse()

    with pytest.raises(canonical_execution_evidence.CanonicalExecutionEvidenceError, match="disagree"):
        canonical_execution_evidence.CanonicalExecutionEvidence.from_dict(_rehash(payload))


def test_rehashed_cross_fold_trace_identity_disagreement_is_still_rejected() -> None:
    execution = _execution()
    payload = canonical_execution_evidence.CanonicalExecutionEvidence.from_validation_execution(
        execution, runtime_attestation=_runtime_attestation(execution)
    ).as_dict()
    trace = payload["node_execution_traces"][1]["nodes"][0]
    trace["seed"] = 42
    payload["content_digest"] = canonical_execution_evidence._digest(
        {key: value for key, value in payload.items() if key != "content_digest"}
    )

    with pytest.raises(
        canonical_execution_evidence.CanonicalExecutionEvidenceError,
        match="traces disagree across validation folds",
    ):
        canonical_execution_evidence.CanonicalExecutionEvidence.from_dict(payload)
