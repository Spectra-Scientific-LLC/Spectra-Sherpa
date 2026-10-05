"""OSS verification tests for current sample-free confirmation evidence."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import numpy as np
import pytest

from spectra_sherpa.sdk.canonical_confirmation import (
    CANONICAL_CONFIRMATION_EVIDENCE_VERSION,
    SIMCA_CONFIRMATION_EVIDENCE_VERSION,
    SIMCA_CONFIRMATION_PLAN_VERSION,
    CanonicalConfirmationError,
    CanonicalConfirmationEvidence,
    CanonicalConfirmationPlan,
)


def _evidence() -> CanonicalConfirmationEvidence:
    return CanonicalConfirmationEvidence.build(
        request_digest="1" * 64,
        graph_digest="2" * 64,
        selected_validation_request_digest="3" * 64,
        winner_refit_authority_digest="4" * 64,
        artifact_digest="5" * 64,
        application_plan_digest="6" * 64,
        capability_content_digest="7" * 64,
        capability_envelope_digest="8" * 64,
        dataset_ref_digest="9" * 64,
        split_plan_digest="a" * 64,
        observed=np.array([1.0, 2.0, 3.0, 4.0]),
        predicted=np.array([0.9, 2.2, 2.8, 4.1]),
        groups=np.array(["a", "a", "b", "b"]),
        plan=CanonicalConfirmationPlan(100, 0.95, 42),
    )


def test_confirmation_plan_and_evidence_are_closed_sample_free_and_reproducible() -> None:
    plan = CanonicalConfirmationPlan(100, 0.95, 42)
    assert CanonicalConfirmationPlan.from_dict(plan.as_dict()) == plan

    evidence = _evidence()
    restored = CanonicalConfirmationEvidence.from_dict(evidence.as_dict())

    assert restored == evidence
    assert evidence.payload["schema_version"] == CANONICAL_CONFIRMATION_EVIDENCE_VERSION
    assert evidence.payload["metrics"]["n_samples"] == 4
    assert evidence.payload["uncertainty"]["grouped"] is True
    serialized = repr(evidence.as_dict()).lower()
    for forbidden in ("observed", "predicted", "spectrum", "sample_id", "group_codes"):
        assert forbidden not in serialized


def test_confirmation_plan_replays_frozen_regression_v2() -> None:
    legacy = CanonicalConfirmationPlan(100, 0.95, 42).as_dict()
    legacy["schema_version"] = "spectra-canonical-confirmation-plan/2"
    legacy.pop("task_type")

    restored = CanonicalConfirmationPlan.from_dict(legacy)

    assert restored.task_type == "regression"
    assert restored.schema_version == "spectra-canonical-confirmation-plan/2"
    assert restored.as_dict() == legacy
    assert (
        restored.digest
        == hashlib.sha256(
            json.dumps(legacy, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode(
                "utf-8"
            )
        ).hexdigest()
    )


def test_classification_confirmation_is_sample_free_reproducible_and_task_bound() -> None:
    plan = CanonicalConfirmationPlan(100, 0.95, 42, task_type="classification")
    assert CanonicalConfirmationPlan.from_dict(plan.as_dict()) == plan

    evidence = CanonicalConfirmationEvidence.build(
        request_digest="1" * 64,
        graph_digest="2" * 64,
        selected_validation_request_digest="3" * 64,
        winner_refit_authority_digest="4" * 64,
        artifact_digest="5" * 64,
        application_plan_digest="6" * 64,
        capability_content_digest="7" * 64,
        capability_envelope_digest="8" * 64,
        dataset_ref_digest="9" * 64,
        split_plan_digest="a" * 64,
        observed=np.array(["apple", "apple", "pear", "pear"], dtype=object),
        predicted=np.array(["apple", "pear", "pear", "pear"], dtype=object),
        groups=np.array(["batch-a", "batch-a", "batch-b", "batch-b"], dtype=object),
        plan=plan,
    )
    restored = CanonicalConfirmationEvidence.from_dict(evidence.as_dict())

    assert restored == evidence
    assert evidence.payload["task_type"] == "classification"
    assert evidence.payload["metrics"]["task_type"] == "classification"
    assert evidence.payload["metrics"]["labels"] == ["apple", "pear"]
    assert evidence.payload["metrics"]["balanced_accuracy"] == pytest.approx(0.75)
    assert set(evidence.payload["uncertainty"]) == {
        "registry_version",
        "confidence_level",
        "n_resamples",
        "grouped",
        "accuracy",
        "balanced_accuracy",
        "macro_f1",
        "mcc",
    }
    serialized = repr(evidence.as_dict()).lower()
    for forbidden in ("batch-a", "batch-b", "observed", "predicted"):
        assert forbidden not in serialized


def test_simca_confirmation_preserves_acceptance_objective_without_sample_egress() -> None:
    plan = CanonicalConfirmationPlan.for_validation(
        100, 0.95, 42, task_type="classification", primary_metric="mean_class_acceptance_sensitivity"
    )
    assert plan.schema_version == SIMCA_CONFIRMATION_PLAN_VERSION
    assert CanonicalConfirmationPlan.from_dict(plan.as_dict()) == plan
    assert plan.as_dict()["reported_metrics"] == [
        "mean_class_acceptance_sensitivity",
        "unassigned_rate",
        "multiple_acceptance_rate",
    ]
    assert plan.as_dict()["uncertainty"]["method_version"] == "2"
    assert (
        CanonicalConfirmationPlan(100, 0.95, 42, task_type="classification").as_dict()["uncertainty"]["method_version"]
        == "1"
    )
    kwargs = {
        "request_digest": "1" * 64,
        "graph_digest": "2" * 64,
        "selected_validation_request_digest": "3" * 64,
        "winner_refit_authority_digest": "4" * 64,
        "artifact_digest": "5" * 64,
        "application_plan_digest": "6" * 64,
        "capability_content_digest": "7" * 64,
        "capability_envelope_digest": "8" * 64,
        "dataset_ref_digest": "9" * 64,
        "split_plan_digest": "a" * 64,
        "observed": ["A", "A", "B", "B"],
        "predicted": ["B", "A", "B", "unassigned"],
        "groups": ["batch-a", "batch-a", "batch-b", "batch-b"],
        "plan": plan,
        "simca_membership": np.asarray([[True, True], [True, False], [False, True], [False, False]]),
        "simca_labels": ("A", "B"),
    }
    evidence = CanonicalConfirmationEvidence.build(**kwargs)
    assert CanonicalConfirmationEvidence.from_dict(evidence.as_dict()) == evidence
    assert evidence.payload["schema_version"] == SIMCA_CONFIRMATION_EVIDENCE_VERSION
    assert evidence.payload["metrics"]["balanced_accuracy"] == 0.5
    assert evidence.payload["metrics"]["mean_class_acceptance_sensitivity"] == 0.75
    assert evidence.payload["metrics"]["simca_acceptance"]["class_acceptance_specificity"] is None
    assert set(evidence.payload["uncertainty"]) == {
        "registry_version",
        "confidence_level",
        "n_resamples",
        "grouped",
        "mean_class_acceptance_sensitivity",
        "unassigned_rate",
        "multiple_acceptance_rate",
    }
    assert "batch-a" not in repr(evidence.as_dict())
    with pytest.raises(CanonicalConfirmationError, match="acceptance evidence"):
        CanonicalConfirmationEvidence.build(**{**kwargs, "simca_membership": None})
    with pytest.raises(CanonicalConfirmationError, match="acceptance evidence"):
        CanonicalConfirmationEvidence.build(
            **{**kwargs, "plan": CanonicalConfirmationPlan(100, 0.95, 42, task_type="classification")}
        )
    fully_assigned = CanonicalConfirmationEvidence.build(
        **{
            **kwargs,
            "predicted": ["A", "A", "B", "B"],
            "simca_membership": np.asarray([[True, False], [True, False], [False, True], [False, True]]),
        }
    )
    assert fully_assigned.payload["metrics"]["labels"] == ["A", "B", "unassigned"]
    assert fully_assigned.payload["metrics"]["unassigned_rate"] == 0.0
    assert CanonicalConfirmationEvidence.from_dict(fully_assigned.as_dict()) == fully_assigned
    with pytest.raises(CanonicalConfirmationError, match="every fitted class"):
        CanonicalConfirmationEvidence.build(
            **{
                **kwargs,
                "simca_labels": ("A", "B", "C"),
                "simca_membership": np.asarray(
                    [[True, True, False], [True, False, False], [False, True, False], [False, False, False]]
                ),
            }
        )


@pytest.mark.parametrize("grouped", [False, True])
def test_simca_confirmation_uncertainty_keeps_rare_fitted_class_in_every_draw(grouped: bool) -> None:
    plan = CanonicalConfirmationPlan.for_validation(
        100, 0.95, 42, task_type="classification", primary_metric="mean_class_acceptance_sensitivity"
    )
    observed = ["A"] * 20 + ["B"] * 20 + ["C"]
    predicted = ["A"] * 20 + ["B"] * 20 + ["unassigned"]
    membership = np.asarray([[True, False, False]] * 20 + [[False, True, False]] * 20 + [[False, False, False]])
    evidence = CanonicalConfirmationEvidence.build(
        request_digest="1" * 64,
        graph_digest="2" * 64,
        selected_validation_request_digest="3" * 64,
        winner_refit_authority_digest="4" * 64,
        artifact_digest="5" * 64,
        application_plan_digest="6" * 64,
        capability_content_digest="7" * 64,
        capability_envelope_digest="8" * 64,
        dataset_ref_digest="9" * 64,
        split_plan_digest="a" * 64,
        observed=observed,
        predicted=predicted,
        groups=["group-a"] * 20 + ["group-b"] * 20 + ["group-c"] if grouped else None,
        plan=plan,
        simca_membership=membership,
        simca_labels=("A", "B", "C"),
    )
    interval = evidence.payload["uncertainty"]["mean_class_acceptance_sensitivity"]
    assert evidence.payload["metrics"]["mean_class_acceptance_sensitivity"] == pytest.approx(2 / 3)
    assert interval["lower"] == pytest.approx(2 / 3)
    assert interval["upper"] == pytest.approx(2 / 3)
    assert CanonicalConfirmationEvidence.from_dict(evidence.as_dict()) == evidence


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("metrics", "rmse"), 99.0),
        (("uncertainty", "n_resamples"), 101),
        (("artifact_digest",), "f" * 64),
        (("application_plan_digest",), "e" * 64),
    ],
)
def test_confirmation_evidence_rejects_detached_aggregate_or_authority_tampering(
    path: tuple[str, ...], replacement: object
) -> None:
    payload = deepcopy(_evidence().as_dict())
    target = payload
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = replacement

    with pytest.raises(CanonicalConfirmationError, match="digest mismatch"):
        CanonicalConfirmationEvidence.from_dict(payload)


def test_confirmation_evidence_recomputes_from_values_instead_of_accepting_reported_metrics() -> None:
    expected = _evidence()
    changed = CanonicalConfirmationEvidence.build(
        request_digest="1" * 64,
        graph_digest="2" * 64,
        selected_validation_request_digest="3" * 64,
        winner_refit_authority_digest="4" * 64,
        artifact_digest="5" * 64,
        application_plan_digest="6" * 64,
        capability_content_digest="7" * 64,
        capability_envelope_digest="8" * 64,
        dataset_ref_digest="9" * 64,
        split_plan_digest="a" * 64,
        observed=[1.0, 2.0, 3.0, 4.0],
        predicted=[1.0, 2.0, 3.0, 4.0],
        groups=["a", "a", "b", "b"],
        plan=CanonicalConfirmationPlan(100, 0.95, 42),
    )

    assert changed.payload["metrics"]["rmse"] == 0.0
    assert changed.payload["metrics"] != expected.payload["metrics"]
    assert changed.evidence_digest != expected.evidence_digest
