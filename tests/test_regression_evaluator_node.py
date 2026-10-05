"""Contracts for the first canonical held-out regression evaluator."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes.regression_evaluator_node  # noqa: F401
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.regression_evaluator_node import (
    RegressionEvaluatorV2Node,
    evaluate_regression_v2,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, TargetAccess
from spectra_sherpa.sdk.validate import RegressionMetricAccumulator, compare_metric_parity, metrics


def test_evaluator_has_a_distinct_target_consuming_contract_and_typed_ports() -> None:
    metadata = node_registry.get_metadata("diagnostics.regression_evaluator")
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["lifecycle_kind"] == LifecycleKind.EVALUATOR.value
    assert contract.payload["target_access"] == TargetAccess.REQUIRED.value
    assert contract.payload["sample_effect"] == "aggregates_samples"
    assert [port["type_ref"] for port in contract.payload["semantic_inputs"]] == [
        "spectrasherpa://types/TargetMatrix/1.0",
        "spectrasherpa://types/TargetMatrix/1.0",
    ]
    assert [port["name"] for port in contract.payload["semantic_inputs"]] == ["default", "y_true"]
    assert [port["type_ref"] for port in contract.payload["semantic_outputs"]] == [
        "spectrasherpa://types/ValidationResult/1.0",
        "spectrasherpa://types/RegressionComparison/1.0",
    ]
    components = {component["component_id"] for component in contract.payload["implementation_components"]}
    assert "spectra_sherpa.sdk.validate" in components


def test_evaluator_scores_one_finite_target_through_the_versioned_registry() -> None:
    node = RegressionEvaluatorV2Node("score", {})
    result = node.score_held_out_predictions([[1.0], [3.0]], np.array([1.5, 2.5]))

    assert result.registry_version == "2"
    assert result.n_samples == 2
    assert result.rmse == pytest.approx(0.5)
    assert result.mae == pytest.approx(0.5)
    assert result.bias == pytest.approx(0.0)


def test_local_evaluator_emits_the_complete_regression_metric_vector() -> None:
    result = evaluate_regression_v2(
        predictions=np.array([1.5, 2.0, 4.0, 7.5]),
        held_out_target=np.array([1.0, 3.0, 5.0, 7.0]),
    )

    metrics = result.outputs["default"]
    assert set(metrics) == {
        "task_type",
        "registry_version",
        "n_samples",
        "rmse",
        "mae",
        "bias",
        "r2",
        "sep",
        "slope",
        "intercept",
        "rer",
    }
    assert metrics["task_type"] == "regression"
    assert metrics["registry_version"] == "2"
    assert result.diagnostics["target_names"] == ["Target 1"]
    for key in ("n_samples", "rmse", "mae", "bias", "r2", "sep", "slope", "intercept", "rer"):
        assert result.diagnostics[key] == metrics[key]


def test_local_evaluator_preserves_the_selected_response_label() -> None:
    node = RegressionEvaluatorV2Node("score", {"target_names": ["Carbon dioxide"]})

    result = asyncio.run(node.execute([[1.5], [2.5]], [[1.0], [3.0]]))

    comparison = result.outputs["comparison"]
    assert comparison["metadata"]["target_names"] == ["Carbon dioxide"]
    assert {row["target"] for row in comparison["data"]} == {"Carbon dioxide"}


def test_evaluator_generated_projection_reuses_the_live_metric_authority() -> None:
    node = RegressionEvaluatorV2Node("score", {"target_names": ["Carbon dioxide"]})
    code = "\n".join(node.generate_python({"default": "predictions", "y_true": "observed"}, indent=""))

    assert "evaluate_regression_v2" in code
    assert "predictions, observed" in code
    assert "target_names=['Carbon dioxide']" in code
    namespace = {
        "predictions": np.array([1.5, 2.5]),
        "observed": np.array([1.0, 3.0]),
        "results": {},
    }
    exec(compile(code, "<regression-evaluator-v2>", "exec"), namespace)
    assert namespace["results"]["score"]["default"]["rmse"] == pytest.approx(0.5)


def test_evaluator_rejects_categorical_targets_instead_of_guessing_a_classification_contract() -> None:
    node = RegressionEvaluatorV2Node("score", {})

    with pytest.raises((TypeError, ValueError)):
        node.score_held_out_predictions(["low", "high"], ["low", "high"])


def test_private_accumulator_pools_folds_without_averaging_fold_r2() -> None:
    accumulator = RegressionMetricAccumulator()
    accumulator.add(np.array([0.0, 10.0]), np.array([0.0, 8.0]))
    accumulator.add(np.array([20.0, 30.0]), np.array([22.0, 30.0]))

    pooled = accumulator.metrics()

    assert pooled.n_samples == 4
    assert pooled.rmse == pytest.approx(np.sqrt(2.0))
    assert pooled.mae == pytest.approx(1.0)
    assert pooled.bias == pytest.approx(0.0)
    assert pooled.r2 == pytest.approx(0.984)


def test_private_accumulator_matches_the_registry_for_nonconstant_data() -> None:
    observed = np.array([-3.0, -1.0, 0.5, 2.0, 9.0, 12.0])
    predicted = np.array([-2.5, -1.5, 0.0, 2.5, 8.0, 13.0])
    accumulator = RegressionMetricAccumulator()
    accumulator.add(observed[:2], predicted[:2])
    accumulator.add(observed[2:5], predicted[2:5])
    accumulator.add(observed[5:], predicted[5:])

    assert compare_metric_parity(metrics(observed, predicted), accumulator.metrics()).matches


def test_private_accumulator_retains_undefined_r2_for_a_constant_target() -> None:
    observed = np.full(4, 7.0)
    predicted = np.array([6.0, 7.5, 6.5, 7.0])
    accumulator = RegressionMetricAccumulator()
    accumulator.add(observed[:2], predicted[:2])
    accumulator.add(observed[2:], predicted[2:])

    assert accumulator.metrics() == metrics(observed, predicted)


def test_private_accumulator_stays_stable_for_large_offset_low_variance_targets() -> None:
    # Reference variation remains resolvable despite a huge common offset.
    observed = 1.0e12 + np.array([0.0, 2.0e7, 4.0e7, 6.0e7, 8.0e7, 1.0e8])
    predicted = observed + np.array([5.0e5, -5.0e5, 5.0e5, -5.0e5, 5.0e5, -5.0e5])
    accumulator = RegressionMetricAccumulator()
    accumulator.add(observed[:2], predicted[:2])
    accumulator.add(observed[2:4], predicted[2:4])
    accumulator.add(observed[4:], predicted[4:])

    actual = accumulator.metrics()
    assert actual.r2 is not None
    assert compare_metric_parity(metrics(observed, predicted), actual).matches


def test_local_evaluator_scores_pls2_responses_without_blending_scales() -> None:
    result = evaluate_regression_v2(
        [[1.1, 101.0], [1.9, 198.0], [3.2, 303.0]],
        [[1.0, 100.0], [2.0, 200.0], [3.0, 300.0]],
        target_names=["minor", "major"],
    )

    metric_set = result.outputs["default"]
    assert metric_set["schema_version"] == "spectrasherpa-regression-metric-set/1"
    assert metric_set["aggregation"] == "none"
    assert metric_set["n_targets"] == 2
    assert [item["target"] for item in metric_set["targets"]] == ["minor", "major"]
    assert metric_set["targets"][0]["metrics"]["rmse"] != metric_set["targets"][1]["metrics"]["rmse"]
    assert result.outputs["comparison"]["metadata"]["target_names"] == ["minor", "major"]
    assert len(result.outputs["comparison"]["data"]) == 6


def test_managed_evaluator_requires_one_explicitly_selected_response() -> None:
    node = RegressionEvaluatorV2Node("score", {})

    with pytest.raises(ValueError, match="one selected target"):
        node.score_held_out_predictions([[1.0, 2.0]], [[1.0, 2.0]])


def test_evaluator_rejects_nonfinite_values() -> None:
    with pytest.raises(ValueError, match="finite"):
        evaluate_regression_v2([[1.0]], [[float("nan")]])


@pytest.mark.asyncio
async def test_evaluator_refuses_unscoped_node_execution() -> None:
    with pytest.raises(RuntimeError, match="canonical fold lifecycle authority"):
        await RegressionEvaluatorV2Node("score", {}).execute([[1.0]])
