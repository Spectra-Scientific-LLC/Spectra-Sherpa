"""Executed, model-bound E1655 assessment for a frozen native PLS artifact."""

from __future__ import annotations

from asyncio import to_thread
from copy import deepcopy
from typing import Any

import numpy as np

from spectra_sherpa.app.services.model_application import VerifiedModelSnapshot, apply_model_to_dataset
from spectra_sherpa.app.services.model_store import get_model_store, verify_model_artifact_storage_record
from spectra_sherpa.sdk.analytical_qualification import (
    QualificationContext,
    QualificationDossier,
    QualificationPolicy,
    assess_native_validation,
)
from spectra_sherpa.sdk.prediction_uncertainty import _digest, _specimen_ids
from spectra_sherpa.sdk.saved_model_qualification import SavedModelApplicationPlan
from spectra_sherpa.sdk.validation_independence import IndependenceEvidence, RecordedPopulation


async def assess_saved_model(
    model: Any,
    dataset: Any,
    *,
    validation_experiment_id: int,
    validation_view_digest: str,
    validation_source_manifest_digest: str,
    policy: QualificationPolicy,
    context: QualificationContext,
    independence_evidence: dict[str, Any] | None = None,
) -> tuple[QualificationDossier, SavedModelApplicationPlan]:
    """Evaluate one external cohort through one verified, pinned native snapshot."""

    if model.training_dataset_id is None or model.training_dataset_id == validation_experiment_id:
        raise ValueError("qualification requires a distinct retained external dataset source")
    if context.evaluation_role != "external_validation":
        raise ValueError("saved-model qualification currently requires external validation")
    if dataset.target is None:
        raise ValueError("qualification dataset has no reference responses")
    for axis in (dataset.sample_axis, dataset.feature_axis):
        if axis is not None and axis.include_mask is not None and not np.all(axis.include_mask):
            raise ValueError("materialize and record sample/feature exclusions before qualification")
    if dataset.sample_axis is None or dataset.sample_axis.labels is None:
        raise ValueError("qualification requires explicit specimen IDs")
    ids = _specimen_ids(list(dataset.sample_axis.labels), len(dataset.X))
    if len(ids) > 8192 or len(str(ids).encode("utf-8")) > 131072:
        raise ValueError("validation specimen register exceeds qualification evidence size limit")
    from spectra_sherpa.app.services.model_application import _target_for_artifact

    await to_thread(verify_model_artifact_storage_record, model)
    manifest, arrays = await to_thread(get_model_store().load, model.artifact_uid, verify=True)
    plan = SavedModelApplicationPlan.from_verified_snapshot(model, manifest, arrays)
    training_ids = manifest["training_specimen_ids"]
    if set(ids) & set(training_ids):
        raise ValueError("external validation specimens overlap fitted model specimens")
    observed, _warnings, target_metadata = _target_for_artifact(dataset, manifest)
    if observed is None:
        raise ValueError("qualification target does not match the saved response authority")
    observed = np.asarray(observed, dtype=float)
    from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import _response_identity

    reference_source = dataset.copy()
    if target_metadata.get("selected_target"):
        reference_source.target_context = reference_source.target_context.model_copy(
            update={"selected_target": target_metadata["selected_target"]}
        )
    reference_identity = _response_identity(
        reference_source,
        targets=1 if observed.ndim == 1 else observed.shape[1],
        bound_names=[],
        embedded=True,
    )
    if (
        reference_identity != manifest.get("response_identity")
        or reference_identity != context.reference_method.response_identity.model_dump()
    ):
        raise ValueError("external validation reference identity or units differ from saved model and declared method")
    if not np.isfinite(observed).all():
        raise ValueError("qualification references must be finite and complete")
    if not np.isfinite(np.asarray(dataset.X, dtype=float)).all():
        raise ValueError("qualification predictors must be finite")
    original_cohort_digest = dataset.scientific_digest
    evidence: dict[str, Any] = {}
    applied = await apply_model_to_dataset(
        model.artifact_uid,
        dataset,
        scope="all",
        execution_evidence=evidence,
        verified_snapshot=VerifiedModelSnapshot(model.artifact_uid, manifest, arrays),
    )
    output = evidence.get("outputs", {}).get("application-model-artifact")
    if not isinstance(output, dict):
        raise ValueError("exact native saved-model execution receipt is unavailable")
    predictions = np.asarray(output.get("default"), dtype=float)
    if not np.array_equal(predictions, np.asarray(applied.get("predictions"), dtype=float)):
        raise ValueError("presented saved-model predictions differ from executed values")
    identity = deepcopy(output.get("prediction_identity"))
    screening = deepcopy(output.get("applicability"))
    if not isinstance(identity, dict) or not isinstance(screening, dict):
        raise ValueError("exact saved PLS prediction and screening receipts are unavailable")
    if screening.get("prediction_identity") != identity:
        raise ValueError("saved PLS screening does not bind to the executed predictions")
    intervals = deepcopy(output.get("prediction_intervals"))
    if isinstance(intervals, dict) and intervals.get("status") != "point_only":
        if intervals.get("prediction_identity") != identity:
            raise ValueError("saved PLS intervals do not bind to the executed predictions")
    identity["saved_model_binding"] = {
        "artifact_uid": plan.artifact_uid,
        "artifact_digest": plan.artifact_digest,
        "manifest_digest": plan.manifest_digest,
        "application_plan_digest": plan.application_plan_digest,
    }
    screening["prediction_identity"] = identity
    if isinstance(intervals, dict) and intervals.get("status") != "point_only":
        intervals["prediction_identity"] = identity
    supplied = IndependenceEvidence.model_validate(
        independence_evidence or {"schema_version": "spectrasherpa.recorded-independence/1", "populations": []}
    )
    if any(population.role == "fit" for population in supplied.populations):
        raise ValueError("fitted specimen identities come from the verified saved artifact")
    fit = RecordedPopulation(
        role="fit",
        namespace=context.specimen_namespace,
        specimen_ids=list(training_ids),
        source_description=f"verified saved model {model.artifact_uid}, manifest {plan.manifest_digest}",
    )
    independence = supplied.model_copy(update={"populations": [fit, *supplied.populations]})
    dossier = await to_thread(
        assess_native_validation,
        plan=plan,
        observed=observed,
        predictions=predictions,
        prediction_identity=identity,
        screening=screening,
        effective_components=plan.effective_components,
        policy=policy,
        context=context,
        cohort_digest=original_cohort_digest,
        specimen_ids=ids,
        source_rows=len(ids),
        excluded_rows=0,
        original_cohort_digest=original_cohort_digest,
        exclusions=[],
        intervals=intervals,
        evidence_links=[
            f"saved-model-artifact:{model.artifact_uid}:{plan.artifact_digest}",
            f"saved-model-manifest-sha256:{plan.manifest_digest}",
            f"validation-view-receipt-sha256:{validation_view_digest}",
            f"validation-source-manifest-sha256:{validation_source_manifest_digest}",
        ],
        independence_evidence=independence.model_dump(mode="json"),
    )
    # The retained API later reloads this exact record. Refuse oversize evidence
    # before persistence rather than creating an assessment that cannot be read.
    QualificationDossier.load(dossier.canonical_bytes())
    return dossier, plan


