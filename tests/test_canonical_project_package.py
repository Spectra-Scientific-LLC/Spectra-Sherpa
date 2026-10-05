"""Offline package tests for the canonical project export boundary."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import math
import zipfile
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.regression_evaluator_node  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset, SpectralAxis, TargetContext
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
from spectra_sherpa.app.services.dag.validation_graph import ValidationGraphError, admit_validation_graph
from spectra_sherpa.app.types import type_registry
from spectra_sherpa.sdk.campaign_review import (
    CAMPAIGN_REVIEW_DELIVERABLE,
    CampaignReviewError,
    CampaignReviewPackage,
    inspect_campaign_review_package,
)
from spectra_sherpa.sdk.canonical_application import CanonicalApplicationPlan
from spectra_sherpa.sdk.canonical_campaign_evidence import CanonicalCampaignEvidence
from spectra_sherpa.sdk.canonical_capsule import CanonicalWorkflowCapsule
from spectra_sherpa.sdk.canonical_confirmation_history import CanonicalConfirmationHistory
from spectra_sherpa.sdk.canonical_execution_evidence import CanonicalExecutionEvidence
from spectra_sherpa.sdk.canonical_fitted_artifact import CanonicalFittedArtifact
from spectra_sherpa.sdk.canonical_full_refit_evidence import CanonicalFullRefitEvidence
from spectra_sherpa.sdk.canonical_project import CanonicalProjectPackage, CanonicalProjectPackageError
from spectra_sherpa.sdk.canonical_publisher_attestation import (
    CANONICAL_PUBLISHER_TRUST_ANCHORS_VERSION,
    CanonicalProjectAttestationSigner,
    CanonicalPublisherAttestationInput,
    CanonicalPublisherTrustAnchors,
)
from spectra_sherpa.sdk.local_model_record import LocalModelRecord, LocalModelRecordError, LocalRecordActor
from spectra_sherpa.sdk.project import (
    ProjectIOError,
    compare_projects,
    inspect_project,
    load,
    load_bounded_json_object,
    reexport,
)
from spectra_sherpa.sdk.validate import make_split_plan

MANAGED_OPTIMIZATION_PROFILE = managed_optimization_profile()


@pytest.fixture(autouse=True)
def _load_type_registry() -> None:
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app" / "types")


async def _build_package(
    *,
    include_local_only_rubberband: bool = False,
    preprocessing_node_id: str = "scale",
    model_family: str = "pls",
) -> CanonicalProjectPackage:
    """Build a sealed first-party package with an optional local-only transform.

    The optional rubberband transform intentionally shares the same refit,
    application-plan, archive, and later project-import path as the native
    fixture.  It remains outside the managed profile because artifact
    application cannot replay the transform, not because it requires SCP.
    """

    X = np.arange(96, dtype=float).reshape(12, 8)
    y = X[:, 0] * 0.3 + X[:, 1] * 0.1
    split = make_split_plan(len(X), n_splits=3)
    capability = SpectralDatasetCapability.from_dataset(
        SherpaDataset(
            X=X,
            target=y,
            feature_axis=SpectralAxis(values=np.arange(X.shape[1], dtype=float), units="cm-1"),
            domain=DomainContext(technique="NIR", measurement_mode="reflectance"),
            target_context=TargetContext(target_type="continuous", target_units="percent"),
        ),
        custody_id="public-fixture",
        dataset_ref_digest="a" * 64,
        split_plan_digest=split.digest,
    )
    nodes = [
        *([WorkflowNode("rubberband", "baseline.rubberband", {})] if include_local_only_rubberband else []),
        WorkflowNode(preprocessing_node_id, "preprocess.scale", {"method": "autoscale", "center": True}),
        WorkflowNode(
            "model",
            f"model.fitted_{model_family}",
            {"n_components": 2, "scale": True} if model_family in {"pls", "pcr"} else {},
        ),
        WorkflowNode("score", "diagnostics.regression_evaluator", {}),
    ]
    graph = admit_validation_graph(nodes, [WorkflowEdge(a.node_id, b.node_id) for a, b in zip(nodes, nodes[1:])])
    validation = await execute_candidate_validation(graph, capability, split)
    refit = await execute_selected_candidate_full_refit(graph, capability, validation)
    versions = {
        str(requirement["distribution"]): str(requirement["version"])
        for node in graph.nodes
        for requirement in MANAGED_OPTIMIZATION_PROFILE.operation(node.operation_id).payload["runtime_requirements"]
    }
    runtime = MANAGED_OPTIMIZATION_PROFILE.runtime_attestation(
        tuple(node.operation_id for node in graph.nodes), version_resolver=versions.__getitem__
    ).as_dict()
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
            json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
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
        capability=capability,
        actor=LocalRecordActor(kind="local_user", ref="fixture-user"),
        recorded_at="2026-08-07T12:00:00+00:00",
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


def _package(
    *, include_local_only_rubberband: bool = False, preprocessing_node_id: str = "scale"
) -> CanonicalProjectPackage:
    """Synchronous package fixture used by the archive-only test module."""

    return asyncio.run(
        _build_package(
            include_local_only_rubberband=include_local_only_rubberband, preprocessing_node_id=preprocessing_node_id
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["pcr", "svr", "linear_regression"])
async def test_new_regression_models_roundtrip_sherpa_and_execute_bound_local_deploy(tmp_path, family):
    from spectra_sherpa.app.services.canonical_artifact_store import init_canonical_artifact_store
    from spectra_sherpa.app.services.dag.node_base import node_registry
    from spectra_sherpa.core.canonical_artifact import ReadOnlyCanonicalArtifactReader
    from spectra_sherpa.core.execution_runtime import ExecutionRuntime
    from spectra_sherpa.sdk.canonical_application_execution import execute_canonical_application
    from spectra_sherpa.sdk.fitted_state_custody import (
        DATA_FREE_APPLICATION_STATE,
        RETAINS_TRAINING_ROWS,
        fitted_state_custody_capability,
    )

    package = await _build_package(model_family=family)
    restored = CanonicalProjectPackage.from_archive(package.archive)
    member = next(item for item in restored.artifact.payload["state_members"] if item["node_id"] == "model")
    custody = fitted_state_custody_capability(member["serializer"], member["contract_digest"])
    assert custody.custody_class == (RETAINS_TRAINING_ROWS if family == "svr" else DATA_FREE_APPLICATION_STATE)
    assert restored.application_plan.payload["nodes"][-1]["application_operation_id"] == f"model.apply_fitted_{family}"

    artifact_path = restored.artifact.write_new((tmp_path / "received-artifact").resolve())
    store = init_canonical_artifact_store(tmp_path)
    store.install_from_directory(artifact_path)
    runtime = ExecutionRuntime(
        canonical_artifact_reader=ReadOnlyCanonicalArtifactReader(
            tmp_path, allowed_artifact_digests=(restored.artifact.artifact_digest,)
        )
    )
    X = np.arange(96, dtype=float).reshape(12, 8)
    incoming = SherpaDataset(
        X=X[:3],
        feature_axis=SpectralAxis(values=np.arange(8, dtype=float), units="cm-1"),
        domain=DomainContext(technique="NIR", measurement_mode="reflectance"),
    )
    result = await execute_canonical_application(restored.application_plan, incoming, runtime=runtime)
    # Independent application of the exact archived states, without fitting on incoming rows.
    expected = incoming
    for node in restored.application_plan.payload["nodes"]:
        state = json.loads(restored.artifact.state_bytes[node["node_id"]])
        operation = node_registry.create_node(node["source_operation_id"], node["node_id"], {})
        expected = operation.apply_fitted_state(expected, state)
    np.testing.assert_allclose(result.results["model"]["default"], expected)
    unauthorized_runtime = ExecutionRuntime(
        canonical_artifact_reader=ReadOnlyCanonicalArtifactReader(tmp_path, allowed_artifact_digests=("0" * 64,))
    )
    with pytest.raises(ValueError, match="grant|authorized|allowed"):
        await execute_canonical_application(restored.application_plan, incoming, runtime=unauthorized_runtime)

    if family == "svr":
        # A data-bearing .sherpa remains portable; a data-free signed review must refuse it.
        with pytest.raises(CampaignReviewError, match="cannot claim data-free custody"):
            _review_package(restored)
    else:
        review, anchors = _review_package(restored)
        inspected = inspect_campaign_review_package(review.archive, publisher_trust_anchors=anchors.as_dict())
        assert inspected.as_dict()["package"]["data_members"] == "none"


def _review_package(
    application: CanonicalProjectPackage,
) -> tuple[CampaignReviewPackage, CanonicalPublisherTrustAnchors]:
    signer = CanonicalProjectAttestationSigner(
        issuer="spectra-scientific-test",
        key_id="test-review-key",
        custody_ref="test-custody",
        private_key=Ed25519PrivateKey.from_private_bytes(bytes(range(32))),
    )
    publisher_input = CanonicalPublisherAttestationInput.from_package(
        application,
        tenant_id="test-tenant",
        terminal_result_digest="7" * 64,
        decision="selected",
        claim_scope="public_reproducibility_only",
        confirmation_disposition="not_requested",
    )
    attestation = signer.sign(
        publisher_input.to_statement(
            issuer=signer.issuer,
            signer_key_id=signer.key_id,
            key_custody_ref=signer.custody_ref,
            executing_build={
                "attestation_status": "attested",
                "source_revision": "8" * 40,
                "image_id": "sha256:" + "9" * 64,
                "repository_digests": ["spectra/test@sha256:" + "a" * 64],
                "runtime_revision": "8" * 40,
            },
        )
    )
    anchors = CanonicalPublisherTrustAnchors.from_dict(
        {
            "schema_version": CANONICAL_PUBLISHER_TRUST_ANCHORS_VERSION,
            "issuer": signer.issuer,
            "keys": {signer.key_id: signer.public_key_b64()},
        }
    )
    return (
        CampaignReviewPackage.build(
            application=application,
            publisher_attestation=attestation,
            publisher_trust_anchors=anchors,
        ),
        anchors,
    )


def _campaign_evidence(
    *,
    capsule: CanonicalWorkflowCapsule,
    artifact: CanonicalFittedArtifact,
    application_plan: CanonicalApplicationPlan,
) -> CanonicalCampaignEvidence:
    """Build a two-candidate ledger that binds the fixture winner exactly.

    The fixture's admitted request is already the selected candidate.  The
    deliberately worse baseline lets the portable record prove that the
    selected result is a decision among declared candidates rather than a
    hand-picked application artifact.
    """

    selected_request = capsule.payload["admitted_request"]
    selected_graph = selected_request["graph"]
    selected_graph_digest = selected_graph["graph_digest"]
    selected_validation = capsule.execution_evidence.payload["validation_execution"]
    baseline_validation = deepcopy(selected_validation)
    baseline_validation["graph_digest"] = selected_graph_digest
    for fold in baseline_validation["folds"]:
        fold["metrics"]["rmse"] += 1.0
    total = baseline_validation["metrics"]["n_samples"]
    baseline_validation["metrics"]["rmse"] = math.sqrt(
        sum(fold["metrics"]["n_samples"] * fold["metrics"]["rmse"] ** 2 for fold in baseline_validation["folds"])
        / total
    )
    baseline = {
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
    }
    selected = {
        "status": "succeeded",
        "candidate_id": selected_request["candidate_id"],
        "ordinal": 2,
        "declared_ordinal": 2,
        "candidate_digest": application_plan.payload["graph_digest"],
        "graph_digest": application_plan.payload["graph_digest"],
        "candidate_graph": selected_graph,
        "request_digest": selected_request["request_digest"],
        "result_digest": "1" * 64,
        "validation_execution": selected_validation,
    }

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
        [decision_input(baseline), decision_input(selected)],
        policy=CanonicalSelectionPolicy.build(0.0),
    )
    return CanonicalCampaignEvidence.build(
        campaign={
            "campaign_id": selected_request["campaign_id"],
            "search_space_digest": selected_request["search"]["search_space_digest"],
            "decision_digest": "3" * 64,
            "claim_scope": "public_reproducibility_only",
            "optimization_lane": "quantitative_calibration",
        },
        candidates=[baseline, selected],
        decision=decision,
        winner_refit={
            "candidate_id": selected["candidate_id"],
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


@pytest.mark.asyncio
async def test_campaign_review_inspector_renders_the_complete_data_free_decision_chain() -> None:
    application = await _build_package()
    package, anchors = _review_package(application)

    inspection = inspect_campaign_review_package(
        package.archive,
        publisher_trust_anchors=anchors.as_dict(),
    )
    report = inspection.as_dict()

    assert report["deliverable"] == CAMPAIGN_REVIEW_DELIVERABLE
    assert report["package"]["integrity"] == "passed"
    assert report["package"]["data_members"] == "none"
    assert report["campaign"]["optimization_lane"] == "quantitative_calibration"
    assert len(report["candidate_ledger"]) == 2
    assert all(
        candidate["configuration"]["graph_digest"] == candidate["candidate_digest"]
        for candidate in report["candidate_ledger"]
    )
    assert all(candidate["folds"] for candidate in report["candidate_ledger"])
    assert report["decision"]["winner_candidate_id"] == report["terminal_refit"]["candidate_id"]
    assert report["terminal_refit"]["artifact_digest"] == application.artifact.artifact_digest
    assert report["fixed_application"]["selected_candidate_id"] == report["decision"]["winner_candidate_id"]
    assert report["verification"]["publisher_authenticated"]["status"] == "passed"
    # Inspection records the expected results; it never claims reproduction.
    validation = report["verification"]["validation_reproduced"]
    application_outcome = report["verification"]["application_reproduced"]
    assert validation["status"] == application_outcome["status"] == "not_run"
    request = application.capsule.payload["admitted_request"]
    recorded = application.capsule.execution_evidence.payload["validation_execution"]
    assert validation["recorded"]["metrics"] == recorded["metrics"]
    assert validation["recorded"]["fold_count"] == len(recorded["folds"])
    assert validation["recorded"]["dataset"]["dataset_content_digest"] == request["dataset_content_digest"]
    assert validation["recorded"]["dataset"]["split_digest"] == request["split_digest"]
    assert application_outcome["recorded"]["artifact_digest"] == application.artifact.artifact_digest
    assert (
        application_outcome["recorded"]["application_plan_digest"]
        == application.application_plan.application_plan_digest
    )
    assert application_outcome["recorded"]["held_out_confirmation"] == application.confirmation_history.disposition
    assert report["boundaries"] == {
        "contains_source_data": False,
        "can_create_or_resume_campaign": False,
        "can_search_or_select_candidates": False,
        "fixed_application_only": True,
        "claim_scope": "public_reproducibility_only",
    }
    encoded = inspection.canonical_bytes
    for forbidden in (b'"spectra"', b'"targets"', b'"predictions"', b'"filesystem_path"'):
        assert forbidden not in encoded


def test_campaign_review_package_keeps_signature_inside_but_does_not_infer_trust() -> None:
    application = _package()
    package, _anchors = _review_package(application)

    loaded = CampaignReviewPackage.from_archive(package.archive)
    report = inspect_campaign_review_package(loaded).as_dict()

    assert loaded.application.archive == application.archive
    assert report["package"]["sha256"] == package.archive_sha256
    assert report["package"]["fixed_application_sha256"] == application.archive_sha256
    assert report["verification"]["publisher_authenticated"] == {
        "status": "not_authenticated",
        "reason": "publisher_trust_anchors_not_supplied",
        "attestation_digest": package.publisher_attestation.digest,
    }


def test_campaign_review_package_rejects_attestation_or_application_substitution() -> None:
    package, _anchors = _review_package(_package())
    with zipfile.ZipFile(io.BytesIO(package.archive), "r") as source:
        members = {name: source.read(name) for name in source.namelist()}
    members["campaign-review/publisher-attestation.json"] = b'{"statement":{},"signature":"wrong"}'
    mutated = io.BytesIO()
    with zipfile.ZipFile(mutated, "w", zipfile.ZIP_DEFLATED) as output:
        for name, data in members.items():
            output.writestr(name, data)

    with pytest.raises(CampaignReviewError, match="archive is invalid"):
        CampaignReviewPackage.from_archive(mutated.getvalue())


def test_canonical_project_package_round_trips_every_canonical_identity() -> None:
    package = _package()
    loaded = CanonicalProjectPackage.from_archive(package.archive)

    assert loaded.archive_sha256 == hashlib.sha256(package.archive).hexdigest()
    assert loaded.application_plan.as_dict() == package.application_plan.as_dict()
    assert loaded.capsule.as_dict() == package.capsule.as_dict()
    assert loaded.artifact.as_dict() == package.artifact.as_dict()
    assert loaded.artifact.state_bytes == package.artifact.state_bytes
    assert loaded.project_payload["workflows"] == []
    assert loaded.project_payload["metadata"]["canonical_project"]["package_status"] == "awaiting_local_data_binding"


def test_project_facade_loads_and_inspects_four_distinct_outcomes(tmp_path: Path) -> None:
    package = _package()
    source = tmp_path / "managed-result.sherpa"
    source.write_bytes(package.archive)

    loaded = load(source)
    inspection = inspect_project(loaded)
    outcomes = inspection.outcomes.as_dict()

    assert loaded.archive_sha256 == package.archive_sha256
    assert inspection.package_sha256 == package.archive_sha256
    assert inspection.artifact_digest == package.artifact.artifact_digest
    assert outcomes == {
        "integrity_verified": {"status": "passed", "reason": None},
        "publisher_authenticated": {
            "status": "not_provided",
            "reason": "publisher_attestation_not_supplied",
        },
        "validation_reproduced": {
            "status": "not_run",
            "reason": "reproduction_report_not_supplied",
        },
        "application_reproduced": {
            "status": "not_run",
            "reason": "reproduction_report_not_supplied",
        },
    }
    assert "verified" not in outcomes


def test_project_facade_compares_scientific_identity_separately_from_archive_bytes() -> None:
    package = _package()
    renamed = CanonicalProjectPackage.build(
        capsule=package.capsule,
        artifact=package.artifact,
        application_plan=package.application_plan,
        local_model_record=package.local_model_record,
        campaign_evidence=package.campaign_evidence,
        confirmation_history=package.confirmation_history,
        project_name="Renamed project",
    )

    exact = compare_projects(package, package.archive)
    renamed_comparison = compare_projects(package, renamed)

    assert exact.archive_bytes_identical is True
    assert exact.scientific_identity_match is True
    assert renamed_comparison.archive_bytes_identical is False
    assert renamed_comparison.scientific_identity_match is True
    assert renamed_comparison.differing_identities == ()
    assert all(renamed_comparison.identity_matches.values())


def test_project_facade_reexports_only_admitted_exact_bytes(tmp_path: Path) -> None:
    package = _package()
    destination = tmp_path / "copy.sherpa"

    written = reexport(package.archive, destination)

    assert written == destination
    assert destination.read_bytes() == package.archive
    with pytest.raises(ProjectIOError, match="destination exists"):
        reexport(package, destination)
    destination.write_bytes(b"not a project")
    reexport(package, destination, overwrite=True)
    assert destination.read_bytes() == package.archive


def test_project_facade_rejects_remote_or_malformed_input(tmp_path: Path) -> None:
    malformed = tmp_path / "malformed.sherpa"
    malformed.write_bytes(b"not a canonical package")

    with pytest.raises(ProjectIOError, match="local paths only"):
        load("https://example.invalid/model.sherpa")
    with pytest.raises(ProjectIOError, match="integrity admission failed"):
        load(malformed)


def test_project_facade_refuses_symlinks_and_ambiguous_verification_json(tmp_path: Path) -> None:
    package = _package()
    actual = tmp_path / "actual.sherpa"
    actual.write_bytes(package.archive)
    linked = tmp_path / "linked.sherpa"
    linked.symlink_to(actual)
    with pytest.raises(ProjectIOError, match="unavailable"):
        load(linked)

    ambiguous = tmp_path / "ambiguous.json"
    ambiguous.write_text('{"issuer":"wrong","issuer":"accepted"}', encoding="utf-8")
    with pytest.raises(ProjectIOError, match="duplicate JSON keys"):
        load_bounded_json_object(ambiguous)


def test_canonical_project_package_carries_one_portable_local_model_record() -> None:
    """The required model record is portable, closed, and identity-bound."""

    package = _package()
    loaded = CanonicalProjectPackage.from_archive(package.archive)

    record = loaded.local_model_record
    assert record.record_digest == package.local_model_record.record_digest
    assert record.payload["model"]["artifact_digest"] == loaded.artifact.artifact_digest
    assert (
        record.payload["training_dataset"]["content_digest"]
        == loaded.capsule.payload["admitted_request"]["dataset_content_digest"]
    )
    assert record.payload["feature_domain"] == {
        "schema_version": "spectra-feature-domain-signature/1",
        "technique": "NIR",
        "measurement_mode": "reflectance",
        "axis_kind": "SpectralAxis",
        "axis_units": "cm-1",
        "feature_identity_digest": record.payload["feature_domain"]["feature_identity_digest"],
        "coordinate_start": 0.0,
        "coordinate_end": 7.0,
        "n_features": 8,
    }
    assert record.payload["performance"]["scalars"][0] == {
        "metric_id": "rmse",
        "value": record.payload["performance"]["scalars"][0]["value"],
        "objective": "minimize",
        "unit": "percent",
    }
    with zipfile.ZipFile(io.BytesIO(package.archive)) as zf:
        assert "canonical/local-model-record.json" in zf.namelist()
        assert b'"X"' not in zf.read("canonical/local-model-record.json")


@pytest.mark.parametrize(
    "mismatch",
    ("campaign_id", "candidate_id", "candidate_ordinal", "candidate_count", "search_space_digest"),
)
def test_local_model_record_rejects_campaign_identity_outside_its_capsule(mismatch: str) -> None:
    package = _package()
    payload = package.local_model_record.as_dict()
    campaign = payload["derivation"]["campaign"]
    if mismatch == "campaign_id":
        campaign["campaign_id"] = "another-campaign-001"
    elif mismatch in {"candidate_id", "candidate_ordinal"}:
        campaign["candidate_id"] = campaign["candidate_ids"][0]
        campaign["candidate_ordinal"] = 1
    elif mismatch == "candidate_count":
        campaign["candidate_ids"].append("extra-candidate-001")
        campaign["candidate_count"] = 3
    else:
        campaign["search_space_digest"] = "a" * 64
    unsigned = {key: item for key, item in payload.items() if key != "record_digest"}
    payload["record_digest"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    record = LocalModelRecord.from_dict(payload)

    with pytest.raises(LocalModelRecordError, match="campaign differs from canonical execution"):
        record.require_matches(
            capsule=package.capsule,
            artifact=package.artifact,
            application_plan=package.application_plan,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("baseline_candidate_id", "canonical-candidate-001"),
        ("decision_digest", "a" * 64),
    ),
)
def test_project_package_rejects_local_provenance_outside_campaign_evidence(field: str, value: str) -> None:
    package = _package()
    payload = package.local_model_record.as_dict()
    payload["derivation"]["campaign"][field] = value
    unsigned = {key: item for key, item in payload.items() if key != "record_digest"}
    payload["record_digest"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    record = LocalModelRecord.from_dict(payload)

    with pytest.raises(CanonicalProjectPackageError, match="does not match its campaign"):
        CanonicalProjectPackage.build(
            capsule=package.capsule,
            artifact=package.artifact,
            application_plan=package.application_plan,
            local_model_record=record,
            campaign_evidence=package.campaign_evidence,
            confirmation_history=package.confirmation_history,
        )


def test_canonical_project_package_carries_the_complete_selection_and_refit_ledger() -> None:
    """The current package closes the selected artifact back to every candidate."""

    package = _package()
    loaded = CanonicalProjectPackage.from_archive(package.archive)

    ledger = loaded.campaign_evidence.payload
    assert [candidate["ordinal"] for candidate in ledger["candidates"]] == [1, 2]
    assert ledger["decision"]["winner_candidate_id"] == loaded.capsule.payload["admitted_request"]["candidate_id"]
    assert ledger["winner_refit"]["artifact_digest"] == loaded.artifact.artifact_digest
    assert (
        ledger["winner_refit"]["full_refit_execution_digest"]
        == loaded.application_plan.payload["full_refit_execution_digest"]
    )
    assert b'"prediction"' not in loaded.campaign_evidence.canonical_bytes()
    with zipfile.ZipFile(io.BytesIO(package.archive)) as zf:
        assert "canonical/campaign-evidence.json" in zf.namelist()


def test_canonical_project_package_carries_explicit_current_confirmation_state() -> None:
    """A project cannot silently omit whether protected confirmation occurred."""

    package = _package()
    loaded = CanonicalProjectPackage.from_archive(package.archive)

    assert loaded.confirmation_history.disposition == "not_requested"
    assert (
        loaded.confirmation_history.payload["campaign_id"]
        == loaded.campaign_evidence.payload["campaign"]["campaign_id"]
    )
    assert (
        loaded.project_payload["metadata"]["canonical_project"]["confirmation_history_digest"]
        == loaded.confirmation_history.content_digest
    )
    with zipfile.ZipFile(io.BytesIO(package.archive)) as zf:
        assert "canonical/confirmation-history.json" in zf.namelist()


def test_canonical_project_package_carries_a_bound_presentation_manifest() -> None:
    """Portable readout and future consent categories follow the admitted DAG."""

    package = _package()
    loaded = CanonicalProjectPackage.from_archive(package.archive)

    manifest = loaded.presentation_manifest
    assert manifest["schema_version"] == "spectrasherpa-portable-presentation-manifest/1"
    assert (
        manifest["manifest_digest"]
        == loaded.project_payload["metadata"]["canonical_project"]["presentation_manifest_digest"]
    )
    assert [node["node_id"] for node in manifest["nodes"]] == [
        node["node_id"] for node in loaded.application_plan.payload["nodes"]
    ]
    assert all(node["presentations"] for node in manifest["nodes"])
    with zipfile.ZipFile(io.BytesIO(package.archive)) as zf:
        assert json.loads(zf.read("canonical/presentation-manifest.json")) == manifest


def test_canonical_project_package_rejects_every_older_package_schema() -> None:
    """Historical package labels cannot select a partial scientific reader."""

    package = _package()
    with zipfile.ZipFile(io.BytesIO(package.archive)) as source:
        members = {name: source.read(name) for name in source.namelist() if name != "sherpa-object.json"}
    project = json.loads(members["project.json"])
    for schema in (
        "spectra-canonical-project-package/1",
        "spectra-canonical-project-package/2",
        "spectra-canonical-project-package/3",
        "spectra-canonical-project-package/4",
        "spectra-canonical-project-package/5",
    ):
        older = deepcopy(project)
        older["archive_format"]["schema"] = schema
        older["metadata"]["canonical_project"]["schema_version"] = schema
        members["project.json"] = json.dumps(older, sort_keys=True, separators=(",", ":")).encode()
        with pytest.raises(CanonicalProjectPackageError, match="schema is unsupported"):
            CanonicalProjectPackage.from_archive(_archive_with_new_manifest(members))


def test_current_package_rejects_a_nested_legacy_application_plan() -> None:
    """Outer package currency cannot make an unbound application plan current."""

    package = _package()
    with zipfile.ZipFile(io.BytesIO(package.archive)) as source:
        members = {name: source.read(name) for name in source.namelist() if name != "sherpa-object.json"}
    plan = json.loads(members["canonical/application-plan.json"])
    for node in plan["nodes"]:
        del node["application_contract_digest"]
    plan["schema_version"] = "spectra-canonical-application-plan/1"
    unsigned = {key: value for key, value in plan.items() if key != "application_plan_digest"}
    plan["application_plan_digest"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    members["canonical/application-plan.json"] = json.dumps(
        plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()

    with pytest.raises(CanonicalProjectPackageError, match="identities are invalid"):
        CanonicalProjectPackage.from_archive(_archive_with_new_manifest(members))


def test_canonical_project_package_rejects_a_valid_ledger_rebound_to_another_request() -> None:
    """A self-consistent campaign ledger cannot be substituted across packages."""

    package = _package()
    with zipfile.ZipFile(io.BytesIO(package.archive)) as source:
        members = {name: source.read(name) for name in source.namelist() if name != "sherpa-object.json"}

    ledger = json.loads(members["canonical/campaign-evidence.json"])
    ledger["candidates"][1]["request_digest"] = "9" * 64
    unsigned = {key: value for key, value in ledger.items() if key != "content_digest"}
    ledger["content_digest"] = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    members["canonical/campaign-evidence.json"] = json.dumps(
        ledger, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()

    with pytest.raises(CanonicalProjectPackageError, match="identities are invalid"):
        CanonicalProjectPackage.from_archive(_archive_with_new_manifest(members))


def test_canonical_project_package_rejects_a_rewritten_presentation_manifest() -> None:
    package = _package()
    with zipfile.ZipFile(io.BytesIO(package.archive)) as source:
        members = {name: source.read(name) for name in source.namelist() if name != "sherpa-object.json"}

    manifest = json.loads(members["canonical/presentation-manifest.json"])
    manifest["nodes"][0]["contract_digest"] = "f" * 64
    members["canonical/presentation-manifest.json"] = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()

    with pytest.raises(CanonicalProjectPackageError, match="presentation manifest differs"):
        CanonicalProjectPackage.from_archive(_archive_with_new_manifest(members))


def test_canonical_project_package_rejects_a_local_record_rebound_to_another_artifact() -> None:
    """A well-formed record cannot be substituted across package identities."""

    package = _package()
    with zipfile.ZipFile(io.BytesIO(package.archive)) as source:
        members = {name: source.read(name) for name in source.namelist() if name != "sherpa-object.json"}

    record = json.loads(members["canonical/local-model-record.json"])
    record["model"]["artifact_digest"] = "b" * 64
    record["model"]["model_identity"] = hashlib.sha256(
        json.dumps(
            {
                "schema_version": "spectra-model-identity/1",
                "family_id": record["model"]["family_id"],
                "artifact_digest": record["model"]["artifact_digest"],
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()
    ).hexdigest()
    unsigned_record = {key: value for key, value in record.items() if key != "record_digest"}
    record["record_digest"] = hashlib.sha256(
        json.dumps(unsigned_record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    members["canonical/local-model-record.json"] = json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()

    with pytest.raises(CanonicalProjectPackageError, match="identities are invalid"):
        CanonicalProjectPackage.from_archive(_archive_with_new_manifest(members))


def test_managed_project_package_rejects_nonreplayable_local_only_rubberband() -> None:
    """A local canvas operation cannot be promoted into portable managed evidence."""

    with pytest.raises(ValidationGraphError, match="local-only"):
        _package(include_local_only_rubberband=True)


def test_canonical_project_package_rejects_unlisted_or_swapped_member() -> None:
    package = _package()
    with zipfile.ZipFile(io.BytesIO(package.archive)) as source:
        members = {name: source.read(name) for name in source.namelist() if name != "sherpa-object.json"}

    members["canonical/extra.json"] = b"{}"
    tampered = _archive_with_new_manifest(members)
    with pytest.raises(CanonicalProjectPackageError, match="hash inventory|member inventory"):
        CanonicalProjectPackage.from_archive(tampered)

    members = {name: data for name, data in members.items() if name != "canonical/extra.json"}
    state_members = sorted(name for name in members if name.startswith("canonical/artifact/states/"))
    first, second = state_members
    members[first], members[second] = members[second], members[first]
    with pytest.raises(CanonicalProjectPackageError, match="identities are invalid"):
        CanonicalProjectPackage.from_archive(_archive_with_new_manifest(members))


def test_canonical_project_package_enforces_its_uncompressed_budget() -> None:
    package = _package()

    with pytest.raises(CanonicalProjectPackageError, match="archive is invalid"):
        CanonicalProjectPackage.from_archive(package.archive, max_uncompressed_bytes=1)


_CUSTODY_CONTRACTS = {
    "spectrasherpa.sherpa-plsda-state/3": "76adfad2282f7ea1a6ac883750d45f972706364fcc0b930bbaccefae2d3c3739",
    "spectrasherpa.model-artifact.simca/1": "ed4a72520c738fbecb4c60eea187649ad6fd903635c92ab8f38a7afe1e428199",
    "spectra.sherpa-simpls-regression-json/6": "ac05f06a069e5551f5cd101dbaec0d40ff352860b360a98e367e1f17dbbaf98d",
    "spectrasherpa.model-artifact.knn/1": "55e1151d097627dd0b54461e2eacca61b48438f1be6414efcf87455de5feb6d3",
}


def _custody_state_member(serializer: str, *, node_id: str = "candidate_model") -> dict[str, object]:
    return {
        "node_id": node_id,
        "state_digest": "1" * 64,
        "serializer": serializer,
        "contract_digest": _CUSTODY_CONTRACTS.get(serializer, "2" * 64),
        "candidate_node_digest": "3" * 64,
        "seed": None,
        "relative_path": f"states/{node_id}.json",
        "state_content_digest": "4" * 64,
    }


@pytest.mark.parametrize(
    "serializer",
    (
        "spectrasherpa.model-artifact.knn/1",
        "spectrasherpa.unknown-retains-all-rows/99",
    ),
)
def test_campaign_review_refuses_unsafe_or_unknown_fitted_state(serializer: str) -> None:
    from types import SimpleNamespace

    from spectra_sherpa.sdk import campaign_review

    application = SimpleNamespace(
        artifact=SimpleNamespace(payload={"state_members": [_custody_state_member(serializer)]})
    )
    with pytest.raises(CampaignReviewError, match="cannot claim data-free custody"):
        campaign_review._require_data_free_application(application)


@pytest.mark.parametrize(
    "serializer",
    (
        "spectrasherpa.sherpa-plsda-state/3",
        "spectrasherpa.model-artifact.simca/1",
        "spectra.sherpa-simpls-regression-json/6",
    ),
)
def test_campaign_review_admits_only_positive_data_free_capabilities(serializer: str) -> None:
    from types import SimpleNamespace

    from spectra_sherpa.sdk import campaign_review

    application = SimpleNamespace(
        artifact=SimpleNamespace(payload={"state_members": [_custody_state_member(serializer)]})
    )
    campaign_review._require_data_free_application(application)


def test_campaign_review_refuses_known_serializer_with_changed_contract() -> None:
    from types import SimpleNamespace

    from spectra_sherpa.sdk import campaign_review

    member = _custody_state_member("spectrasherpa.sherpa-plsda-state/3")
    member["contract_digest"] = "2" * 64
    application = SimpleNamespace(artifact=SimpleNamespace(payload={"state_members": [member]}))
    with pytest.raises(CampaignReviewError, match="cannot claim data-free custody"):
        campaign_review._require_data_free_application(application)


def test_campaign_review_refuses_mixed_data_free_and_reference_state() -> None:
    from types import SimpleNamespace

    from spectra_sherpa.sdk import campaign_review

    application = SimpleNamespace(
        artifact=SimpleNamespace(
            payload={
                "state_members": [
                    _custody_state_member("spectrasherpa.sherpa-plsda-state/3"),
                    _custody_state_member("spectrasherpa.model-artifact.knn/1", node_id="second_model"),
                ]
            }
        )
    )
    with pytest.raises(CampaignReviewError, match="cannot claim data-free custody"):
        campaign_review._require_data_free_application(application)


def test_campaign_review_central_directory_count_is_bounded_before_zipfile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spectra_sherpa.sdk import campaign_review

    attack = io.BytesIO()
    with zipfile.ZipFile(attack, "w", zipfile.ZIP_STORED) as output:
        for index in range(10_001):
            output.writestr(f"empty-{index:05d}", b"")
    raw = bytearray(attack.getvalue())
    eocd = raw.rfind(b"PK\x05\x06")
    assert eocd >= 0
    raw[eocd + 8 : eocd + 10] = (1).to_bytes(2, "little")
    raw[eocd + 10 : eocd + 12] = (1).to_bytes(2, "little")

    def zipfile_must_not_be_reached(*_args, **_kwargs):
        raise AssertionError("ZipFile reached before the independent directory census")

    monkeypatch.setattr(campaign_review.zipfile, "ZipFile", zipfile_must_not_be_reached)
    with pytest.raises(CampaignReviewError, match="archive is invalid"):
        CampaignReviewPackage.from_archive(bytes(raw), max_uncompressed_bytes=1024)


def _archive_with_new_manifest(members: dict[str, bytes]) -> bytes:
    """Rebuild a generic valid archive so canonical checks—not ZIP hashes—reject it."""

    from spectra_sherpa.app.services.sherpa_object import ArchiveMember, build_archive

    source = dict(members)
    project = json.loads(source.pop("project.json"))
    return build_archive(
        project_payload=project,
        members=[ArchiveMember(name, data) for name, data in source.items()],
        package_mode="full",
    )
