"""OSS-only contract tests for the canonical workflow capsule."""

from __future__ import annotations

import asyncio
import builtins
import hashlib
import importlib
import json
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.regression_evaluator_node  # noqa: F401
import spectra_sherpa.sdk.canonical_capsule as canonical_capsule
import spectra_sherpa.sdk.workflow as workflow_sdk
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.fold_graph_executor import (
    execute_candidate_validation,
    execute_selected_candidate_full_refit,
)
from spectra_sherpa.app.services.dag.managed_optimization_profile import managed_optimization_profile
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.sdk.canonical_execution_evidence import CanonicalExecutionEvidence
from spectra_sherpa.sdk.canonical_full_refit_evidence import CanonicalFullRefitEvidence
from spectra_sherpa.sdk.validate import make_split_plan

MANAGED_OPTIMIZATION_PROFILE = managed_optimization_profile()
managed_optimization_profile_module = importlib.import_module(
    "spectra_sherpa.app.services.dag.managed_optimization_profile"
)


@pytest.fixture(autouse=True)
def _load_type_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _capsule(*, materialize_refit: bool = False):
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
    execution = asyncio.run(execute_candidate_validation(graph, capability, split))
    versions = {
        str(requirement["distribution"]): str(requirement["version"])
        for node in graph.nodes
        for requirement in MANAGED_OPTIMIZATION_PROFILE.operation(node.operation_id).payload["runtime_requirements"]
    }
    runtime = MANAGED_OPTIMIZATION_PROFILE.runtime_attestation(
        tuple(node.operation_id for node in graph.nodes), version_resolver=versions.__getitem__
    ).as_dict()
    evidence = CanonicalExecutionEvidence.from_validation_execution(execution, runtime_attestation=runtime)
    refit_evidence = None
    if materialize_refit:
        refit = asyncio.run(execute_selected_candidate_full_refit(graph, capability, execution))
        refit_evidence = CanonicalFullRefitEvidence.from_full_refit_execution(refit)
    unsigned = {
        "protocol": "spectra-canonical-runner/5",
        "execution_purpose": "candidate_validation",
        "winner_refit_authority_digest": None,
        "confirmation_authority": None,
        "request_id": "canonical-request-001",
        "campaign_id": "canonical-campaign-001",
        "candidate_id": "canonical-candidate-001",
        "profile": {
            "profile_id": MANAGED_OPTIMIZATION_PROFILE.profile_id,
            "profile_version": MANAGED_OPTIMIZATION_PROFILE.profile_version,
            "profile_digest": MANAGED_OPTIMIZATION_PROFILE.digest,
        },
        "graph": graph.as_dict(),
        "evaluation_kind": "public_reproducibility",
        "dataset_role": "public_reproducibility",
        "capability_digest": capability.envelope_digest,
        "dataset_content_digest": capability.content_digest,
        "dataset_ref_digest": "a" * 64,
        "dataset_shape": {"n_samples": 12, "n_features": 8, "grouped": False},
        "split_digest": split.digest,
        "validation": {
            "schema_version": "spectra-canonical-validation/3",
            "task_type": "regression",
            "selection": "group_kfold_when_groups_else_kfold",
            "outer_splits": 3,
            "shuffle": False,
            "metric_registry_version": "2",
            "primary_metric": "rmse",
        },
        "search": {
            "schema_version": "spectra-canonical-search-execution/2",
            "strategy": "finite_declared_parameter_grid",
            "search_space_digest": "9" * 64,
            "candidate_ordinal": 1,
            "candidate_count": 2,
            "candidate_id": "canonical-candidate-001",
            "candidate_graph_digest": graph.digest,
        },
        "resources": {
            "schema_version": "spectra-canonical-resources/1",
            "timeout_seconds": 30,
            "cpu_seconds": 30,
            "memory_bytes": 1024**3,
            "temp_bytes": 512 * 1024**2,
            "max_file_bytes": 128 * 1024**2,
            "stdout_bytes": 65536,
            "stderr_bytes": 16384,
        },
        "runtime_attestation": runtime,
    }
    request = {**unsigned, "request_digest": _digest(unsigned)}
    return canonical_capsule.CanonicalWorkflowCapsule.from_admitted_request(
        request,
        evidence,
        full_refit_evidence=refit_evidence,
    )


def _digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def _redigest_capsule(payload: dict) -> None:
    payload["capsule_digest"] = _digest({key: value for key, value in payload.items() if key != "capsule_digest"})


def _redigest_request(payload: dict) -> None:
    request = payload["admitted_request"]
    request["request_digest"] = _digest({key: value for key, value in request.items() if key != "request_digest"})
    _redigest_capsule(payload)


