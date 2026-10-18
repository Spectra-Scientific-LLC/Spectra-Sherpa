from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from spectra_sherpa.app.services.model_outlier_challenge import summarize_challenge
from spectra_sherpa.app.services.model_promotion_review import (
    PromotionReviewDecision,
    build_promotion_review,
    confirm_promotion_review,
)


def review(qualification=None):
    model = SimpleNamespace(
        model_type="pca",
        project_id=1,
        workflow_id=2,
        workflow_version_id=3,
        source_run_id=4,
        is_active=True,
        is_deploy_ready=False,
        artifact_uid="m1",
        integrity_hash="a" * 64,
    )
    return build_promotion_review(model, {"model_type": "pca"}, {}, qualification or {"state": "unavailable"})


def decision(current, **values):
    return PromotionReviewDecision(
        review_digest=current["review_digest"],
        intended_use="screening",
        rationale="Exploratory instrument check",
        **values,
    )


def test_exact_review_reuses_artifact_without_fabricating_population():
    current = review()
    assert current["population"]["fitted_count"] is None
    assert current["population"]["held_out_count"] is None
    result = confirm_promotion_review(current, decision(current))
    assert result["artifact_digest"] == "a" * 64
    assert result["refitted"] is False
    assert result["protocol"] == "exploratory"


def test_evidence_changes_invalidate_previously_reviewed_snapshot():
    old = review()
    changed = review({"state": "rejected", "reason": "validation failed"})
    with pytest.raises(ValueError, match="changed after review"):
        confirm_promotion_review(changed, decision(old))


def test_external_protocol_cannot_be_granted_by_operational_boolean_or_declared_label():
    current = review()
    with pytest.raises(ValueError, match="current accepted"):
        confirm_promotion_review(current, decision(current, protocol="accepted_external_validation"))
    accepted = review({"state": "accepted_under_declared_policy", "intended_use": "different purpose"})
    with pytest.raises(ValueError, match="Intended use differs"):
        confirm_promotion_review(accepted, decision(accepted, protocol="accepted_external_validation"))
    matching = review({"state": "accepted_under_declared_policy", "intended_use": "screening"})
    assert (
        confirm_promotion_review(matching, decision(matching, protocol="accepted_external_validation"))["protocol"]
        == "accepted_external_validation"
    )


def test_blank_decision_is_not_review():
    with pytest.raises(ValidationError):
        PromotionReviewDecision(review_digest="a" * 64, intended_use=" ", rationale="reason")


def test_challenge_keeps_misses_unavailable_and_errors_separate():
    applied = {
        "predictions": [[1.0], [2.0], [3.0]],
        "metrics": {"rmse": 4.0},
        "applicability": {
            "t2_limit": 3.0,
            "rows": [
                {"row_index": i, "screening_status": status}
                for i, status in enumerate(["outside_global_screen", "within_global_screen", "unavailable"])
            ],
        },
    }
    result = summarize_challenge(
        applied, ["x", "y", "z"], outlier_type="matrix", label_basis="independent laboratory labels"
    )
    assert (result["detected"], result["missed"], result["unavailable"]) == (1, 1, 1)
    assert result["detection_fraction"] == 1 / 3
    assert result["ordinary_validation_rmsep"] is None
    assert result["false_alarm_rate"] is None
    assert result["challenge_prediction_metrics"] == {"rmse": 4.0}
    assert result["rows"][1]["specimen_id"] == "y"
    applied["applicability"]["rows"][1]["row_index"] = 9
    with pytest.raises(ValueError, match="order"):
        summarize_challenge(applied, ["x", "y", "z"], outlier_type="matrix", label_basis="lab")


def test_population_counts_require_matching_fitted_membership_and_graph(monkeypatch):
    import spectra_sherpa.app.services.run_output_retention as retention
    import spectra_sherpa.app.services.run_validation_summary as summaries
    from spectra_sherpa.app.services.model_promotion_review import retained_model_population

    definition = {
        "nodes": [{"node_id": "split"}, {"node_id": "fit"}],
        "edges": [{"from_node_id": "split", "to_node_id": "fit"}],
    }
    receipt = {"state": "exact", "storage": "file", "sha256": "a" * 64, "byte_count": 10, "format_version": 1}
    data_receipt = {**receipt, "sha256": "b" * 64}
    run = SimpleNamespace(
        id=4,
        user_id=5,
        evidence_completeness={
            "qualification": "qualified",
            "outputs": {"__workflow__": {"definition": receipt}, "split": {"X_train": data_receipt}},
        },
    )
    model = SimpleNamespace(source_run_id=4, user_id=5, node_id="fit")
    dataset = {"y_axis": {"labels": ["a", "b"]}}
    monkeypatch.setattr(
        retention, "read_output", lambda _user, item: definition if item.sha256 == "a" * 64 else dataset
    )
    monkeypatch.setattr(
        summaries,
        "_split_summaries",
        lambda _run, _graph: [
            {"node": "split", "plan": {"train_indices": [0, 1], "test_indices": [2], "digest": "c" * 64}}
        ],
    )
    assert retained_model_population(model, {"training_specimen_ids": ["a", "b"]}, run)["held_out_count"] == 1
    assert retained_model_population(model, {"training_specimen_ids": ["x", "y"]}, run) == {}
    definition["edges"] = []
    assert retained_model_population(model, {"training_specimen_ids": ["a", "b"]}, run) == {}


def test_full_development_fit_requires_retained_population_proof(monkeypatch):
    from spectra_sherpa.sdk.saved_model_qualification import SavedModelApplicationPlan

    monkeypatch.setattr(
        SavedModelApplicationPlan,
        "from_verified_snapshot",
        lambda *args: SimpleNamespace(training_specimen_count=174, application_plan_digest="b" * 64),
    )
    model = SimpleNamespace(
        model_type="pca",
        project_id=1,
        workflow_id=2,
        workflow_version_id=3,
        source_run_id=4,
        is_active=True,
        is_deploy_ready=False,
        artifact_uid="m1",
        integrity_hash="a" * 64,
    )
    unknown = build_promotion_review(model, {}, {}, {"state": "unavailable"})
    assert unknown["fitting_plan"]["state"] == "fitted_population_only"
    verified = build_promotion_review(
        model,
        {},
        {},
        {"state": "unavailable"},
        retained_population={
            "fitted_count": 174,
            "declared_development_count": 174,
            "held_out_count": 57,
            "held_out_count_status": "verified_retained_split",
            "partition_digest": "c" * 64,
        },
    )
    assert verified["fitting_plan"]["state"] == "complete_declared_development_fit"
    assert verified["population"]["held_out_count"] == 57
    assert verified["fitting_plan"]["duplicate_fit_required"] is False
    assert verified["fitting_plan"]["held_out_expansion"] == "never_automatic"
    assert verified["review_digest"] != unknown["review_digest"]
