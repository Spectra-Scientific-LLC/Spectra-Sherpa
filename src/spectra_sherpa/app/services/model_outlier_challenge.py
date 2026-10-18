"""Optional declared-outlier challenge of an exact native saved PLS pipeline."""

from __future__ import annotations

from asyncio import to_thread
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from spectra_sherpa.app.services.model_application import VerifiedModelSnapshot, apply_model_to_dataset
from spectra_sherpa.app.services.model_store import get_model_store, verify_model_artifact_storage_record
from spectra_sherpa.sdk.prediction_uncertainty import _specimen_ids
from spectra_sherpa.sdk.saved_model_qualification import SavedModelApplicationPlan


class OutlierChallengeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_view_id: int = Field(gt=0)
    outlier_type: str = Field(min_length=1, max_length=200)
    label_basis: str = Field(min_length=1, max_length=4000)
    labels_independent_of_detector: Literal[True]


def summarize_challenge(applied: dict, specimen_ids: list[str], *, outlier_type: str, label_basis: str) -> dict:
    screening = applied.get("applicability") or {}
    rows = screening.get("rows", [])
    if len(rows) != len(specimen_ids) or not rows:
        raise ValueError("Frozen model has no complete per-specimen screening evidence")
    statuses = {"outside_global_screen": "detected", "within_global_screen": "missed", "unavailable": "unavailable"}
    predictions = applied.get("predictions")
    if predictions is None or len(predictions) != len(rows):
        raise ValueError("Challenge predictions are incomplete")
    presented = []
    for index, (specimen, row) in enumerate(zip(specimen_ids, rows)):
        if row.get("row_index") != index or row.get("screening_status") not in statuses:
            raise ValueError("Challenge screening order or status is invalid")
        presented.append(
            {
                **row,
                "specimen_id": specimen,
                "outcome": statuses[row["screening_status"]],
                "prediction": predictions[index],
            }
        )
    counts = {outcome: sum(row["outcome"] == outcome for row in presented) for outcome in statuses.values()}
    return {
        "source_count": len(rows),
        "evaluated_count": len(rows),
        "excluded_count": 0,
        **counts,
        "detection_fraction": counts["detected"] / len(rows),
        "outlier_type": outlier_type,
        "label_basis": label_basis,
        "label_authority": "user_declared_independently_of_this_detector",
        "screening": {key: value for key, value in screening.items() if key not in {"rows", "prediction_identity"}},
        "rows": presented,
        "challenge_prediction_metrics": applied.get("metrics"),
        "ordinary_validation_rmsep": None,
        "false_alarm_rate": None,
        "claim_scope": "exploratory_declared_outlier_challenge",
        "limitations": [
            "Declared labels are not independently verified by Sherpa. Detector flags are not truth labels.",
            "Unavailable screening is neither detection nor a pass; all rows remain in the denominator.",
            "Challenge errors are separate from ordinary validation RMSEP; "
            "false alarms need a declared in-domain cohort.",
            "Using these results to tune the model or thresholds makes this development evidence.",
        ],
    }


async def assess_outlier_challenge(
    model: Any, dataset: Any, *, outlier_type: str, label_basis: str
) -> tuple[dict, SavedModelApplicationPlan]:
    if dataset.sample_axis is None or dataset.sample_axis.labels is None:
        raise ValueError("Challenge requires explicit unique specimen IDs")
    ids = _specimen_ids(list(dataset.sample_axis.labels), len(dataset.X))
    if len(ids) > 8192:
        raise ValueError("Challenge exceeds the retained specimen limit (8192)")
    for axis in (dataset.sample_axis, dataset.feature_axis):
        if axis is not None and axis.include_mask is not None and not np.all(axis.include_mask):
            raise ValueError("Materialize the named challenge selection before assessment")
    await to_thread(verify_model_artifact_storage_record, model)
    manifest, arrays = await to_thread(get_model_store().load, model.artifact_uid, verify=True)
    plan = SavedModelApplicationPlan.from_verified_snapshot(model, manifest, arrays)
    if set(ids) & set(manifest["training_specimen_ids"]):
        raise ValueError("Challenge specimens overlap fitted model specimens")
    applied = await apply_model_to_dataset(
        model.artifact_uid,
        dataset,
        scope="all",
        verified_snapshot=VerifiedModelSnapshot(model.artifact_uid, manifest, arrays),
    )
    result = summarize_challenge(applied, ids, outlier_type=outlier_type, label_basis=label_basis)
    result.update(
        schema_version="spectrasherpa.outlier-challenge/1",
        artifact_uid=model.artifact_uid,
        artifact_digest=plan.artifact_digest,
        application_plan_digest=plan.application_plan_digest,
        cohort_digest=dataset.scientific_digest,
    )
    return result, plan