def test_capsule_round_trips_and_re_admits_the_graph_without_server_import(monkeypatch) -> None:
    capsule = _capsule()
    loaded = canonical_capsule.CanonicalWorkflowCapsule.from_bytes(capsule.canonical_bytes())

    assert loaded.capsule_digest == capsule.capsule_digest
    assert loaded.graph.digest == capsule.graph.digest
    assert loaded.execution_evidence.content_digest == capsule.execution_evidence.content_digest
    assert loaded.full_refit_evidence is None

    original_import = builtins.__import__

    def reject_server_import(name, *args, **kwargs):
        if name == "spectrasherpa_server" or name.startswith("spectrasherpa_server."):
            raise AssertionError("canonical workflow capsules must remain independently OSS-verifiable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_server_import)
    importlib.reload(canonical_capsule)


@pytest.mark.parametrize("primary_metric", ["balanced_accuracy", "mean_class_acceptance_sensitivity"])
def test_capsule_admits_current_classification_validation_authority(primary_metric: str) -> None:
    canonical_capsule._validate_validation_plan(  # noqa: SLF001 - direct closed-contract qualification.
        {
            "schema_version": "spectra-canonical-validation/4",
            "task_type": "classification",
            "selection": "stratified_group_kfold_when_groups_else_stratified_kfold",
            "outer_splits": 3,
            "shuffle": False,
            "metric_registry_version": "2",
            "primary_metric": primary_metric,
        }
    )


def test_capsule_rejects_current_classification_plan_with_legacy_metric_registry() -> None:
    with pytest.raises(canonical_capsule.CanonicalWorkflowCapsuleError, match="validation plan is unsupported"):
        canonical_capsule._validate_validation_plan(  # noqa: SLF001 - direct closed-contract qualification.
            {
                "schema_version": "spectra-canonical-validation/4",
                "task_type": "classification",
                "selection": "stratified_group_kfold_when_groups_else_stratified_kfold",
                "outer_splits": 3,
                "shuffle": False,
                "metric_registry_version": "1",
                "primary_metric": "balanced_accuracy",
            }
        )


def test_capsule_rejects_the_prototype_runner_request_without_translation() -> None:
    payload = deepcopy(_capsule().as_dict())
    request = payload["admitted_request"]
    request["protocol"] = "spectra-canonical-runner/3"
    request.pop("execution_purpose")
    _redigest_request(payload)

    with pytest.raises(canonical_capsule.CanonicalWorkflowCapsuleError, match="fields are closed|unsupported"):
        canonical_capsule.CanonicalWorkflowCapsule.from_dict(payload)


def test_capsule_rejects_a_refit_request_as_the_validation_authority() -> None:
    payload = deepcopy(_capsule().as_dict())
    payload["admitted_request"]["execution_purpose"] = "winner_refit"
    _redigest_request(payload)

    with pytest.raises(canonical_capsule.CanonicalWorkflowCapsuleError, match="candidate-validation"):
        canonical_capsule.CanonicalWorkflowCapsule.from_dict(payload)


def test_sealed_capsule_is_readable_offline_but_strict_live_readmission_rejects_runtime_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The capsule consumer, not just its graph helper, has the offline boundary."""

    capsule = _capsule()
    expected = {
        str(requirement["distribution"]): str(requirement["version"])
        for contract in MANAGED_OPTIMIZATION_PROFILE.contracts
        for requirement in contract.payload["runtime_requirements"]
    }

    def drifted_runtime(distribution: str) -> str:
        return "9.9.9" if distribution == "scipy" else expected[distribution]

    monkeypatch.setattr(managed_optimization_profile_module.importlib.metadata, "version", drifted_runtime)
    loaded = canonical_capsule.CanonicalWorkflowCapsule.from_dict(capsule.as_dict())

    assert loaded.capsule_digest == capsule.capsule_digest
    with pytest.raises(canonical_capsule.CanonicalWorkflowCapsuleError, match="graph failed local re-admission"):
        canonical_capsule._validate_admitted_request(  # noqa: SLF001 - tests the execution-only boundary directly.
            loaded.payload["admitted_request"],
            require_live_runtime=True,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["admitted_request"]["graph"]["nodes"][0]["parameters"].update(center=False), "graph"),
        (lambda value: value["admitted_request"]["dataset_shape"].update(n_samples=13), "evidence differs"),
        (
            lambda value: value["admitted_request"]["runtime_attestation"].update(
                profile_version="forged-profile-version"
            ),
            "runtime",
        ),
        (
            lambda value: value["execution_evidence"]["node_execution_traces"][0]["nodes"][0].update(
                node_id="invented"
            ),
            "execution evidence is invalid",
        ),
    ],
)
def test_self_rehashed_scientific_mutations_are_rejected(mutation, message) -> None:
    payload = deepcopy(_capsule().as_dict())
    mutation(payload)
    if "admitted_request" in payload:
        _redigest_request(payload)
    _redigest_capsule(payload)

    with pytest.raises(canonical_capsule.CanonicalWorkflowCapsuleError, match=message):
        canonical_capsule.CanonicalWorkflowCapsule.from_dict(payload)


def test_capsule_is_closed_sample_free_and_distinct_from_legacy_capsules() -> None:
    capsule = _capsule()
    encoded = capsule.canonical_bytes().decode()

    assert capsule.payload["schema_version"] == "spectra-canonical-workflow-capsule/6"
    assert "spectra-sherpa-workflow-capsule/1" not in encoded
    assert "spectra-sherpa-workflow-capsule/2" not in encoded
    for forbidden in ('"target":', '"predictions":', "raw_spectra", "fitted_state_bytes", "/Users/", "dataset_path"):
        assert forbidden not in encoded

    extra = capsule.as_dict()
    extra["python_source"] = "raise SystemExit"
    _redigest_capsule(extra)
    with pytest.raises(canonical_capsule.CanonicalWorkflowCapsuleError, match="fields are closed"):
        canonical_capsule.CanonicalWorkflowCapsule.from_dict(extra)


def test_materialized_refit_is_bound_to_this_selected_validation_and_graph() -> None:
    capsule = _capsule(materialize_refit=True)
    loaded = canonical_capsule.CanonicalWorkflowCapsule.from_bytes(capsule.canonical_bytes())

    assert loaded.full_refit_evidence is not None
    refit = loaded.full_refit_evidence.payload["full_refit_execution"]
    assert refit["validation_execution_digest"] == loaded.execution_evidence.validation_execution_digest
    assert refit["node_ids"] == ["scale", "model"]
    assert [item["node_id"] for item in refit["fitted_state_references"]] == ["scale", "model"]


def test_transitional_v3_capsule_is_rejected_without_translation() -> None:
    payload = _capsule().as_dict()
    payload["schema_version"] = "spectra-canonical-workflow-capsule/3"
    del payload["application_refit"]
    _redigest_capsule(payload)

    with pytest.raises(canonical_capsule.CanonicalWorkflowCapsuleError, match="schema is unsupported"):
        canonical_capsule.CanonicalWorkflowCapsule.from_dict(payload)


def test_retired_one_candidate_search_plan_is_rejected_without_translation() -> None:
    payload = _capsule().as_dict()
    request = payload["admitted_request"]
    request["search"] = {
        "schema_version": "spectra-canonical-search-plan/1",
        "strategy": "one_preadmitted_candidate",
        "candidate_ordinal": 1,
        "max_candidates": 1,
    }
    request["request_digest"] = _digest({key: value for key, value in request.items() if key != "request_digest"})
    _redigest_capsule(payload)

    with pytest.raises(
        canonical_capsule.CanonicalWorkflowCapsuleError,
        match="canonical search execution plan",
    ):
        canonical_capsule.CanonicalWorkflowCapsule.from_dict(payload)


def test_current_capsule_loader_accepts_mapping_bytes_and_path_and_rejects_prototypes(tmp_path: Path) -> None:
    capsule = _capsule()
    path = tmp_path / "canonical-capsule.json"
    path.write_bytes(capsule.canonical_bytes())

    from_mapping = canonical_capsule.load_canonical_capsule(capsule.as_dict())
    from_bytes = canonical_capsule.load_canonical_capsule(capsule.canonical_bytes())
    from_path = canonical_capsule.load_canonical_capsule(path)
    from_public_loader = workflow_sdk.load(path)

    assert from_mapping.as_dict() == from_bytes.as_dict() == from_path.as_dict() == from_public_loader.as_dict()
    with pytest.raises(canonical_capsule.CanonicalWorkflowCapsuleError, match="does not accept URLs"):
        canonical_capsule.load_canonical_capsule("https://example.invalid/capsule.json")
    with pytest.raises(canonical_capsule.CanonicalWorkflowCapsuleError, match="schema is unsupported"):
        canonical_capsule.load_canonical_capsule(
            {
                "schema_version": "spectra-sherpa-workflow-capsule/2",
                "capsule_digest": "0" * 64,
            }
        )


def test_noncanonical_duplicate_and_oversized_bytes_are_rejected() -> None:
    capsule = _capsule()
    with pytest.raises(canonical_capsule.CanonicalWorkflowCapsuleError, match="canonical JSON"):
        canonical_capsule.CanonicalWorkflowCapsule.from_bytes(json.dumps(capsule.as_dict(), indent=2).encode())
    with pytest.raises(canonical_capsule.CanonicalWorkflowCapsuleError, match="repeats field"):
        canonical_capsule.CanonicalWorkflowCapsule.from_bytes(
            b'{"capsule_digest":"' + b"0" * 64 + b'","capsule_digest":"' + b"0" * 64 + b'"}'
        )
    with pytest.raises(canonical_capsule.CanonicalWorkflowCapsuleError, match="size"):
        canonical_capsule.CanonicalWorkflowCapsule.from_bytes(
            b"x" * (canonical_capsule.MAX_CANONICAL_WORKFLOW_CAPSULE_BYTES + 1)
        )
