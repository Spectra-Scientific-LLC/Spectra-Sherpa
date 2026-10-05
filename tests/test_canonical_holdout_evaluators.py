from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.classification_evaluator_node import (
    ClassificationEvaluatorV2Node,
    evaluate_classification_v2,
)
from spectra_sherpa.app.services.dag.nodes.regression_evaluator_node import (
    RegressionEvaluatorV2Node,
    evaluate_regression_v2,
)
from spectra_sherpa.sdk.validate import ClassificationMetricAccumulator, metrics
from tests.performance_contract import PerformanceCeiling


def test_regression_local_evaluation_reuses_managed_metric_registry() -> None:
    observed = np.asarray([1.0, 2.0, 4.0, 8.0])
    predicted = np.asarray([1.2, 1.8, 4.5, 7.5])

    result = evaluate_regression_v2(predicted, observed, node_id="score")

    assert result.outputs["default"] == {
        "task_type": "regression",
        **metrics(observed, predicted).as_dict(),
    }
    rows = result.outputs["comparison"]["data"]
    assert [(row["sample"], row["target"], row["role"]) for row in rows] == [
        ("1", "Target 1", "unqualified_evaluation"),
        ("2", "Target 1", "unqualified_evaluation"),
        ("3", "Target 1", "unqualified_evaluation"),
        ("4", "Target 1", "unqualified_evaluation"),
    ]
    np.testing.assert_allclose([row["reference"] for row in rows], observed)
    np.testing.assert_allclose([row["predicted"] for row in rows], predicted)
    np.testing.assert_allclose([row["residual"] for row in rows], observed - predicted)
    generated = "\n".join(
        RegressionEvaluatorV2Node("score", {}).generate_python({"default": "predicted", "y_true": "observed"})
    )
    assert "evaluate_regression_v2" in generated


def test_regression_evaluator_has_a_representative_absolute_performance_ceiling() -> None:
    observed = np.linspace(0.0, 100.0, 10_000)
    predicted = observed + np.sin(observed) * 0.05

    with PerformanceCeiling(
        "diagnostics.regression_evaluator",
        "10000-held-out-decisions",
        5.0,
    ).measure():
        result = evaluate_regression_v2(predicted, observed, node_id="score")

    assert result.outputs["default"]["n_samples"] == 10_000
    assert len(result.outputs["comparison"]["data"]) == 10_000


@pytest.mark.asyncio
async def test_regression_local_evaluation_requires_explicit_truth() -> None:
    with pytest.raises(RuntimeError, match="explicit y_true"):
        await RegressionEvaluatorV2Node("score", {}).execute(np.asarray([1.0, 2.0]))


def test_multiclass_evaluator_accounts_for_predicted_only_rejections() -> None:
    observed = np.asarray(["A", "A", "B", "B", "C", "C"])
    predicted = np.asarray(["A", "unassigned", "B", "C", "C", "unassigned"])

    result = evaluate_classification_v2(predicted, observed, node_id="score")
    report = result.outputs["default"]

    assert report["n_samples"] == 6
    assert report["predicted_only_labels"] == ["unassigned"]
    assert sum(sum(row) for row in report["confusion_matrix"]) == 6
    assert report["accuracy"] == pytest.approx(3 / 6)
    assert report["balanced_accuracy"] == pytest.approx(0.5)
    assert report["macro_specificity"] == pytest.approx(41 / 48)
    assert all("specificity" in row for row in report["per_class"])
    comparison_rows = result.outputs["comparison"]["data"]
    assert comparison_rows == [
        {
            "sample": "Evaluation row 1",
            "reference": "A",
            "predicted": "A",
            "correct": True,
            "role": "unqualified_evaluation",
        },
        {
            "sample": "Evaluation row 2",
            "reference": "A",
            "predicted": "unassigned",
            "correct": False,
            "role": "unqualified_evaluation",
        },
        {
            "sample": "Evaluation row 3",
            "reference": "B",
            "predicted": "B",
            "correct": True,
            "role": "unqualified_evaluation",
        },
        {
            "sample": "Evaluation row 4",
            "reference": "B",
            "predicted": "C",
            "correct": False,
            "role": "unqualified_evaluation",
        },
        {
            "sample": "Evaluation row 5",
            "reference": "C",
            "predicted": "C",
            "correct": True,
            "role": "unqualified_evaluation",
        },
        {
            "sample": "Evaluation row 6",
            "reference": "C",
            "predicted": "unassigned",
            "correct": False,
            "role": "unqualified_evaluation",
        },
    ]
    assert result.diagnostics["accounted_samples"] == 6
    generated = "\n".join(
        ClassificationEvaluatorV2Node("score", {}).generate_python({"default": "predicted", "y_true": "observed"})
    )
    assert "evaluate_classification_v2" in generated


