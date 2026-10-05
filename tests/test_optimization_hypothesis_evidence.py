"""Portable hypothesis outcomes reproduce from retained scalar evidence."""

from copy import deepcopy

import pytest

from spectra_sherpa.sdk.optimization_hypothesis_evidence import (
    classify_hypothesis,
    hypothesis_projection_digest,
    summarize_direction_groups,
)


def _hypothesis(*, classification: bool = False, changes: int = 1):
    return {
        "hypothesis_id": "scatter",
        "title": "Test scatter handling",
        "direction_label": "scatter correction",
        "decision_rule": {
            "schema_version": "spectra-managed-hypothesis-decision-rule/1",
            "comparator": {},
            "paired_calculation": {
                "required_pair_count": 3,
                "primary_metric": "balanced_accuracy" if classification else "rmse",
                "direction": "maximize" if classification else "minimize",
            },
            "minimum_meaningful_improvement": 0.02 if classification else 0.1,
            "guardrails": (
                [{"metric": "mcc", "operator": "minimum", "value": 0.2}]
                if classification
                else [{"metric": "bias", "operator": "maximum_absolute", "value": 0.1}]
            ),
            "stability": {"minimum_fraction": 0.6},
        },
        "trial": {
            "workflow_diff": {
                "schema_version": "test",
                "change_count": changes,
                "added_nodes": [{"node_id": f"change_{index}"} for index in range(changes)],
                "removed_nodes": [],
                "operation_changes": [],
                "parameter_changes": [],
                "order_changes": [],
            }
        },
    }


def _validation(primary, folds, *, classification=False, guardrail=0.0):
    metric = "balanced_accuracy" if classification else "rmse"
    guardrail_metric = "mcc" if classification else "bias"
    return {
        "metrics": {metric: primary, guardrail_metric: guardrail},
        "folds": [
            {"partition_digest": character * 64, "metrics": {metric: value, guardrail_metric: guardrail}}
            for character, value in zip("abc", folds, strict=True)
        ],
    }


def _classify(hypothesis, reference, trial, *, status="evaluated", failure_code=None):
    return classify_hypothesis(
        hypothesis=hypothesis,
        reference_validation=reference,
        trial_validation=trial,
        trial_status=status,
        failure_code=failure_code,
    )


def test_regression_hypothesis_is_supported_only_when_every_frozen_rule_passes():
    result = _classify(
        _hypothesis(),
        _validation(1.0, [1.0, 0.9, 1.1]),
        _validation(0.8, [0.8, 0.7, 1.0], guardrail=-0.05),
    )

    assert result["outcome"] == "supported"
    assert result["reason"] == "all_frozen_rules_met"
    assert result["primary_metric"]["improvement"] == pytest.approx(0.2)
    assert result["stability"]["directionally_improved_pair_count"] == 3
    assert result["guardrails"][0]["passed"] is True
    assert result["attribution"] == "single_change_attributable"


@pytest.mark.parametrize(
    ("trial", "expected_reason"),
    [
        (_validation(0.95, [0.9, 0.85, 1.0]), "one_or_more_frozen_rules_not_met"),
        (_validation(0.8, [0.8, 0.7, 1.0], guardrail=0.2), "one_or_more_frozen_rules_not_met"),
        (_validation(0.8, [0.9, 1.0, 1.2]), "aggregate_and_pair_stability_conflict"),
    ],
)
def test_threshold_guardrail_and_stability_dispositions_are_deterministic(trial, expected_reason):
    result = _classify(_hypothesis(), _validation(1.0, [1.0, 0.9, 1.1]), trial)

    assert result["reason"] == expected_reason
    assert result["outcome"] == (
        "inconclusive" if expected_reason == "aggregate_and_pair_stability_conflict" else "not_supported"
    )


