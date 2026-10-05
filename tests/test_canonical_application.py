"""OSS-only tests for the capsule/artifact canonical application-plan join."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.regression_evaluator_node  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.fold_graph_executor import (
    execute_candidate_validation,
    execute_selected_candidate_full_refit,
)
from spectra_sherpa.app.services.dag.managed_optimization_profile import managed_optimization_profile
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.sdk.canonical_application import (
    CANONICAL_APPLICATION_PLAN_VERSION,
    CanonicalApplicationPlan,
    CanonicalApplicationPlanError,
)
from spectra_sherpa.sdk.canonical_application_execution import application_workflow
from spectra_sherpa.sdk.canonical_capsule import CanonicalWorkflowCapsule
from spectra_sherpa.sdk.canonical_execution_evidence import CanonicalExecutionEvidence
from spectra_sherpa.sdk.canonical_fitted_artifact import CanonicalFittedArtifact
from spectra_sherpa.sdk.canonical_full_refit_evidence import CanonicalFullRefitEvidence
from spectra_sherpa.sdk.validate import make_split_plan

MANAGED_OPTIMIZATION_PROFILE = managed_optimization_profile()


@pytest.fixture(autouse=True)
def _load_type_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


def _digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
    ).hexdigest()


def _capsule_and_artifact(
    *,
    offset: float = 0.0,
    include_stateless_smooth: bool = False,
    fitted_preprocess: tuple[str, dict[str, object]] | None = None,
) -> tuple[CanonicalWorkflowCapsule, CanonicalFittedArtifact]:
    rng = np.random.default_rng(20260813)
    axis = np.linspace(900.0, 1900.0, 16)
    target = np.linspace(-1.0, 1.0, 12)
    nuisance = rng.normal(size=(12, 3)) @ rng.normal(scale=0.08, size=(3, 16))
    X = (
        np.linspace(0.85, 1.15, 12)[:, None] * (1.2 + target[:, None] * np.sin(axis / 175.0) + nuisance)
        + np.linspace(-0.05, 0.05, 12)[:, None]
        + offset
    )
    split = make_split_plan(X.shape[0], n_splits=3)
    capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(X=X, target=target, feature_axis=SpectralAxis(values=axis, units="cm-1")),
        custody_id="public-fixture",
        dataset_ref_digest="a" * 64,
        split_plan_digest=split.digest,
    )
    nodes = [
        *(
            [WorkflowNode("smooth", "preprocess.smooth", {"method": "gaussian", "sigma": 1.0})]
            if include_stateless_smooth
            else []
        ),
        *(
            [WorkflowNode("fitted-preprocess", fitted_preprocess[0], fitted_preprocess[1])]
            if fitted_preprocess is not None
            else []
        ),
        WorkflowNode("scale", "preprocess.scale", {"method": "autoscale", "center": True}),
        WorkflowNode("model", "model.fitted_pls", {"n_components": 2, "scale": True}),
        WorkflowNode("score", "diagnostics.regression_evaluator", {}),
    ]
    graph = admit_validation_graph(
        nodes, [WorkflowEdge(left.node_id, right.node_id) for left, right in zip(nodes, nodes[1:])]
    )
    validation = asyncio.run(execute_candidate_validation(graph, capability, split))
    refit = asyncio.run(execute_selected_candidate_full_refit(graph, capability, validation))
    versions = {
        str(requirement["distribution"]): str(requirement["version"])
        for node in graph.nodes
        for requirement in MANAGED_OPTIMIZATION_PROFILE.operation(node.operation_id).payload["runtime_requirements"]
    }
    runtime = MANAGED_OPTIMIZATION_PROFILE.runtime_attestation(
        tuple(node.operation_id for node in graph.nodes), version_resolver=versions.__getitem__
    ).as_dict()
    evidence = CanonicalExecutionEvidence.from_validation_execution(validation, runtime_attestation=runtime)
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
    capsule = CanonicalWorkflowCapsule.from_admitted_request(
        {**unsigned, "request_digest": _digest(unsigned)},
        evidence,
        full_refit_evidence=refit_evidence,
    )
    return capsule, CanonicalFittedArtifact.from_full_refit_execution(refit)


def test_application_plan_is_a_closed_visible_projection_of_the_verified_graph() -> None:
    capsule, artifact = _capsule_and_artifact()

    plan = CanonicalApplicationPlan.from_capsule_and_artifact(capsule, artifact)
    loaded = CanonicalApplicationPlan.from_dict(plan.as_dict())

    assert loaded.as_dict() == plan.as_dict()
    assert plan.payload["schema_version"] == CANONICAL_APPLICATION_PLAN_VERSION
    assert plan.payload["capsule_digest"] == capsule.capsule_digest
    assert plan.payload["artifact_digest"] == artifact.artifact_digest
    assert [node["node_id"] for node in plan.payload["nodes"]] == ["scale", "model"]
    assert [node["application_operation_id"] for node in plan.payload["nodes"]] == [
        "preprocess.apply_fitted_scale",
        "model.apply_fitted_pls",
    ]
    assert [node["application_contract_digest"] for node in plan.payload["nodes"]] == [
        node_registry.get_metadata("preprocess.apply_fitted_scale").resolved_execution_contract().digest,
        node_registry.get_metadata("model.apply_fitted_pls").resolved_execution_contract().digest,
    ]
    assert plan.application_contract_status == "application_contracts_bound"
    assert plan.payload["edges"] == [
        {"from_node_id": "scale", "from_output": "default", "to_node_id": "model", "to_input": "default"}
    ]
    assert plan.payload["nodes"][0]["artifact_binding"]["state_node_id"] == "scale"
    assert plan.payload["nodes"][1]["artifact_binding"]["state_node_id"] == "model"
    assert "state_bytes" not in json.dumps(plan.as_dict(), sort_keys=True)


@pytest.mark.parametrize(
    ("legacy_source_digest", "legacy_application_digest"),
    [
        (
            "64bdf49b4d1cc289f43edca2e760037b3ce6c82e731bbb3c9aa1b7c7460028a8",
            "7a54cae94c875d150e16ea321960b6b3db5f1176cae2756f007d1bd134c94cf9",
        ),
        (
            "ac05f06a069e5551f5cd101dbaec0d40ff352860b360a98e367e1f17dbbaf98d",
            "efee828721a2fa29dc3ddb8b0737a9fcd72d45830b5c9db391438cdd4f087baa",
        ),
    ],
)
def test_suffix_era_pls_application_plan_requires_refit_for_response_authority(
    legacy_source_digest: str,
    legacy_application_digest: str,
) -> None:
    capsule, artifact = _capsule_and_artifact()
    legacy = CanonicalApplicationPlan.from_capsule_and_artifact(capsule, artifact).as_dict()
    model = next(node for node in legacy["nodes"] if node["node_id"] == "model")
    model["source_operation_id"] = "model.fitted_pls_v2"
    model["source_contract_digest"] = legacy_source_digest
    model["application_operation_id"] = "model.apply_fitted_pls_v2"
    model["application_contract_digest"] = legacy_application_digest
    model["artifact_binding"]["source_contract_digest"] = legacy_source_digest
    legacy["application_plan_digest"] = _digest(
        {key: value for key, value in legacy.items() if key != "application_plan_digest"}
    )

    with pytest.raises(CanonicalApplicationPlanError, match="source operation is not currently re-admitted"):
        CanonicalApplicationPlan.from_dict(legacy)


def test_application_execution_projects_the_plan_into_the_canonical_executor_workflow() -> None:
    capsule, artifact = _capsule_and_artifact()
    plan = CanonicalApplicationPlan.from_capsule_and_artifact(capsule, artifact)

    workflow = application_workflow(plan)

    assert [node["node_type"] for node in workflow.payload["nodes"]] == [
        "deploy.input",
        "model.apply_fitted_pls",
        "preprocess.apply_fitted_scale",
    ]
    assert workflow.payload["edges"] == [
        {
            "from_node_id": "canonical.application.input",
            "from_output": "default",
            "to_node_id": "scale",
            "to_input": "default",
        },
        {
            "from_node_id": "scale",
            "from_output": "default",
            "to_node_id": "model",
            "to_input": "default",
        },
    ]
    assert workflow.payload["nodes"][1]["parameters"] == plan.payload["nodes"][1]["artifact_binding"]


def test_cross_refit_artifact_cannot_be_joined_to_a_capsule() -> None:
    _capsule, artifact = _capsule_and_artifact()
    other_capsule, _other_artifact = _capsule_and_artifact(offset=0.5)

    with pytest.raises(CanonicalApplicationPlanError, match="artifact refit differs"):
        CanonicalApplicationPlan.from_capsule_and_artifact(
            other_capsule,
            artifact,
        )


def test_application_plan_retains_an_admitted_stateless_transform_without_state() -> None:
    capsule, artifact = _capsule_and_artifact(include_stateless_smooth=True)

    plan = CanonicalApplicationPlan.from_capsule_and_artifact(capsule, artifact)

    smooth = plan.payload["nodes"][0]
    assert smooth == {
        "node_id": "smooth",
        "source_operation_id": "preprocess.smooth",
        "source_contract_digest": capsule.graph.nodes[0].contract.digest,
        "parameters": {"method": "gaussian", "size": 11, "order": 2, "lam": 100.0, "d": "2", "sigma": 1.0},
        "application_operation_id": "preprocess.smooth",
        "application_contract_digest": capsule.graph.nodes[0].contract.digest,
    }
    assert "smooth" not in {member["node_id"] for member in artifact.payload["state_members"]}


@pytest.mark.parametrize(
    ("source_operation", "parameters", "application_operation"),
    [
        ("preprocess.msc", {"reference_method": "mean"}, "preprocess.apply_fitted_msc"),
        (
            "preprocess.emsc",
            {"reference_method": "median", "poly_order": 1},
            "preprocess.apply_fitted_emsc",
        ),
        ("preprocess.osc", {"n_components": 1}, "preprocess.apply_fitted_osc"),
    ],
)
def test_fitted_preprocessing_projects_to_exact_artifact_application_contract(
    source_operation: str,
    parameters: dict[str, object],
    application_operation: str,
) -> None:
    capsule, artifact = _capsule_and_artifact(fitted_preprocess=(source_operation, parameters))

    plan = CanonicalApplicationPlan.from_capsule_and_artifact(capsule, artifact)

    projected = plan.payload["nodes"][0]
    assert projected["node_id"] == "fitted-preprocess"
    assert projected["source_operation_id"] == source_operation
    assert projected["application_operation_id"] == application_operation
    assert projected["artifact_binding"]["state_node_id"] == "fitted-preprocess"
    assert projected["application_contract_digest"] == (
        node_registry.get_metadata(application_operation).resolved_execution_contract().digest
    )


def test_plan_rejects_a_reordered_or_name_only_artifact_binding() -> None:
    capsule, artifact = _capsule_and_artifact()
    plan = CanonicalApplicationPlan.from_capsule_and_artifact(capsule, artifact).as_dict()
    plan["nodes"][0]["artifact_binding"]["state_node_id"] = "model"
    plan["application_plan_digest"] = _digest(
        {key: value for key, value in plan.items() if key != "application_plan_digest"}
    )

    with pytest.raises(CanonicalApplicationPlanError, match="binding identity"):
        CanonicalApplicationPlan.from_dict(plan)


def test_plan_rejects_a_rehashed_topology_or_artifact_substitution() -> None:
    capsule, artifact = _capsule_and_artifact()
    plan = CanonicalApplicationPlan.from_capsule_and_artifact(capsule, artifact).as_dict()
    plan["edges"][0]["from_node_id"] = "model"
    plan["edges"][0]["to_node_id"] = "scale"
    plan["application_plan_digest"] = _digest(
        {key: value for key, value in plan.items() if key != "application_plan_digest"}
    )

    with pytest.raises(CanonicalApplicationPlanError, match="topology"):
        CanonicalApplicationPlan.from_dict(plan)

    plan = CanonicalApplicationPlan.from_capsule_and_artifact(capsule, artifact).as_dict()
    plan["nodes"][0]["artifact_binding"]["artifact_digest"] = "0" * 64
    plan["application_plan_digest"] = _digest(
        {key: value for key, value in plan.items() if key != "application_plan_digest"}
    )

    with pytest.raises(CanonicalApplicationPlanError, match="binding identity"):
        CanonicalApplicationPlan.from_dict(plan)


def test_plan_rejects_an_unbound_or_extra_field_even_when_rehashed() -> None:
    capsule, artifact = _capsule_and_artifact()
    plan = CanonicalApplicationPlan.from_capsule_and_artifact(capsule, artifact).as_dict()
    del plan["nodes"][0]["artifact_binding"]
    plan["application_plan_digest"] = _digest(
        {key: value for key, value in plan.items() if key != "application_plan_digest"}
    )

    with pytest.raises(CanonicalApplicationPlanError, match="stateless application node"):
        CanonicalApplicationPlan.from_dict(plan)


def test_plan_rejects_a_rehashed_application_contract_substitution() -> None:
    capsule, artifact = _capsule_and_artifact()
    plan = CanonicalApplicationPlan.from_capsule_and_artifact(capsule, artifact).as_dict()
    plan["nodes"][1]["application_contract_digest"] = "0" * 64
    plan["application_plan_digest"] = _digest(
        {key: value for key, value in plan.items() if key != "application_plan_digest"}
    )

    with pytest.raises(CanonicalApplicationPlanError, match="admitted execution contract"):
        CanonicalApplicationPlan.from_dict(plan)


def test_legacy_application_plan_is_rejected_before_it_can_execute() -> None:
    capsule, artifact = _capsule_and_artifact()
    current = CanonicalApplicationPlan.from_capsule_and_artifact(capsule, artifact).as_dict()
    for node in current["nodes"]:
        del node["application_contract_digest"]
    current["schema_version"] = "spectra-canonical-application-plan/1"
    current["application_plan_digest"] = _digest(
        {key: value for key, value in current.items() if key != "application_plan_digest"}
    )

    with pytest.raises(CanonicalApplicationPlanError, match="schema is unsupported"):
        CanonicalApplicationPlan.from_dict(current)
