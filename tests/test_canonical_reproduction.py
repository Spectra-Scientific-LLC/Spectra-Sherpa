"""OSS-only scientific reproduction tests for canonical project packages."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.regression_evaluator_node  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.canonical_selection_policy import (
    CanonicalSelectionPolicy,
    build_canonical_development_decision,
    selection_candidate,
)
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.fold_graph_executor import (
    execute_candidate_validation,
    execute_selected_candidate_full_refit,
)
from spectra_sherpa.app.services.dag.managed_optimization_profile import managed_optimization_profile
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.sdk import canonical_reproduction
from spectra_sherpa.sdk.canonical_application import CanonicalApplicationPlan
from spectra_sherpa.sdk.canonical_campaign_evidence import CanonicalCampaignEvidence
from spectra_sherpa.sdk.canonical_capsule import CanonicalWorkflowCapsule
from spectra_sherpa.sdk.canonical_confirmation_history import CanonicalConfirmationHistory
from spectra_sherpa.sdk.canonical_execution_evidence import CanonicalExecutionEvidence
from spectra_sherpa.sdk.canonical_fitted_artifact import CanonicalFittedArtifact
from spectra_sherpa.sdk.canonical_full_refit_evidence import CanonicalFullRefitEvidence
from spectra_sherpa.sdk.canonical_project import CanonicalProjectPackage
from spectra_sherpa.sdk.canonical_reproduction import (
    CanonicalReproductionReport,
    reproduce_canonical_project,
)
from spectra_sherpa.sdk.local_model_record import LocalModelRecord, LocalRecordActor
from spectra_sherpa.sdk.validate import (
    ClassificationMetricAccumulator,
    make_classification_split_plan,
    make_split_plan,
    pool_supervised_metric_records,
    supervised_metric_task,
)

MANAGED_OPTIMIZATION_PROFILE = managed_optimization_profile()


def _campaign_evidence(
    *,
    capsule: CanonicalWorkflowCapsule,
    artifact: CanonicalFittedArtifact,
    application_plan: CanonicalApplicationPlan,
) -> CanonicalCampaignEvidence:
    """Bind the reproduction fixture to a genuine two-candidate decision."""

    request = capsule.payload["admitted_request"]
    selected_graph = request["graph"]
    selected_graph_digest = selected_graph["graph_digest"]
    selected_validation = capsule.execution_evidence.payload["validation_execution"]
    baseline_validation = copy.deepcopy(selected_validation)
    baseline_validation["graph_digest"] = selected_graph_digest
    if supervised_metric_task(baseline_validation["metrics"]) == "classification":
        for fold in baseline_validation["folds"]:
            metrics = fold["metrics"]
            labels = metrics["labels"]
            accumulator = ClassificationMetricAccumulator(labels)
            y_true: list[str] = []
            for label, row in zip(labels, metrics["confusion_matrix"], strict=True):
                y_true.extend([label] * sum(row))
            accumulator.add(y_true, [labels[0]] * len(y_true))
            fold["metrics"] = accumulator.metrics().as_dict()
        baseline_validation["metrics"] = pool_supervised_metric_records(
            [fold["metrics"] for fold in baseline_validation["folds"]]
        )
    else:
        for fold in baseline_validation["folds"]:
            fold["metrics"]["rmse"] += 1.0
        total = baseline_validation["metrics"]["n_samples"]
        baseline_validation["metrics"]["rmse"] = math.sqrt(
            sum(fold["metrics"]["n_samples"] * fold["metrics"]["rmse"] ** 2 for fold in baseline_validation["folds"])
            / total
        )
    candidates = [
        {
            "status": "succeeded",
            "candidate_id": "baseline-candidate-001",
            "ordinal": 1,
            "declared_ordinal": 1,
            "candidate_digest": selected_graph_digest,
            "graph_digest": selected_graph_digest,
            "candidate_graph": selected_graph,
            "request_digest": "d" * 64,
            "result_digest": "e" * 64,
            "validation_execution": baseline_validation,
        },
        {
            "status": "succeeded",
            "candidate_id": request["candidate_id"],
            "ordinal": 2,
            "declared_ordinal": 2,
            "candidate_digest": application_plan.payload["graph_digest"],
            "graph_digest": application_plan.payload["graph_digest"],
            "candidate_graph": selected_graph,
            "request_digest": request["request_digest"],
            "result_digest": "1" * 64,
            "validation_execution": selected_validation,
        },
    ]

    def decision_input(candidate: dict) -> dict:
        validation = candidate["validation_execution"]
        return selection_candidate(
            candidate_id=candidate["candidate_id"],
            ordinal=candidate["ordinal"],
            result_digest=candidate["result_digest"],
            dataset_content_digest=validation["capability_content_digest"],
            split_plan_digest=validation["split_plan_digest"],
            metrics=validation["metrics"],
            folds=[
                {
                    "partition_digest": fold["partition_digest"],
                    "metrics": fold["metrics"],
                }
                for fold in validation["folds"]
            ],
        )

    decision = build_canonical_development_decision(
        [decision_input(candidate) for candidate in candidates],
        policy=CanonicalSelectionPolicy.build(
            0.0,
            task_type=supervised_metric_task(selected_validation["metrics"]),
        ),
    )
    return CanonicalCampaignEvidence.build(
        campaign={
            "campaign_id": request["campaign_id"],
            "search_space_digest": request["search"]["search_space_digest"],
            "decision_digest": "3" * 64,
            "claim_scope": "public_reproducibility_only",
            "optimization_lane": (
                "categorical_classification"
                if selected_validation["task_type"] == "classification"
                else "quantitative_calibration"
            ),
        },
        candidates=candidates,
        decision=decision,
        winner_refit={
            "candidate_id": request["candidate_id"],
            "authority_digest": "4" * 64,
            "refit_request_digest": "5" * 64,
            "refit_terminal_digest": "6" * 64,
            "full_refit_execution_digest": application_plan.payload["full_refit_execution_digest"],
            "artifact_digest": artifact.artifact_digest,
        },
    )


def _campaign_provenance(evidence: CanonicalCampaignEvidence) -> dict:
    candidates = evidence.payload["candidates"]
    winner_id = evidence.payload["winner_refit"]["candidate_id"]
    winner = next(candidate for candidate in candidates if candidate["candidate_id"] == winner_id)
    return {
        "campaign_id": evidence.payload["campaign"]["campaign_id"],
        "candidate_id": winner_id,
        "candidate_ordinal": winner["ordinal"],
        "candidate_count": len(candidates),
        "candidate_ids": [candidate["candidate_id"] for candidate in candidates],
        "baseline_candidate_id": candidates[0]["candidate_id"],
        "search_space_digest": evidence.payload["campaign"]["search_space_digest"],
        "selection_status": "selected",
        "decision_digest": evidence.payload["campaign"]["decision_digest"],
    }


def _fixture(
    *,
    shifted: bool = False,
    custody_id: str = "public-fixture",
) -> tuple[SpectralDatasetCapability, object]:
    X = np.arange(96, dtype=float).reshape(12, 8)
    if shifted:
        X = X.copy()
        X[0, 0] += 0.5
    target = X[:, 0] * 0.3 + X[:, 1] * 0.1
    split = make_split_plan(X.shape[0], n_splits=3)
    capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(
            X=X,
            target=target,
            feature_axis=SpectralAxis(values=np.arange(X.shape[1], dtype=float), units="cm-1"),
        ),
        custody_id=custody_id,
        dataset_ref_digest="a" * 64,
        split_plan_digest=split.digest,
    )
    return capability, split


def _classification_fixture() -> tuple[SpectralDatasetCapability, object]:
    rng = np.random.default_rng(20260815)
    target = np.repeat(np.asarray(["control", "blend-a", "blend-b"], dtype="U8"), 8)
    X = rng.normal(scale=0.08, size=(target.size, 12))
    X[target == "control", :4] += 0.2
    X[target == "blend-a", 4:8] += 1.4
    X[target == "blend-b", 8:12] += 2.2
    split = make_classification_split_plan(target, n_splits=4)
    capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(
            X=X,
            target=target,
            feature_axis=SpectralAxis(values=np.arange(X.shape[1], dtype=float), units="cm-1"),
        ),
        custody_id="public-classification-fixture",
        dataset_ref_digest="8" * 64,
        split_plan_digest=split.digest,
    )
    return capability, split


async def _build_package(
    *,
    classification: bool = False,
    custody_id: str | None = None,
) -> CanonicalProjectPackage:
    """Build a public first-party package, independently from its verifier."""

    fixture, split = (
        _classification_fixture()
        if classification
        else _fixture(custody_id="public-fixture" if custody_id is None else custody_id)
    )
    nodes = (
        [
            WorkflowNode("model", "classification.plsda", {"n_components": 2, "scale": True}),
            WorkflowNode("score", "diagnostics.classification_evaluator", {}),
        ]
        if classification
        else [
            WorkflowNode("scale", "preprocess.scale", {"method": "autoscale", "center": True}),
            WorkflowNode("model", "model.fitted_pls", {"n_components": 2, "scale": True}),
            WorkflowNode("score", "diagnostics.regression_evaluator", {}),
        ]
    )
    graph = admit_validation_graph(
        nodes,
        [
            WorkflowEdge(
                left.node_id,
                right.node_id,
                "predictions" if classification else "default",
                "default",
            )
            for left, right in zip(nodes, nodes[1:])
        ],
    )
    validation = await execute_candidate_validation(graph, fixture, split)
    refit = await execute_selected_candidate_full_refit(graph, fixture, validation)
    versions = {
        str(requirement["distribution"]): str(requirement["version"])
        for node in graph.nodes
        for requirement in MANAGED_OPTIMIZATION_PROFILE.operation(node.operation_id).payload["runtime_requirements"]
    }
    runtime = MANAGED_OPTIMIZATION_PROFILE.runtime_attestation(
        tuple(node.operation_id for node in graph.nodes), version_resolver=versions.__getitem__
    ).as_dict()
    unsigned: dict[str, object] = {
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
        "capability_digest": fixture.envelope_digest,
        "dataset_content_digest": fixture.content_digest,
        "dataset_ref_digest": "8" * 64 if classification else "a" * 64,
        "dataset_shape": {
            "n_samples": int(fixture.arrays["X"].shape[0]),
            "n_features": int(fixture.arrays["X"].shape[1]),
            "grouped": False,
        },
        "split_digest": split.digest,
        "validation": {
            "schema_version": "spectra-canonical-validation/3",
            "task_type": "classification" if classification else "regression",
            "selection": (
                "stratified_group_kfold_when_groups_else_stratified_kfold"
                if classification
                else "group_kfold_when_groups_else_kfold"
            ),
            "outer_splits": 4 if classification else 3,
            "shuffle": False,
            "metric_registry_version": "1" if classification else "2",
            "primary_metric": "balanced_accuracy" if classification else "rmse",
        },
        "search": {
            "schema_version": "spectra-canonical-search-execution/2",
            "strategy": "finite_declared_parameter_grid",
            "search_space_digest": "9" * 64,
            "candidate_ordinal": 2,
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
    request = {
        **unsigned,
        "request_digest": hashlib.sha256(
            json.dumps(
                unsigned,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest(),
    }
    evidence = CanonicalExecutionEvidence.from_validation_execution(validation, runtime_attestation=runtime)
    refit_evidence = CanonicalFullRefitEvidence.from_full_refit_execution(refit)
    capsule = CanonicalWorkflowCapsule.from_admitted_request(request, evidence, full_refit_evidence=refit_evidence)
    artifact = CanonicalFittedArtifact.from_full_refit_execution(refit)
    plan = CanonicalApplicationPlan.from_capsule_and_artifact(capsule, artifact)
    campaign_evidence = _campaign_evidence(
        capsule=capsule,
        artifact=artifact,
        application_plan=plan,
    )
    record = LocalModelRecord.from_canonical(
        capsule=capsule,
        artifact=artifact,
        application_plan=plan,
        capability=fixture,
        actor=LocalRecordActor(kind="local_user", ref="reproduction-fixture"),
        recorded_at="2026-08-13T12:00:00+00:00",
        campaign_provenance=_campaign_provenance(campaign_evidence),
    )
    return CanonicalProjectPackage.build(
        capsule=capsule,
        artifact=artifact,
        application_plan=plan,
        local_model_record=record,
        campaign_evidence=campaign_evidence,
        confirmation_history=CanonicalConfirmationHistory.not_requested(
            campaign_id=campaign_evidence.payload["campaign"]["campaign_id"], campaign_record_id=1
        ),
    )


def test_native_plsda_campaign_exports_imports_and_reproduces_in_oss() -> None:
    """Classification follows the same complete package path as regression."""

    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")
    package = asyncio.run(_build_package(classification=True))
    fixture, split = _classification_fixture()

    imported = CanonicalProjectPackage.from_archive(package.archive)
    assert imported.application_plan.payload["nodes"][-1]["application_operation_id"] == "classification.apply_plsda"
    strategy = imported.campaign_evidence.payload["decision"]["strategy"]
    assert strategy["schema_version"] == "spectra-canonical-selection-policy/2"
    assert strategy["task_type"] == "classification"
    assert strategy["primary_metric"] == "balanced_accuracy"
    assert strategy["optimization_direction"] == "maximize"
    assert strategy["minimum_improvement"] == 0.0

    report = reproduce_canonical_project(imported, fixture=fixture, split_plan=split)
    assert report.payload["validation_reproduced"]["status"] == "passed"
    assert report.payload["validation_reproduced"]["expected_metrics"]["task_type"] == "classification"
    assert report.payload["application_reproduced"]["status"] == "passed"
    assert report.payload["application_reproduced"]["prediction_match"] is True


def test_oss_reproduction_recomputes_validation_and_application_without_server_import() -> None:
    """A package digest is not enough: both real local execution paths run."""

    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")
    package = asyncio.run(_build_package())
    fixture, split = _fixture()

    report = reproduce_canonical_project(package.archive, fixture=fixture, split_plan=split)
    loaded = CanonicalReproductionReport.from_dict(report.as_dict())

    assert loaded.as_dict() == report.as_dict()
    assert report.payload["integrity_verified"] == {"status": "passed", "reason": None}
    assert report.payload["publisher_authenticated"] == {
        "status": "not_provided",
        "reason": "publisher_attestation_not_provided",
    }
    validation = report.payload["validation_reproduced"]
    assert validation["status"] == "passed"
    assert validation["pooled_metric_match"] is True
    assert validation["fold_metric_matches"] == [True, True, True]
    application = report.payload["application_reproduced"]
    assert application["status"] == "passed"
    assert application["prediction_match"] is True
    assert application["source_prediction_digest"] == application["application_prediction_digest"]
    assert not any(name == "spectrasherpa_server" or name.startswith("spectrasherpa_server.") for name in sys.modules)


def test_oss_reproduction_preserves_integrity_when_the_fixture_cannot_be_reproduced() -> None:
    """A wrong local data source never becomes a generic verified result."""

    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")
    package = asyncio.run(_build_package())
    fixture, split = _fixture(shifted=True)

    report = reproduce_canonical_project(package, fixture=fixture, split_plan=split)

    assert report.payload["integrity_verified"]["status"] == "passed"
    assert report.payload["validation_reproduced"] == {
        "status": "not_run",
        "reason": "fixture_or_split_identity_mismatch",
    }
    assert report.payload["application_reproduced"] == {
        "status": "not_run",
        "reason": "fixture_or_split_identity_mismatch",
    }


def _drifted_validation(package: CanonicalProjectPackage, fixture, split, *, rmse_delta: float):
    """Return a stand-in execution whose recomputed RMSE differs by ``rmse_delta``.

    The package itself stays honest and untampered. This models the failure the
    verifier actually exists to catch: the managed publisher reported one
    number, and independent local re-execution produces another -- because the
    publisher's runtime differed, its implementation drifted, or its claim was
    untrue. Forging the package instead would be caught earlier by integrity,
    which is a different outcome and is already covered above.
    """

    execution = asyncio.run(execute_candidate_validation(package.capsule.graph, fixture, split))
    drifted = copy.deepcopy(execution.as_dict())
    drifted["metrics"]["rmse"] += rmse_delta
    for fold in drifted["folds"]:
        fold["metrics"]["rmse"] += rmse_delta

    class _DriftedExecution:
        def as_dict(self):
            return copy.deepcopy(drifted)

    async def _execute(_graph, _fixture, _split):
        return _DriftedExecution()

    return _execute


def test_oss_reproduction_reports_failed_when_local_execution_diverges(monkeypatch) -> None:
    """A claim the local runtime cannot reproduce is failed, never 'verified'."""

    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")
    package = asyncio.run(_build_package())
    fixture, split = _fixture()
    monkeypatch.setattr(
        canonical_reproduction,
        "execute_candidate_validation",
        _drifted_validation(package, fixture, split, rmse_delta=0.5),
    )

    report = reproduce_canonical_project(package, fixture=fixture, split_plan=split)
    validation = report.payload["validation_reproduced"]

    assert validation["status"] == "failed"
    assert validation["reason"] == "canonical_validation_metrics_differ"
    assert validation["pooled_metric_match"] is False
    assert all(match is False for match in validation["fold_metric_matches"])
    assert validation["expected_metrics"]["rmse"] != validation["actual_metrics"]["rmse"]
    # The four outcomes must stay separable: an unreproducible scientific claim
    # does not retroactively make the bytes corrupt, and it does not suppress
    # the independent artifact-application result.
    assert report.payload["integrity_verified"]["status"] == "passed"
    assert report.payload["application_reproduced"]["status"] == "passed"


@pytest.mark.parametrize(
    ("rmse_delta", "expected_status"),
    [(1e-15, "passed"), (1e-6, "failed")],
)
def test_oss_reproduction_metric_parity_tolerance_is_exact_not_decorative(
    monkeypatch, rmse_delta: float, expected_status: str
) -> None:
    """Parity is bounded by the published tolerance, not by a loose eyeball."""

    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")
    package = asyncio.run(_build_package())
    fixture, split = _fixture()
    monkeypatch.setattr(
        canonical_reproduction,
        "execute_candidate_validation",
        _drifted_validation(package, fixture, split, rmse_delta=rmse_delta),
    )

    report = reproduce_canonical_project(package, fixture=fixture, split_plan=split)

    assert report.payload["validation_reproduced"]["status"] == expected_status


@pytest.mark.parametrize("metadata", [False, True])
def test_regression_prediction_projection_preserves_values_without_metadata_egress(metadata):
    from spectra_sherpa.app.services.dag.node_base import NodeResult

    predictions = np.array([[1.0], [2.0]])
    outputs = {"default": predictions}
    if metadata:
        outputs.update(prediction_identity={"private": "identity"}, applicability={}, prediction_intervals={})
    projected = canonical_reproduction._prediction_output(NodeResult(outputs=outputs), "model", task="regression")
    np.testing.assert_array_equal(projected, predictions)
    assert projected is not predictions
    outputs["unexpected"] = ["sample-level-content"]
    with pytest.raises(canonical_reproduction.CanonicalReproductionError, match="did not produce predictions"):
        canonical_reproduction._prediction_output(NodeResult(outputs=outputs), "model", task="regression")
