from __future__ import annotations

import numpy as np
import pytest

import spectra_sherpa.sdk as ss
from spectra_sherpa.sdk.validate import Fold, SplitPlan


def test_metrics_uses_versioned_regression_definitions() -> None:
    result = ss.validate.metrics([1.0, 2.0, 3.0], [2.0, 2.0, 2.0])

    assert result.registry_version == "2"
    assert result.n_samples == 3
    assert result.rmse == pytest.approx(np.sqrt(2 / 3))
    assert result.mae == pytest.approx(2 / 3)
    assert result.bias == pytest.approx(0.0)
    assert result.r2 == pytest.approx(0.0)
    assert result.sep == pytest.approx(1.0)
    assert result.slope == pytest.approx(0.0)
    assert result.intercept == pytest.approx(2.0)
    assert result.rer == pytest.approx(2.0)


def test_metrics_marks_constant_target_r2_undefined() -> None:
    result = ss.validate.metrics([2.0, 2.0], [2.0, 2.0])

    assert result.r2 is None


def test_classification_metrics_requires_explicit_positive_label() -> None:
    result = ss.validate.classification_metrics(
        ["pass", "pass", "fail", "fail", "fail"],
        ["pass", "fail", "pass", "fail", "fail"],
        positive_label="fail",
    )

    assert result.registry_version == "1"
    assert result.positive_label == "fail"
    assert result.negative_label == "pass"
    assert (result.true_positive, result.false_positive, result.true_negative, result.false_negative) == (2, 1, 1, 1)
    assert result.sensitivity == pytest.approx(2 / 3)
    assert result.specificity == pytest.approx(1 / 2)
    assert result.accuracy == pytest.approx(3 / 5)
    with pytest.raises(ValueError, match="positive_label"):
        ss.validate.classification_metrics(["pass", "fail"], ["pass", "fail"], positive_label="detected")
    with pytest.raises(ValueError, match="exactly two"):
        ss.validate.classification_metrics(["pass", "pass"], ["pass", "pass"], positive_label="pass")
    with pytest.raises(ValueError, match="absent from y_true"):
        ss.validate.classification_metrics(["pass", "fail"], ["pass", "unknown"], positive_label="fail")


def test_multiclass_metric_set_reports_per_class_sensitivity_and_specificity() -> None:
    result = ss.validate.classification_metric_set(
        ["A", "A", "B", "B"],
        ["A", "B", "B", "B"],
        labels=["A", "B"],
    )
    assert result.registry_version == "2"
    assert result.class_sensitivities == (0.5, 1.0)
    assert result.class_specificities == (1.0, 0.5)
    assert result.mean_class_acceptance_sensitivity is None
    assert result.unassigned_rate is None
    assert result.multiple_acceptance_rate is None
    assert result.simca_acceptance is None
    assert ss.validate.validate_supervised_metric_record(result.as_dict()) == result.as_dict()


def test_simca_acceptance_evidence_pools_exact_counts_across_folds() -> None:
    first = ss.validate.classification_metric_set(
        ["A", "B"],
        ["A", "unassigned"],
        labels=("A", "B", "unassigned"),
        simca_membership=[[True, False], [False, False]],
        simca_labels=("A", "B"),
    ).as_dict()
    second = ss.validate.classification_metric_set(
        ["A", "B"],
        ["B", "B"],
        labels=("A", "B", "unassigned"),
        simca_membership=[[True, True], [False, True]],
        simca_labels=("A", "B"),
    ).as_dict()

    pooled = ss.validate.pool_supervised_metric_records([first, second])

    assert pooled["simca_acceptance"] == {
        "schema_version": "spectra-simca-acceptance-evidence/1",
        "labels": ["A", "B"],
        "n_samples": 4,
        "unassigned_count": 1,
        "unassigned_rate": 0.25,
        "multiple_acceptance_count": 1,
        "multiple_acceptance_rate": 0.25,
        "observed_class_counts": [2, 2],
        "accepted_own_class_counts": [2, 1],
        "class_acceptance_sensitivity": [1.0, 0.5],
        "representative_challenge_population_declared": False,
        "class_acceptance_specificity": None,
    }
    assert pooled["mean_class_acceptance_sensitivity"] == pytest.approx(0.75)
    assert pooled["unassigned_rate"] == pytest.approx(0.25)
    assert pooled["multiple_acceptance_rate"] == pytest.approx(0.25)
    assert ss.validate.validate_supervised_metric_record(pooled) == pooled

    for corrupted_labels in (["X", "Y"], ["A", "A"], ["B", "A"]):
        corrupted = {
            **pooled,
            "simca_acceptance": {
                **pooled["simca_acceptance"],
                "labels": corrupted_labels,
            },
        }
        with pytest.raises(ValueError, match="confusion-matrix class identities"):
            ss.validate.validate_supervised_metric_record(corrupted)


