"""Scientific review projected onto the existing application-release authority."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from spectra_sherpa.sdk.prediction_uncertainty import _digest


class PromotionReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_digest: str = Field(pattern="^[a-f0-9]{64}$")
    intended_use: str = Field(min_length=1, max_length=2000)
    protocol: Literal["exploratory", "accepted_external_validation"] = "exploratory"
    rationale: str = Field(min_length=1, max_length=4000)

    @field_validator("intended_use", "rationale")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("intended use and rationale cannot be blank")
        return value.strip()


def build_promotion_review(
    model: Any, manifest: dict, arrays: dict, qualification: dict, *, retained_population: dict | None = None
) -> dict:
    """Caller verifies storage, access and current validation before projection."""
    from spectra_sherpa.app.services.application_release import _model_readiness
    from spectra_sherpa.sdk.saved_model_qualification import SavedModelApplicationPlan, _manifest_digest

    blockers = [x for x in _model_readiness(model)["blockers"] if x != "model is not marked deploy-ready"]
    count = None
    plan_digest = None
    limitations = [
        "Operational readiness is not an independent-validation or ASTM-conformity claim.",
        "Review reuses the frozen artifact; it does not fit additional development or held-out samples.",
    ]
    try:
        plan = SavedModelApplicationPlan.from_verified_snapshot(model, manifest, arrays)
        count = plan.training_specimen_count
        plan_digest = plan.application_plan_digest
    except (ValueError, KeyError, TypeError):
        limitations.append("Exact fitted specimen membership is unavailable for this artifact; do not infer counts.")
    data = {
        "schema_version": "spectrasherpa.model-promotion-review/1",
        "artifact_uid": model.artifact_uid,
        "artifact_digest": model.integrity_hash,
        "manifest_digest": _manifest_digest(manifest),
        "application_plan_digest": plan_digest,
        "workflow_id": model.workflow_id,
        "workflow_version_id": model.workflow_version_id,
        "source_run_id": model.source_run_id,
        "population": {
            "fitted_count": count,
            "held_out_count": None,
            "held_out_count_status": "not_recorded",
            **(retained_population or {}),
        },
        "qualification": qualification,
        "fitting_plan": {
            "state": (
                "complete_declared_development_fit"
                if (retained_population or {}).get("declared_development_count") == count and count is not None
                else "fitted_population_only"
            ),
            "declared_development_count": (retained_population or {}).get("declared_development_count"),
            "source_run_id": model.source_run_id,
            "recipe_changed": "not_assessed_current_workflow_is_mutable",
            "duplicate_fit_required": False,
            "changed_fit_action": "edit_workflow_then_explicit_run",
            "held_out_expansion": "never_automatic",
        },
        "reuse_existing_fitted_model": not blockers,
        "blockers": blockers,
        "limitations": limitations,
        "guidance": {
            "next_action": "Review the existing fitted model and its intended use.",
            "reason": (
                "A completed workflow may already have fitted all declared training samples. "
                "Refit only if the recipe or fitting population must change."
            ),
            "scientific_basis": (
                "CV supports development; separate validation evaluates the frozen calibration. "
                "ASTM E1655 §§15.3.6 and 18.1–18.3; a model update requires revalidation (§24.2)."
            ),
        },
    }
    return {**data, "review_digest": _digest(data)}


def confirm_promotion_review(review: dict, decision: PromotionReviewDecision) -> dict:
    if decision.review_digest != review["review_digest"]:
        raise ValueError("Model or evidence changed after review. Reopen Review for promotion.")
    if review["blockers"]:
        raise ValueError("; ".join(review["blockers"]))
    qualification = review["qualification"]
    if decision.protocol == "accepted_external_validation":
        if qualification.get("state") != "accepted_under_declared_policy":
            raise ValueError("This protocol requires a current accepted artifact-bound external-validation dossier.")
        if decision.intended_use != qualification.get("intended_use"):
            raise ValueError("Intended use differs from the accepted validation dossier. Review that policy first.")
    return {
        **decision.model_dump(),
        "artifact_uid": review["artifact_uid"],
        "artifact_digest": review["artifact_digest"],
        "manifest_digest": review["manifest_digest"],
        "population": review["population"],
        "qualification": qualification,
        "limitations": review["limitations"],
        "refitted": False,
    }


def retained_model_population(model: Any, manifest: dict, run: Any) -> dict:
    """Only expose split counts whose exact train membership belongs to this fitted artifact."""
    from spectra_sherpa.app.schemas.run_evidence import RunEvidence
    from spectra_sherpa.app.services.run_output_retention import read_output
    from spectra_sherpa.app.services.run_validation_summary import _split_summaries

    if run is None or run.id != model.source_run_id or run.user_id != model.user_id:
        return {}
    training = manifest.get("training_specimen_ids")
    if not isinstance(training, list) or not training or len(set(training)) != len(training):
        return {}
    evidence = RunEvidence.model_validate(run.evidence_completeness)
    if evidence.qualification != "qualified":
        return {}
    definition_receipt = evidence.outputs.get("__workflow__", {}).get("definition")
    if definition_receipt is None or definition_receipt.state != "exact" or definition_receipt.storage != "file":
        return {}
    definition = read_output(run.user_id, definition_receipt)
    ancestors = {model.node_id}
    for _ in range(len(definition.get("nodes", []))):
        ancestors.update(e["from_node_id"] for e in definition.get("edges", []) if e.get("to_node_id") in ancestors)
    verified = []
    for entry in _split_summaries(run, definition):
        if entry["node"] not in ancestors:
            continue
        receipt = evidence.outputs.get(entry["node"], {}).get("X_train")
        if receipt is None or receipt.state != "exact" or receipt.storage != "file":
            continue
        data = read_output(run.user_id, receipt)
        labels = (data.get("y_axis") or {}).get("labels")
        plan = entry["plan"]
        if labels != training or len(plan["train_indices"]) != len(training):
            continue
        verified.append(
            {
                "fitted_count": len(training),
                "declared_development_count": len(training),
                "held_out_count": len(plan["test_indices"]),
                "held_out_count_status": "verified_retained_split",
                "partition_digest": plan["digest"],
                "source_run_id": run.id,
                "limitations": ["Exclusion from this fit does not establish freedom from prior inspection."],
            }
        )
    return verified[0] if verified and all(item == verified[0] for item in verified) else {}


def canonical_fitted_state(binding: Any) -> dict:
    """Read the same frozen PLS state accepted by the canonical application executor."""
    from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import FittedPLSV2Node
    from spectra_sherpa.app.services.execution_runtime import build_application_execution_runtime

    plan = binding.canonical_application_plan
    node = next(node for node in plan["nodes"] if node["node_id"] == plan["model_node_id"])
    if node["application_operation_id"] != "model.apply_fitted_pls":
        raise ValueError("Fitted population is available for canonical PLS regression only")
    runtime = build_application_execution_runtime(canonical_artifact_read_grant=binding.canonical_read_grant)
    artifact = node["artifact_binding"]
    state = runtime.canonical_artifact_reader.load_bound_state(
        artifact,
        expected_source_contract_digest=artifact["source_contract_digest"],
        expected_serializer=artifact["serializer"],
    )
    return FittedPLSV2Node("promotion-state-validator", {}).validate_fitted_state(state)