def test_classification_evaluator_declares_complete_scientist_facing_results() -> None:
    contract = ClassificationEvaluatorV2Node.metadata.resolved_presentation_contract()

    assert contract is not None
    assert contract.default_presentation == "sample_comparison"
    assert [(item.presentation_id, item.kind, item.source_ports) for item in contract.presentations] == [
        ("sample_comparison", "classification_comparison", ("comparison",)),
        ("metrics", "metric_record", ("default",)),
        ("confusion", "confusion_matrix", ("visualization",)),
    ]


def test_classification_evaluator_emits_and_pools_managed_metric_record() -> None:
    node = ClassificationEvaluatorV2Node("score", {})
    accumulator = ClassificationMetricAccumulator(("A", "B", "C"))

    first = node.score_held_out_predictions(
        np.asarray(["A", "B", "A"], dtype=object),
        np.asarray(["A", "B", "C"], dtype=object),
        accumulator=accumulator,
    )
    second = node.score_held_out_predictions(
        np.asarray(["A", "C", "C"], dtype=object),
        np.asarray(["A", "B", "C"], dtype=object),
        accumulator=accumulator,
    )

    assert first.n_samples == second.n_samples == 3
    assert accumulator.metrics().n_samples == 6
    assert accumulator.metrics().confusion_matrix == ((2, 0, 0), (0, 1, 1), (1, 0, 1))


def test_classification_evaluator_has_a_representative_absolute_performance_ceiling() -> None:
    observed = np.resize(np.asarray(["A", "B", "C", "D"], dtype=object), 10_000)
    predicted = observed.copy()
    predicted[::17] = "unassigned"

    with PerformanceCeiling(
        "diagnostics.classification_evaluator",
        "10000-held-out-decisions-four-classes",
        5.0,
    ).measure():
        result = evaluate_classification_v2(predicted, observed, node_id="score")

    assert result.outputs["default"]["n_samples"] == 10_000
    assert len(result.outputs["comparison"]["data"]) == 10_000
    assert result.diagnostics["accounted_samples"] == 10_000


def test_classification_evaluator_exposes_typed_prediction_and_truth_ports() -> None:
    contract = node_registry.get_metadata("diagnostics.classification_evaluator").resolved_execution_contract()

    assert contract is not None
    assert [port["type_ref"] for port in contract.payload["semantic_inputs"]] == [
        "spectrasherpa://types/Categorical/1.0",
        "spectrasherpa://types/TargetMatrix/1.0",
    ]


def test_classification_evaluator_rejects_cross_domain_labels() -> None:
    with pytest.raises(ValueError, match="observed numeric class-label domain"):
        evaluate_classification_v2(
            np.asarray(["1", "2"]),
            np.asarray([1, 2]),
        )


def test_classification_evaluator_counts_rejection_against_numeric_truth() -> None:
    result = evaluate_classification_v2(
        np.asarray([1, "unassigned", 2], dtype=object),
        np.asarray([1, 1, 2]),
    )

    report = result.outputs["default"]
    assert report["accuracy"] == pytest.approx(2 / 3)
    assert report["labels"] == [1.0, 2.0, "unassigned"]
    assert report["predicted_only_labels"] == ["unassigned"]
    assert sum(sum(row) for row in report["confusion_matrix"]) == 3


def test_classification_evaluator_rejects_ambiguous_observed_rejection_label() -> None:
    with pytest.raises(ValueError, match="reserves 'unassigned'"):
        evaluate_classification_v2(
            np.asarray(["A", "unassigned"]),
            np.asarray(["A", "unassigned"]),
        )


@pytest.mark.parametrize("labels", [["row-1", "row-3", "row-7"], ["duplicate", "duplicate", "other"]])
def test_classification_comparison_retains_explicit_sample_order(labels):
    import json

    from spectra_sherpa.app.services.dag.classification_comparison import build_classification_comparison

    comparison = build_classification_comparison(
        ["A", "B", "B"], ["A", "A", "B"], role="held_out_test", sample_labels=labels
    )
    retained = json.loads(json.dumps(comparison))
    assert [row["sample"] for row in retained["data"]] == labels
    assert retained["metadata"]["sample_identity"] == "provided_labels"
    fallback = build_classification_comparison(["A", "B", "B"], ["A", "A", "B"], role="held_out_test")
    assert [row["sample"] for row in fallback["data"]] == ["Held-out row 1", "Held-out row 2", "Held-out row 3"]
    assert fallback["metadata"]["sample_identity"] == "row_position_only"
    with pytest.raises(ValueError, match="labels must match"):
        build_classification_comparison(["A"], ["A"], role="held_out_test", sample_labels=[])
