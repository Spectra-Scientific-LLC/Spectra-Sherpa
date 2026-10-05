"""Shared helpers for classification nodes (PLSDA, KNN, SIMCA)."""

from __future__ import annotations

from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import AxisInfo
from spectra_sherpa.app.services.dag.class_labels import prepare_class_labels as prepare_class_labels


def make_labeled_coord(labels: Any, title: str) -> AxisInfo:
    """
    Create an AxisInfo with string labels and a numeric index axis.

    This replaces the former SpectroChemPy Coord helper so that
    classification nodes work without SCP installed.
    """
    labels_list = [str(v) for v in (labels or [])]
    return AxisInfo(
        values=np.arange(len(labels_list), dtype=float),
        labels=labels_list,
        title=title,
    )


def coerce_numeric_array(values: Any) -> np.ndarray:
    """
    Best-effort conversion to float ndarray.

    SpectroChemPy objects can occasionally surface object/string dtypes in `.data`
    payloads. This helper converts numeric-like values to float and maps
    non-convertible entries to NaN so downstream code can handle them safely.
    """
    arr = np.asarray(values)
    if np.issubdtype(arr.dtype, np.number):
        return arr.astype(float, copy=False)

    flat = []
    for item in arr.reshape(-1):
        try:
            if isinstance(item, np.generic):
                item = item.item()
            flat.append(float(item))
        except Exception:
            flat.append(np.nan)

    return np.array(flat, dtype=float).reshape(arr.shape)


def macro_specificity_score(y_true: Any, y_pred: Any, classes: Any) -> float:
    """Return one-vs-rest macro specificity for binary or multiclass labels."""
    observed = np.asarray(y_true, dtype=object).reshape(-1)
    predicted = np.asarray(y_pred, dtype=object).reshape(-1)
    labels = np.asarray(classes, dtype=object).reshape(-1)
    if observed.shape != predicted.shape or observed.size == 0:
        return 0.0

    values: list[float] = []
    for label in labels:
        negative = observed != label
        fp = float(np.count_nonzero(negative & (predicted == label)))
        tn = float(np.count_nonzero(negative & (predicted != label)))
        denom = tn + fp
        values.append(float(tn / denom) if denom > 0 else 0.0)
    return float(np.mean(values)) if values else 0.0


def classification_scalar_metrics(y_true: Any, y_pred: Any, classes: Any, *, prefix: str = "") -> dict[str, float]:
    """
    Standard comparable classification metrics for training, CV, or test predictions.

    The prefix should be ``train_``, ``cv_``, or ``test_`` when the validation
    source matters. Sensitivity is the macro recall alias chemometricians expect.
    """
    from sklearn.metrics import (
        accuracy_score,
        f1_score,
        precision_score,
        recall_score,
    )

    labels = list(classes)
    metrics = {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "balanced_accuracy": float(recall_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)),
        "f1_macro": float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)),
        "precision_macro": float(precision_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)),
        "recall_macro": float(recall_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)),
        "sensitivity_macro": float(recall_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)),
        "specificity_macro": macro_specificity_score(y_true, y_pred, classes),
    }
    return {f"{prefix}{key}": value for key, value in metrics.items()}


CLASSIFICATION_METRIC_NAMES = (
    "accuracy",
    "balanced_accuracy",
    "f1_macro",
    "precision_macro",
    "recall_macro",
    "sensitivity_macro",
    "specificity_macro",
)


def _strip_classification_prefix(metrics: dict[str, Any] | None, split: str) -> dict[str, float]:
    """Convert ``train_accuracy``/``cv_accuracy`` style keys to canonical split metrics."""
    if not metrics:
        return {}
    prefix = f"{split}_"
    out: dict[str, float] = {}
    for name in CLASSIFICATION_METRIC_NAMES:
        candidates = (f"{prefix}{name}", name)
        for key in candidates:
            value = metrics.get(key)
            if isinstance(value, (int, float)) and np.isfinite(float(value)):
                out[name] = float(value)
                break
    return out


def classification_metrics_contract(
    *,
    classes: Any,
    train_metrics: dict[str, Any] | None = None,
    cv_metrics: dict[str, Any] | None = None,
    test_metrics: dict[str, Any] | None = None,
    primary_split: str = "cv",
    confusion_matrices: dict[str, Any] | None = None,
    method: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build the canonical classification result contract used by comparison and Sherpa guidance.

    Method-specific outputs remain available on each node, but this object gives
    every classifier a common split-aware metric vocabulary. Unqualified
    ``accuracy`` is intentionally not the source of truth because it can mean
    training, CV, or holdout accuracy depending on the node.
    """
    splits: dict[str, dict[str, float] | None] = {
        "train": _strip_classification_prefix(train_metrics, "train"),
        "cv": _strip_classification_prefix(cv_metrics, "cv"),
        "test": _strip_classification_prefix(test_metrics, "test"),
    }
    splits = {name: values for name, values in splits.items() if values}

    if primary_split not in splits:
        for candidate in ("test", "cv", "train"):
            if candidate in splits:
                primary_split = candidate
                break

    class_labels = [str(cls) for cls in np.asarray(classes).tolist()]
    contract: dict[str, Any] = {
        "schema_version": 1,
        "task_type": "classification",
        "primary_split": primary_split,
        "primary_metric": "balanced_accuracy",
        "classes": class_labels,
        "n_classes": len(class_labels),
        "splits": splits,
    }
    if method:
        contract["method"] = method
    if confusion_matrices:
        contract["confusion_matrices"] = confusion_matrices
    if extra:
        contract.update(extra)
    return contract


def flatten_classification_metrics_contract(contract: dict[str, Any]) -> dict[str, float]:
    """Flatten the canonical contract into split-qualified scalar keys for existing tables."""
    if contract.get("task_type") != "classification":
        return {}
    splits = contract.get("splits")
    if not isinstance(splits, dict):
        return {}

    out: dict[str, float] = {}
    for split, metrics in splits.items():
        if not isinstance(metrics, dict):
            continue
        for name in CLASSIFICATION_METRIC_NAMES:
            value = metrics.get(name)
            if isinstance(value, (int, float)) and np.isfinite(float(value)):
                out[f"{split}_{name}"] = float(value)

    n_classes = contract.get("n_classes")
    if isinstance(n_classes, (int, float)) and np.isfinite(float(n_classes)):
        out["n_classes"] = float(n_classes)
    return out
