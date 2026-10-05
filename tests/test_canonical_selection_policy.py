"""Single-authority scientific selection policy tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from spectra_sherpa.app.services.dag.canonical_selection_policy import (
    CanonicalSelectionPolicy,
    CanonicalSelectionPolicyError,
    build_canonical_development_decision,
    selection_candidate,
    verify_canonical_development_decision,
)


def _candidate(candidate_id: str, ordinal: int, values: list[float]) -> dict:
    pooled = (sum(value**2 for value in values) / len(values)) ** 0.5
    metrics = {
        "registry_version": "2",
        "n_samples": 10 * len(values),
        "rmse": pooled,
        "mae": pooled,
        "bias": 0.0,
        "r2": None,
        "sep": pooled,
        "slope": None,
        "intercept": None,
        "rer": None,
    }
    return selection_candidate(
        candidate_id=candidate_id,
        ordinal=ordinal,
        result_digest=f"{ordinal:064x}",
        dataset_content_digest="b" * 64,
        split_plan_digest="a" * 64,
        metrics=metrics,
        folds=[
            {
                "partition_digest": f"{index + 10:064x}",
                "metrics": {
                    "registry_version": "2",
                    "n_samples": 10,
                    "rmse": value,
                    "mae": value,
                    "bias": 0.0,
                    "r2": None,
                    "sep": value,
                    "slope": None,
                    "intercept": None,
                    "rer": None,
                },
            }
            for index, value in enumerate(values)
        ],
    )


def test_policy_is_digest_bound_and_decision_recomputes_from_folds() -> None:
    policy = CanonicalSelectionPolicy.build(0.05)
    candidates = [
        _candidate("baseline-001", 1, [1.0, 1.0, 1.0, 1.0]),
        _candidate("candidate-002", 2, [0.8, 0.81, 0.79, 0.8]),
    ]

    decision = build_canonical_development_decision(candidates, policy=policy)
    verified = verify_canonical_development_decision(decision, candidates, expected_policy=policy)

    assert verified["conclusion"] == "improved"
    assert verified["conclusion_reason"] == "declared_margin_dispersion_and_majority_satisfied"
    assert verified["strategy"]["content_digest"] == policy.content_digest
    assert verified["paired_fold_margin"]["folds_favouring_winner"] == 4


def test_ranking_does_not_choose_and_scientist_can_keep_lower_ranked_candidate() -> None:
    policy = CanonicalSelectionPolicy.build(0.0)
    candidates = [_candidate("baseline-001", 1, [1.0] * 3), _candidate("candidate-002", 2, [0.8] * 3)]
    ranked = build_canonical_development_decision(candidates, policy=policy, require_scientist_selection=True)
    assert ranked["scientist_selection"] is None
    assert ranked["ranked_first_candidate_id"] == "candidate-002"
    assert verify_canonical_development_decision(ranked, candidates) == ranked
    chosen = build_canonical_development_decision(
        candidates,
        policy=policy,
        require_scientist_selection=True,
        scientist_selection={"candidate_id": "baseline-001", "actor_user_id": 7, "rationale": "Simpler model"},
    )
    assert chosen["winner_candidate_id"] == "baseline-001"
    assert chosen["ranked_first_candidate_id"] == "candidate-002"
    assert chosen["pooled_improvement"] == 0
    assert verify_canonical_development_decision(chosen, candidates) == chosen
    changed = deepcopy(chosen)
    changed["winner_candidate_id"] = "candidate-002"
    with pytest.raises(CanonicalSelectionPolicyError, match="does not reproduce"):
        verify_canonical_development_decision(changed, candidates)


@pytest.mark.parametrize(
    "candidate_id,actor,rationale",
    [("missing-001", 7, "Review"), ("baseline-001", True, "Review"), ("baseline-001", 7, "")],
)
def test_scientist_selection_rejects_missing_trial_or_invalid_actor_or_reason(candidate_id, actor, rationale):
    with pytest.raises(CanonicalSelectionPolicyError):
        build_canonical_development_decision(
            [_candidate("baseline-001", 1, [1.0] * 3)],
            policy=CanonicalSelectionPolicy.build(0.0),
            scientist_selection={"candidate_id": candidate_id, "actor_user_id": actor, "rationale": rationale},
        )


def test_strict_fold_majority_rejects_a_win_concentrated_in_half_the_folds() -> None:
    candidates = [
        _candidate("baseline-001", 1, [1.0, 1.0, 1.0, 1.0]),
        _candidate("candidate-002", 2, [0.8, 0.8, 1.01, 1.01]),
    ]

    decision = build_canonical_development_decision(
        candidates,
        policy=CanonicalSelectionPolicy.build(0.0),
    )

    assert decision["winner_candidate_id"] == "candidate-002"
    assert decision["pooled_improvement"] > decision["paired_fold_margin"]["required_dispersion_delta"]
    assert decision["paired_fold_margin"]["folds_favouring_winner"] == 2
    assert decision["conclusion"] == "no_defensible_improvement"
    assert decision["conclusion_reason"] == "not_consistent_across_folds"


def test_verifier_rejects_rehashed_summary_instead_of_echoing_it() -> None:
    policy = CanonicalSelectionPolicy.build(0.0)
    candidates = [
        _candidate("baseline-001", 1, [1.0, 1.0, 1.0]),
        _candidate("candidate-002", 2, [0.8, 0.8, 0.8]),
    ]
    decision = build_canonical_development_decision(candidates, policy=policy)
    forged = deepcopy(decision)
    forged["paired_fold_margin"]["paired_standard_error"] = 0.5
    forged["paired_fold_margin"]["required_dispersion_delta"] = 0.5
    forged["conclusion"] = "no_defensible_improvement"
    forged["conclusion_reason"] = "within_fold_dispersion"

    with pytest.raises(CanonicalSelectionPolicyError, match="does not reproduce from fold evidence"):
        verify_canonical_development_decision(forged, candidates)


def test_policy_and_partition_changes_fail_closed() -> None:
    policy = CanonicalSelectionPolicy.build(0.1).as_dict()
    policy["minimum_improvement"] = 0.0
    with pytest.raises(CanonicalSelectionPolicyError, match="content digest mismatch"):
        CanonicalSelectionPolicy.from_dict(policy)

    baseline = _candidate("baseline-001", 1, [1.0, 1.0])
    candidate = _candidate("candidate-002", 2, [0.8, 0.8])
    candidate["folds"][1]["partition_digest"] = "f" * 64
    with pytest.raises(CanonicalSelectionPolicyError, match="identical folds"):
        build_canonical_development_decision(
            [baseline, candidate],
            policy=CanonicalSelectionPolicy.build(0.0),
        )


def test_pooled_rmse_and_dataset_identity_are_recomputed() -> None:
    baseline = _candidate("baseline-001", 1, [1.0, 1.0])
    candidate = _candidate("candidate-002", 2, [0.8, 0.8])

    forged_rmse = deepcopy(candidate)
    forged_rmse["metrics"]["rmse"] = 0.1
    forged_rmse["metrics"]["mae"] = 0.1
    with pytest.raises(CanonicalSelectionPolicyError, match="primary metric"):
        build_canonical_development_decision(
            [baseline, forged_rmse],
            policy=CanonicalSelectionPolicy.build(0.0),
        )

    changed_dataset = {**candidate, "dataset_content_digest": "c" * 64}
    with pytest.raises(CanonicalSelectionPolicyError, match="dataset content"):
        build_canonical_development_decision(
            [baseline, changed_dataset],
            policy=CanonicalSelectionPolicy.build(0.0),
        )


def test_one_fold_cannot_support_a_dispersion_claim() -> None:
    with pytest.raises(CanonicalSelectionPolicyError, match="at least two folds"):
        selection_candidate(
            candidate_id="baseline-001",
            ordinal=1,
            result_digest="1" * 64,
            dataset_content_digest="4" * 64,
            split_plan_digest="2" * 64,
            metrics={
                "registry_version": "2",
                "n_samples": 10,
                "rmse": 1.0,
                "mae": 1.0,
                "bias": 0.0,
                "r2": None,
                "sep": 1.0,
                "slope": None,
                "intercept": None,
                "rer": None,
            },
            folds=[
                {
                    "partition_digest": "3" * 64,
                    "metrics": {
                        "registry_version": "2",
                        "n_samples": 10,
                        "rmse": 1.0,
                        "mae": 1.0,
                        "bias": 0.0,
                        "r2": None,
                        "sep": 1.0,
                        "slope": None,
                        "intercept": None,
                        "rer": None,
                    },
                }
            ],
        )


def test_classification_policy_maximizes_balanced_accuracy_from_confusion_evidence() -> None:
    def classified(candidate_id: str, ordinal: int, matrices: list[list[list[int]]]) -> dict:
        # Scalar fields are a deterministic projection, so construct through
        # the same public accumulator rather than authoring reported numbers.
        from spectra_sherpa.sdk.validate import ClassificationMetricAccumulator, pool_supervised_metric_records

        fold_records = []
        for matrix in matrices:
            observed: list[str] = []
            predicted: list[str] = []
            labels = ("a", "b")
            for actual_index, row in enumerate(matrix):
                for predicted_index, count in enumerate(row):
                    observed.extend([labels[actual_index]] * count)
                    predicted.extend([labels[predicted_index]] * count)
            accumulator = ClassificationMetricAccumulator(labels=labels)
            accumulator.add(observed, predicted)
            fold_records.append(accumulator.metrics().as_dict())
        return selection_candidate(
            candidate_id=candidate_id,
            ordinal=ordinal,
            result_digest=f"{ordinal:064x}",
            dataset_content_digest="b" * 64,
            split_plan_digest="a" * 64,
            metrics=pool_supervised_metric_records(fold_records),
            folds=[
                {"partition_digest": f"{index + 20:064x}", "metrics": metric}
                for index, metric in enumerate(fold_records)
            ],
        )

    baseline = classified("baseline-001", 1, [[[7, 3], [3, 7]], [[6, 4], [2, 8]]])
    candidate = classified("candidate-002", 2, [[[9, 1], [2, 8]], [[8, 2], [1, 9]]])
    decision = build_canonical_development_decision(
        [baseline, candidate],
        policy=CanonicalSelectionPolicy.build(0.01, task_type="classification"),
    )

    assert decision["winner_candidate_id"] == "candidate-002"
    assert decision["winner_primary_metric"] > decision["baseline_primary_metric"]
    assert decision["conclusion"] == "improved"
