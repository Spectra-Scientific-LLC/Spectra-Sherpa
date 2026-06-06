"""Curated scalar run metrics for history and comparison views."""

from __future__ import annotations

from math import isfinite
from typing import Any

from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.schemas.execution_runs import ComparisonResponse, ExecutionRunOut
from spectra_sherpa.app.services.dag.nodes.classification.core_utils import flatten_classification_metrics_contract

COMPARABLE_METRIC_KEYS = {
    "accuracy",
    "accuracy_test",
    "balanced_accuracy",
    "best_interval",
    "best_k",
    "best_rmsecv",
    "cumulative_variance",
    "cv_accuracy",
    "cv_balanced_accuracy",
    "cv_f1_macro",
    "cv_precision_macro",
    "cv_recall_macro",
    "cv_sensitivity_macro",
    "cv_specificity_macro",
    "explained_variance",
    "explained_variance_ratio",
    "f1",
    "f1_macro",
    "f1_score",
    "global_rmsecv",
    "inertia",
    "bias",
    "mae",
    "mean_n_selected",
    "mse",
    "n_classes",
    "n_clusters",
    "n_components",
    "n_iterations_run",
    "n_outliers",
    "n_selected",
    "precision",
    "precision_macro",
    "q2",
    "q_residuals",
    "r2",
    "r2_cv",
    "r2_test",
    "recall",
    "recall_macro",
    "reconstruction_error",
    "rmse",
    "rmsecv",
    "rmse_test",
    "rer",
    "selection_stability",
    "sep",
    "silhouette_score",
    "sensitivity_macro",
    "specificity_macro",
    "test_accuracy",
    "test_balanced_accuracy",
    "test_f1_macro",
    "test_precision_macro",
    "test_recall_macro",
    "test_sensitivity_macro",
    "test_specificity_macro",
    "train_accuracy",
    "train_balanced_accuracy",
    "train_f1_macro",
    "train_precision_macro",
    "train_recall_macro",
    "train_sensitivity_macro",
    "train_specificity_macro",
}

COMPARABLE_NESTED_KEYS = {
    "default",
    "diagnostics",
    "evaluation",
    "meta",
    "metadata",
    "metrics",
    "cv_metrics",
    "quality_summary",
}

AMBIGUOUS_CLASSIFICATION_KEYS = {
    "accuracy",
    "balanced_accuracy",
    "f1",
    "f1_macro",
    "f1_score",
    "precision",
    "precision_macro",
    "recall",
    "recall_macro",
    "sensitivity_macro",
    "specificity_macro",
}

CLASSIFICATION_SPLIT_METRIC_KEYS = {
    key
    for split in ("train", "cv", "test")
    for key in (
        f"{split}_accuracy",
        f"{split}_balanced_accuracy",
        f"{split}_f1_macro",
        f"{split}_precision_macro",
        f"{split}_recall_macro",
        f"{split}_sensitivity_macro",
        f"{split}_specificity_macro",
    )
}

LEGACY_METRIC_ALIASES = {
    "accuracy_test": "test_accuracy",
    "f1_score": "f1_macro",
    "MAE": "mae",
    "Q2": "q2",
    "RMSE": "rmse",
    "RMSECV": "rmsecv",
    "RMSEP": "rmse_test",
    "SEP": "sep",
    "RER": "rer",
}

REGRESSION_CONTEXT_ALIASES = {
    "cv": {
        "r2": "r2_cv",
        "R2": "r2_cv",
        "RMSE": "rmsecv",
        "RMSECV": "rmsecv",
    },
    "test": {
        "r2": "r2_test",
        "R2": "r2_test",
        "RMSE": "rmse_test",
        "RMSEP": "rmse_test",
    },
}

METRIC_COMPARE_PRIORITY = [
    "cv_balanced_accuracy",
    "test_accuracy",
    "accuracy_test",
    "test_balanced_accuracy",
    "cv_accuracy",
    "balanced_accuracy",
    "accuracy",
    "train_accuracy",
    "train_balanced_accuracy",
    "cv_f1_macro",
    "f1_macro",
    "f1",
    "cv_sensitivity_macro",
    "cv_specificity_macro",
    "cv_precision_macro",
    "cv_recall_macro",
    "test_f1_macro",
    "test_sensitivity_macro",
    "test_specificity_macro",
    "train_f1_macro",
    "train_sensitivity_macro",
    "train_specificity_macro",
    "train_precision_macro",
    "train_recall_macro",
    "precision",
    "recall",
    "r2_cv",
    "q2",
    "r2_test",
    "r2",
    "rmsecv",
    "rmse_test",
    "rmse",
    "mae",
    "bias",
    "sep",
    "rer",
    "best_rmsecv",
    "global_rmsecv",
    "selection_stability",
    "n_selected",
    "silhouette_score",
    "n_clusters",
    "inertia",
    "explained_variance_ratio",
    "cumulative_variance",
    "reconstruction_error",
    "n_outliers",
    "n_components",
]