def test_multiclass_metric_set_is_pooled_from_one_confusion_authority() -> None:
    observed = np.asarray(["A", "A", "B", "B", "C", "C"], dtype=object)
    predicted = np.asarray(["A", "B", "B", "B", "C", "A"], dtype=object)
    accumulator = ss.validate.ClassificationMetricAccumulator(("A", "B", "C"))

    accumulator.add(observed[:3], predicted[:3])
    accumulator.add(observed[3:], predicted[3:])
    result = accumulator.metrics()

    assert result == ss.validate.classification_metric_set(
        observed,
        predicted,
        labels=("A", "B", "C"),
    )
    assert result.n_samples == 6
    assert result.confusion_matrix == ((1, 1, 0), (0, 2, 0), (1, 0, 1))
    assert result.accuracy == pytest.approx(4 / 6)
    assert result.balanced_accuracy == pytest.approx((0.5 + 1.0 + 0.5) / 3)
    assert result.macro_f1 == pytest.approx((0.5 + 0.8 + 2 / 3) / 3)
    assert result.mcc == pytest.approx(0.5222329678670935)
    assert result.as_dict()["task_type"] == "classification"


def test_multiclass_metric_set_rejects_undeclared_predictions() -> None:
    accumulator = ss.validate.ClassificationMetricAccumulator(("A", "B"))

    with pytest.raises(ValueError, match="undeclared class label"):
        accumulator.add(["A", "B"], ["A", "unknown"])


def test_multiclass_metric_set_counts_declared_predicted_only_rejections_without_diluting_class_balance() -> None:
    result = ss.validate.classification_metric_set(
        ["A", "A", "B", "B"],
        ["A", "unassigned", "B", "unassigned"],
        labels=("A", "B", "unassigned"),
    )

    assert result.accuracy == pytest.approx(0.5)
    assert result.balanced_accuracy == pytest.approx(0.5)
    assert result.confusion_matrix == ((1, 0, 1), (0, 1, 1), (0, 0, 0))


@pytest.mark.parametrize("label", [None, b"bytes", ["nested"], {"not": "scalar"}, float("nan")])
def test_multiclass_metric_set_rejects_nonportable_labels(label: object) -> None:
    with pytest.raises(ValueError, match="bounded JSON-scalar"):
        ss.validate.classification_metric_set(["control", label], ["control", label])


def test_classification_split_plan_is_stratified_and_digest_bound() -> None:
    labels = np.asarray(["a", "b", "c"] * 4, dtype=object)

    plan = ss.validate.make_classification_split_plan(labels, n_splits=4)

    assert plan.method == "stratified_kfold"
    assert len(plan.digest) == 64
    for fold in plan.folds:
        assert set(labels[fold.train]) == {"a", "b", "c"}
        assert set(labels[fold.test]) == {"a", "b", "c"}
    ss.validate.validate_classification_split_plan(plan, labels)


def test_classification_split_plan_rejects_an_underrepresented_class() -> None:
    labels = np.asarray(["major"] * 8 + ["minor"] * 2, dtype=object)

    with pytest.raises(ValueError, match="at least n_splits"):
        ss.validate.make_classification_split_plan(labels, n_splits=3)