def test_failed_or_incomplete_paired_evidence_is_inconclusive():
    reference = _validation(1.0, [1.0, 0.9, 1.1])
    failed = _classify(_hypothesis(), reference, None, status="failed", failure_code="fit_failed")
    missing = _validation(0.8, [0.8, 0.7, 1.0])
    missing["folds"].pop()
    incomplete = _classify(_hypothesis(), reference, missing)

    assert (failed["outcome"], failed["reason"], failed["failure_code"]) == (
        "inconclusive",
        "trial_failed_or_evidence_incomplete",
        "fit_failed",
    )
    assert (incomplete["outcome"], incomplete["reason"]) == (
        "inconclusive",
        "paired_evidence_insufficient",
    )


def test_live_batch_remains_pending_even_when_one_pair_is_already_complete():
    result = classify_hypothesis(
        hypothesis=_hypothesis(),
        reference_validation=_validation(1.0, [1.0, 0.9, 1.1]),
        trial_validation=_validation(0.8, [0.8, 0.7, 1.0]),
        trial_status="evaluated",
        failure_code=None,
        execution_complete=False,
    )

    assert (result["outcome"], result["reason"]) == ("pending", "execution_in_progress")


def test_classification_uses_maximize_direction_and_declared_mcc_guardrail():
    result = _classify(
        _hypothesis(classification=True),
        _validation(0.70, [0.68, 0.70, 0.72], classification=True, guardrail=0.25),
        _validation(0.76, [0.74, 0.77, 0.76], classification=True, guardrail=0.31),
    )

    assert result["outcome"] == "supported"
    assert result["primary_metric"]["metric"] == "balanced_accuracy"
    assert result["primary_metric"]["improvement"] == pytest.approx(0.06)
    assert result["guardrails"] == [
        {"metric": "mcc", "operator": "minimum", "limit": 0.2, "observed": 0.31, "passed": True}
    ]


def test_regression_maximum_guardrail_is_a_valid_upper_bound():
    hypothesis = _hypothesis()
    hypothesis["decision_rule"]["guardrails"] = [{"metric": "mae", "operator": "maximum", "value": 0.5}]
    reference = _validation(1.0, [1.0, 0.9, 1.1])
    reference["metrics"]["mae"] = 0.6
    trial = _validation(0.8, [0.8, 0.7, 1.0])
    trial["metrics"]["mae"] = 0.4

    result = _classify(hypothesis, reference, trial)

    assert result["outcome"] == "supported"
    assert result["guardrails"] == [
        {"metric": "mae", "operator": "maximum", "limit": 0.5, "observed": 0.4, "passed": True}
    ]


def test_bundled_change_and_direction_group_never_create_attribution_or_group_support():
    result = _classify(
        _hypothesis(changes=2),
        _validation(1.0, [1.0, 0.9, 1.1]),
        _validation(0.8, [0.8, 0.7, 1.0]),
    )
    groups = summarize_direction_groups([result, {**deepcopy(result), "hypothesis_id": "scatter_2"}])

    assert result["attribution"] == "bundled_changes_non_attributable"
    assert groups == [
        {
            "direction_label": "scatter correction",
            "member_hypothesis_ids": ["scatter", "scatter_2"],
            "member_outcome_counts": {"pending": 0, "supported": 2, "not_supported": 0, "inconclusive": 0},
            "claim_status": "summary_only_no_group_support_claim",
        }
    ]
    assert "outcome" not in groups[0]


def test_two_parameter_changes_on_one_node_are_a_non_attributable_bundle():
    hypothesis = _hypothesis()
    diff = hypothesis["trial"]["workflow_diff"]
    diff["added_nodes"] = []
    diff["parameter_changes"] = [
        {"node_id": "model", "parameter": "n_components", "before": 4, "after": 6},
        {"node_id": "model", "parameter": "scale", "before": False, "after": True},
    ]

    result = _classify(
        hypothesis,
        _validation(1.0, [1.0, 0.9, 1.1]),
        _validation(0.8, [0.8, 0.7, 1.0]),
    )

    assert result["scientific_change_count"] == 2
    assert result["attribution"] == "bundled_changes_non_attributable"


def test_projection_digest_is_unicode_safe_and_reproducible():
    projection = {"response": "β-carotene", "units": "µg/mL", "outcome": "supported"}
    assert hypothesis_projection_digest(projection) == hypothesis_projection_digest(deepcopy(projection))