def verify_validation_cohort(dossier: QualificationDossier, dataset: Any) -> None:
    """Recheck the materialized cohort, not merely its saved selection receipt."""

    if dataset.sample_axis is None or dataset.sample_axis.labels is None:
        raise ValueError("validation specimen identities are unavailable")
    ids = _specimen_ids(list(dataset.sample_axis.labels), len(dataset.X))
    identity = _digest({"namespace": dossier.context.specimen_namespace, "ids": ids})
    if dataset.scientific_digest != dossier.original_cohort_digest or identity != dossier.specimen_identity_digest:
        raise ValueError("validation cohort or specimen identities changed after assessment")


def qualification_status(
    model: Any,
    manifest: dict[str, Any],
    arrays: dict[str, np.ndarray],
    records: list[Any],
    view: Any | None,
    *,
    selected_view_digest: str | None = None,
    selection_present: bool = False,
    source_verified: bool | None = None,
    current_dataset: Any | None = None,
) -> dict[str, Any]:
    """Project one current dossier without promoting a calculated score."""

    assessments = [row for row in records if row.kind == "assessment"]
    if not assessments:
        return {"state": "unavailable", "reason": "No E1655 assessment is bound to this exact saved model."}
    latest = max(assessments, key=lambda row: row.id)
    try:
        dossier = QualificationDossier.load(latest.payload["dossier"])
        plan = SavedModelApplicationPlan.from_verified_snapshot(model, manifest, arrays)
        stored_plan = SavedModelApplicationPlan.model_validate(latest.payload["plan"])
    except (ValueError, TypeError, KeyError):
        return {"state": "stale", "reason": "Saved model or qualification evidence no longer verifies."}
    if (
        latest.record_digest != dossier.record_digest
        or stored_plan != plan
        or latest.model_integrity_hash != plan.artifact_digest
        or latest.manifest_digest != plan.manifest_digest
        or latest.application_plan_digest != plan.application_plan_digest
        or dossier.artifact_digest != plan.artifact_digest
        or dossier.application_plan_digest != plan.application_plan_digest
        or dossier.terminal_state_digest != plan.state_content_digest
        or view is None
        or view.id != latest.validation_view_id
        or view.deleted_at is not None
        or view.selection_sha256 != latest.validation_view_digest
        or f"validation-view-receipt-sha256:{latest.validation_view_digest}" not in dossier.evidence_links
    ):
        return {"state": "stale", "reason": "Model or validation dataset view changed after assessment."}
    if source_verified is False:
        return {"state": "stale", "reason": "Validation source no longer matches its recorded view."}
    if source_verified is None:
        return {
            "state": "current_source_unverified",
            "reason": "Validation source must be rechecked before current qualification is shown.",
        }
    try:
        if current_dataset is None:
            raise ValueError("validation cohort was not materialized")
        verify_validation_cohort(dossier, current_dataset)
    except (ValueError, TypeError):
        return {"state": "stale", "reason": "Validation cohort or specimen identities changed after assessment."}
    from spectra_sherpa.app.lib.dataset_view_receipts import receipt_sha256

    if receipt_sha256(view.selection) != view.selection_sha256:
        return {"state": "stale", "reason": "Validation dataset view receipt no longer verifies."}
    from spectra_sherpa.app.services.dataset_use import dossier_dataset_use

    binding = {
        "dataset_use": dossier_dataset_use(dossier),
        "independence": dossier.calculation.get("independence"),
        "dossier_digest": dossier.record_digest,
        "assessment": dossier.assessment,
        "intended_population": dossier.context.intended_population,
        "intended_use": dossier.context.intended_use,
        "policy_name": dossier.policy.policy_name,
        "policy_version": dossier.policy.policy_version,
        "validation_view_id": latest.validation_view_id,
        "validation_view_digest": latest.validation_view_digest,
        "application_plan_digest": plan.application_plan_digest,
        "evidence_links": dossier.evidence_links,
        "limitations": dossier.limitations,
        "external_validation": {
            "cohort_digest": dossier.cohort_digest,
            "specimen_identity_digest": dossier.specimen_identity_digest,
            "count": dossier.calculation["complete_rows"],
            "responses": [item["metrics"] for item in dossier.calculation["responses"]],
            "reference_method": dossier.context.reference_method.model_dump(mode="json"),
            "interval_coverage": (
                dossier.calculation["intervals"]["observed_coverage_among_available"]
                if dossier.calculation["intervals"] is not None
                else None
            ),
            "interval_available_rows": (
                dossier.calculation["intervals"]["available_rows"]
                if dossier.calculation["intervals"] is not None
                else None
            ),
        },
    }
    if selection_present and selected_view_digest != latest.validation_view_digest:
        return {
            **binding,
            "state": "stale_for_selected_dataset",
            "reason": "The selected project dataset differs from this assessed validation view.",
        }
    decisions = [row for row in records if row.kind == "decision" and row.parent_digest == dossier.record_digest]
    if decisions:
        from spectra_sherpa.sdk.analytical_qualification import QualificationDecision

        decision = QualificationDecision.model_validate(max(decisions, key=lambda row: row.id).payload["decision"])
        if max(decisions, key=lambda row: row.id).record_digest != decision.decision_digest:
            return {"state": "stale", "reason": "Human decision digest no longer verifies."}
        if decision.dossier_digest != dossier.record_digest:
            return {"state": "stale", "reason": "Human decision no longer binds to this assessment."}
        if decision.decision == "accepted_under_declared_policy" and dossier.assessment == "criteria_met":
            return {**binding, "state": "accepted_under_declared_policy", "decision_digest": decision.decision_digest}
        return {**binding, "state": decision.decision, "decision_digest": decision.decision_digest}
    return {**binding, "state": "awaiting_review" if dossier.assessment == "criteria_met" else dossier.assessment}