def test_metric_parity_uses_documented_tolerance() -> None:
    expected = ss.validate.metrics([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    actual = ss.validate.RegressionMetrics(
        registry_version="2",
        n_samples=3,
        rmse=5e-13,
        mae=5e-13,
        bias=-5e-13,
        r2=1.0 - 5e-13,
        sep=5e-13,
        slope=1.0 - 5e-13,
        intercept=5e-13,
        rer=None,
    )

    result = ss.validate.compare_metric_parity(expected, actual)

    assert result.matches
    assert result.differences == {}
    result.require_match()


def test_metric_parity_rejects_scientific_difference_and_contract_mismatch() -> None:
    expected = ss.validate.metrics([1.0, 2.0, 3.0], [1.0, 2.0, 3.0])
    actual = ss.validate.RegressionMetrics(
        registry_version="3",
        n_samples=4,
        rmse=0.01,
        mae=0.0,
        bias=0.0,
        r2=1.0,
        sep=0.0,
        slope=1.0,
        intercept=0.0,
        rer=None,
    )

    result = ss.validate.compare_metric_parity(expected, actual)

    assert result.matches is False
    assert set(result.differences) == {"registry_version", "n_samples", "rmse"}
    with pytest.raises(ValueError, match="metric parity failed"):
        result.require_match()


def test_bootstrap_regression_uncertainty_is_deterministic_and_group_aware() -> None:
    observed = np.arange(1.0, 13.0)
    predicted = observed + np.asarray([0.0, 0.2, -0.1, 0.3] * 3)
    groups = np.repeat(["batch-a", "batch-b", "batch-c"], 4)

    first = ss.validate.bootstrap_regression_uncertainty(
        observed,
        predicted,
        groups=groups,
        n_resamples=100,
        random_state=17,
    )
    second = ss.validate.bootstrap_regression_uncertainty(
        observed,
        predicted,
        groups=groups,
        n_resamples=100,
        random_state=17,
    )

    assert first == second
    assert first.grouped is True
    assert first.rmse.lower <= first.rmse.upper
    assert first.mae.lower <= first.mae.upper
    assert first.r2 is not None
    with pytest.raises(ValueError, match="one value per sample"):
        ss.validate.bootstrap_regression_uncertainty(observed, predicted, groups=["only-one"], n_resamples=10)
    with pytest.raises(ValueError, match="at least 2"):
        ss.validate.bootstrap_regression_uncertainty(observed, predicted, n_resamples=1)


def test_group_kfold_never_splits_an_independent_group() -> None:
    groups = ["batch-a", "batch-a", "batch-b", "batch-b", "batch-c", "batch-c"]
    plan = ss.validate.make_split_plan(len(groups), n_splits=3, groups=groups)

    assert plan.method == "group_kfold"
    assert plan.grouped is True
    for fold in plan.folds:
        assert set(np.asarray(groups)[fold.train]).isdisjoint(np.asarray(groups)[fold.test])


def test_kfold_rejects_seed_without_shuffle() -> None:
    with pytest.raises(ValueError, match="requires shuffle=True"):
        ss.validate.make_split_plan(8, n_splits=4, random_state=7)


def test_split_plan_rejects_group_leakage() -> None:
    plan = SplitPlan(
        method="invalid",
        n_samples=4,
        folds=(
            Fold(train=np.array([0, 1]), test=np.array([2, 3])),
            Fold(train=np.array([2, 3]), test=np.array([0, 1])),
        ),
        grouped=True,
    )

    with pytest.raises(ValueError, match="leaks group"):
        plan.validate(["batch-a", "batch-b", "batch-a", "batch-c"])


def test_split_plan_rejects_fold_that_drops_training_samples() -> None:
    plan = SplitPlan(
        method="invalid",
        n_samples=4,
        folds=(
            Fold(train=np.array([0]), test=np.array([1, 2])),
            Fold(train=np.array([1, 2]), test=np.array([0, 3])),
        ),
        grouped=False,
    )

    with pytest.raises(ValueError, match="does not partition every sample"):
        plan.validate()


def test_parallel_estimator_validation_and_local_quarantine_surfaces_are_absent() -> None:
    retired_validation_names = {
        "ConfirmationQuarantine",
        "ConfirmationQuarantineError",
        "ConfirmationResult",
        "CrossValidationResult",
        "FrozenCandidate",
        "NestedCrossValidationResult",
        "cross_validate",
        "cross_validate_classification",
        "nested_cross_validate",
    }

    assert retired_validation_names.isdisjoint(dir(ss.validate))
    assert not hasattr(ss.report, "cross_validation_diagnostics")