def collect_comparable_metric_scalars(
    value: Any,
    out: dict[str, Any],
    *,
    depth: int = 0,
    classification_context: bool = False,
    regression_context: str | None = None,
) -> None:
    """Collect only scientist-facing scalar metrics from a nested result payload."""
    if depth > 5 or not isinstance(value, dict):
        return

    canonical = flatten_classification_metrics_contract(value)
    if canonical:
        out.update({key: val for key, val in canonical.items() if key not in out})
        return

    has_canonical_child = bool(CLASSIFICATION_SPLIT_METRIC_KEYS.intersection(out))
    for child_key in ("metrics", "classification_metrics"):
        child = value.get(child_key)
        if isinstance(child, dict):
            child_metrics = flatten_classification_metrics_contract(child)
            if child_metrics:
                out.update({key: val for key, val in child_metrics.items() if key not in out})
                has_canonical_child = True

    suppress_ambiguous_classification = classification_context or has_canonical_child
    local_regression_context = _infer_regression_context(value) or regression_context
    for key, candidate in value.items():
        if suppress_ambiguous_classification and key in AMBIGUOUS_CLASSIFICATION_KEYS:
            continue
        metric_key = _canonical_metric_key(key, local_regression_context)
        if metric_key in COMPARABLE_METRIC_KEYS and isinstance(candidate, (int, float)) and isfinite(float(candidate)):
            out.setdefault(metric_key, candidate)
    for key in COMPARABLE_NESTED_KEYS:
        nested = value.get(key)
        if isinstance(nested, dict):
            collect_comparable_metric_scalars(
                nested,
                out,
                depth=depth + 1,
                classification_context=suppress_ambiguous_classification,
                regression_context=local_regression_context,
            )


def _canonical_metric_key(key: str, regression_context: str | None) -> str:
    if regression_context:
        context_alias = REGRESSION_CONTEXT_ALIASES.get(regression_context, {}).get(key)
        if context_alias:
            return context_alias
    if key == "R2":
        return "r2"
    return LEGACY_METRIC_ALIASES.get(key, key)


def _infer_regression_context(value: dict[str, Any]) -> str | None:
    type_value = value.get("type")
    metadata = value.get("metadata")
    if not isinstance(type_value, str) and isinstance(metadata, dict):
        type_value = metadata.get("type")
    if type_value == "RegressionCV":
        return "cv"
    if type_value == "RegressionTest":
        return "test"
    return None


def comparable_results_by_node(results_summary: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    comparable: dict[str, dict[str, Any]] = {}
    for node_id, raw_metrics in (results_summary or {}).items():
        metrics: dict[str, Any] = {}
        collect_comparable_metric_scalars(raw_metrics, metrics)
        if metrics:
            comparable[str(node_id)] = metrics
    return comparable


def comparable_results_for_run(results_summary: dict[str, Any] | None) -> dict[str, Any]:
    """Collapse run metrics for cross-run comparison without silent first-wins.

    Most workflows expose one terminal model node, so metric rows should remain
    unqualified (``cv_accuracy``, ``rmse``). When a run contains multiple nodes
    emitting the same metric key, prefix only those conflicting rows with the
    producing node id. That preserves node provenance without making the common
    one-model comparison noisy.
    """
    by_node = comparable_results_by_node(results_summary)
    collapsed: dict[str, Any] = {}
    keys = sorted({key for metrics in by_node.values() for key in metrics})
    for key in keys:
        entries = [(node_id, metrics[key]) for node_id, metrics in by_node.items() if key in metrics]
        if not entries:
            continue
        first_value = entries[0][1]
        if len(entries) == 1 or all(_metric_values_equal(first_value, value) for _, value in entries[1:]):
            collapsed[key] = first_value
            continue
        for node_id, value in entries:
            collapsed[f"{node_id}.{key}"] = value
    return collapsed


def _metric_values_equal(left: Any, right: Any) -> bool:
    """Return True when duplicate node metrics are semantically identical."""
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return isfinite(float(left)) and isfinite(float(right)) and float(left) == float(right)
    return left == right


def comparison_response(runs: list[ExecutionRun]) -> ComparisonResponse:
    comparable_by_run = {run.id: comparable_results_for_run(run.results_summary) for run in runs}
    metric_keys = sorted(
        {key for metrics in comparable_by_run.values() for key in metrics},
        key=lambda key: (
            METRIC_COMPARE_PRIORITY.index(key) if key in METRIC_COMPARE_PRIORITY else len(METRIC_COMPARE_PRIORITY),
            key,
        ),
    )

    diff: dict[str, dict[str, Any]] = {}
    for key in metric_keys:
        diff[key] = {}
        for run in runs:
            run_metrics = comparable_by_run.get(run.id, {})
            if key in run_metrics:
                diff[key][str(run.id)] = run_metrics[key]

    return ComparisonResponse(
        runs=[ExecutionRunOut.model_validate(run) for run in runs],
        metric_keys=metric_keys,
        diff=diff,
    )