async def assess_canonical_outlier_challenge(
    binding: Any, dataset: Any, *, outlier_type: str, label_basis: str
) -> dict:
    """Execute the imported frozen pipeline using the same screening summary as native models."""
    from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import _response_identity
    from spectra_sherpa.app.services.execution_runtime import build_application_execution_runtime
    from spectra_sherpa.app.services.model_promotion_review import canonical_fitted_state
    from spectra_sherpa.sdk.canonical_application import CanonicalApplicationPlan
    from spectra_sherpa.sdk.canonical_application_execution import execute_canonical_application
    from spectra_sherpa.sdk.validate import metrics

    if dataset.sample_axis is None or dataset.sample_axis.labels is None:
        raise ValueError("Challenge requires explicit unique specimen IDs")
    ids = _specimen_ids(list(dataset.sample_axis.labels), len(dataset.X))
    if len(ids) > 8192:
        raise ValueError("Challenge exceeds the retained specimen limit (8192)")
    for axis in (dataset.sample_axis, dataset.feature_axis):
        if axis is not None and axis.include_mask is not None and not np.all(axis.include_mask):
            raise ValueError("Materialize the named challenge selection before assessment")
    state = await to_thread(canonical_fitted_state, binding)
    plan = CanonicalApplicationPlan.from_dict(binding.canonical_application_plan)
    runtime = build_application_execution_runtime(canonical_artifact_read_grant=binding.canonical_read_grant)
    executed = await execute_canonical_application(plan, dataset, runtime=runtime)
    output = executed.results[plan.payload["model_node_id"]]
    predictions = np.asarray(output["default"], dtype=float)
    screening = output["applicability"]
    if screening.get("prediction_identity") != output.get("prediction_identity"):
        raise ValueError("Challenge screening is not bound to the exact predictions")
    errors = None
    if dataset.target is not None:
        observed = np.asarray(dataset.target, dtype=float)
        if observed.ndim == 1:
            observed = observed[:, None]
        if predictions.ndim == 1:
            predictions = predictions[:, None]
        identity = _response_identity(dataset, targets=observed.shape[1], bound_names=[], embedded=True)
        if identity != state["response_identity"] or observed.shape != predictions.shape:
            raise ValueError("Challenge reference identity or units differ from the frozen model")
        if not np.isfinite(observed).all():
            raise ValueError("Challenge references must be complete or omitted; no rows are silently excluded")
        errors = [metrics(observed[:, i], predictions[:, i]).as_dict() for i in range(observed.shape[1])]
    result = summarize_challenge(
        {"predictions": predictions.tolist(), "applicability": screening, "metrics": errors},
        ids,
        outlier_type=outlier_type,
        label_basis=label_basis,
    )
    result.update(
        schema_version="spectrasherpa.outlier-challenge/1",
        canonical_artifact_id=binding.canonical_artifact_id,
        artifact_digest=plan.payload["artifact_digest"],
        application_plan_digest=plan.application_plan_digest,
        cohort_digest=dataset.scientific_digest,
        fitted_count=state["reference_samples"],
        fit_overlap_status="unknown_export_has_no_fitting_specimen_register",
    )
    result["limitations"].append(
        "The imported data-free artifact has no fitting specimen register; "
        "this check cannot verify cohort separation or independent sampling."
    )
    return result
