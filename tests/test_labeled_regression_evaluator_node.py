"""Workbench sample custody without changing the frozen managed evaluator."""

import asyncio

import numpy as np
import pytest

from spectra_sherpa.app.services.dag.nodes.labeled_regression_evaluator_node import (
    LabeledRegressionEvaluatorNode,
    evaluate_labeled_regression,
)


def _sample_context():
    from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, TargetContext

    return SherpaDataset(
        np.eye(3),
        target=np.array([2.0, 5.0, 9.0]),
        sample_axis=SampleAxis(labels=["fuel-C", "fuel-A", "fuel-B"]),
        target_context=TargetContext(target_names=["response"], target_type="continuous"),
    )


def test_local_evaluator_preserves_context_labels_and_generated_python():
    context = _sample_context()
    predicted = np.array([2.2, 4.7, 8.9])
    node = LabeledRegressionEvaluatorNode("evaluate", {"target_names": ["response"]})
    actual = asyncio.run(node.execute(predicted, context.target, sample_context=context)).outputs
    rows = actual["comparison"]["data"]
    assert [row["sample"] for row in rows] == ["fuel-C", "fuel-A", "fuel-B"]
    assert actual["comparison"]["metadata"]["sample_identity_mode"] == "source_label"
    scope = {"prediction": predicted, "truth": context.target, "context": context, "results": {}}
    code = "\n".join(
        node.generate_python({"default": "prediction", "y_true": "truth", "sample_context": "context"}, indent="")
    )
    exec(code, scope)
    assert scope["results"]["evaluate"] == actual


@pytest.mark.parametrize("bad", ["rows", "reordered_target", "names", "missing_target", "missing_labels"])
def test_local_evaluator_refuses_misbound_sample_context(bad):
    context = _sample_context()
    truth = context.target.copy()
    if bad == "rows":
        context = context[:2]
    elif bad == "reordered_target":
        context.target = truth[::-1]
    elif bad == "names":
        context.target_context.target_names = ["unrelated"]
    elif bad == "missing_target":
        context.target = None
    else:
        axis = context.sample_axis
        axis.labels = None
        context.sample_axis = axis
    with pytest.raises(ValueError):
        evaluate_labeled_regression(truth, truth, sample_context=context, target_names=["response"])


@pytest.mark.parametrize("kind", ["values", "labels", "response_names"])
def test_comparison_refuses_before_shared_row_expansion(monkeypatch, kind):
    from spectra_sherpa.app.services.dag.nodes import labeled_regression_evaluator_node as module

    context = _sample_context()
    truth = context.target
    if kind == "values":
        truth = np.ones((30_000, 2))
    elif kind == "labels":
        axis = context.sample_axis
        axis.labels = ["x" * 800_000] * 3
        context.sample_axis = axis
    else:
        context.target_context.target_names = ["y" * 800_000]

    def forbidden(*args, **kwargs):
        pytest.fail("comparison expansion must not run for excessive input")

    monkeypatch.setattr(module.canonical_evaluator, "evaluate_regression_v2", forbidden)
    with pytest.raises(ValueError, match="display limit"):
        evaluate_labeled_regression(truth, truth, sample_context=context)


def test_labeled_operation_is_not_a_managed_baseline():
    payload = LabeledRegressionEvaluatorNode.metadata.resolved_execution_contract().payload
    assert payload["managed_optimization_eligibility"] == ("local",)


def test_duplicate_source_labels_preserve_row_order():
    context = _sample_context()
    axis = context.sample_axis
    axis.labels = ["replicate", "replicate", "other"]
    context.sample_axis = axis
    output = evaluate_labeled_regression(context.target, context.target, sample_context=context).outputs["comparison"]
    assert [row["sample"] for row in output["data"]] == ["replicate", "replicate", "other"]
    assert [row["reference"] for row in output["data"]] == [2.0, 5.0, 9.0]


def test_labeled_operation_is_absent_from_managed_profile():
    from spectra_sherpa.app.services.dag.managed_optimization_profile import managed_optimization_profile

    assert "diagnostics.labeled_regression_evaluator" not in managed_optimization_profile().operation_ids


def test_labeled_evaluator_retains_canonical_metrics():
    from spectra_sherpa.app.services.canonical_metric_retention import project_canonical_metric_evidence

    context = _sample_context()
    evaluated = evaluate_labeled_regression(context.target, context.target, sample_context=context)
    retained = project_canonical_metric_evidence(
        {"score": evaluated.outputs},
        {"nodes": [{"node_id": "score", "node_type": "diagnostics.labeled_regression_evaluator"}]},
    )
    assert retained["score"]["canonical_metrics"] == {
        key: value for key, value in evaluated.outputs["default"].items() if key != "task_type"
    }
