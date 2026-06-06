"""Shared helpers for classification nodes (PLSDA, KNN, SIMCA)."""

from __future__ import annotations

import re
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import AxisInfo


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


def normalize_class_label_value(value: Any) -> str:
    """Normalize one raw class label into a stable, human-readable string."""
    if isinstance(value, np.generic):
        value = value.item()

    if value is None:
        return ""

    if isinstance(value, np.ndarray):
        return normalize_class_label_value(value.tolist())

    if isinstance(value, (list, tuple)):
        # Common case for SpectroChemPy labels:
        # [datetime(...), "ClassName"] -> use the readable trailing string.
        for item in reversed(value):
            if isinstance(item, str) and item.strip():
                return item.strip()
        normalized_parts = [normalize_class_label_value(item) for item in value]
        normalized_parts = [part for part in normalized_parts if part]
        if len(normalized_parts) == 1:
            return normalized_parts[0]
        if normalized_parts:
            return " | ".join(normalized_parts)
        return ""

    if isinstance(value, dict):
        for key in ("label", "name"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return str(value)

    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed.startswith("[") or trimmed.startswith("("):
            quoted = re.findall(r"'([^']+)'|\"([^\"]+)\"", trimmed)
            if quoted:
                return str(quoted[-1][0] or quoted[-1][1])
        return trimmed

    return str(value)


def normalize_class_label_vector(raw_labels: Any, n_samples: int) -> np.ndarray:
    """
    Normalize class labels while preserving one label per sample.

    This specifically guards against nested label structures like
    ``[[datetime, "ClassA"], [datetime, "ClassB"], ...]`` where a naive
    ``flatten()`` would incorrectly produce 2x the sample count.
    """
    labels_obj = np.asarray(raw_labels, dtype=object)

    if labels_obj.ndim == 0:
        labels = [normalize_class_label_value(labels_obj.item())]
    elif labels_obj.ndim == 1:
        if n_samples > 0 and labels_obj.size == n_samples:
            labels = [normalize_class_label_value(item) for item in labels_obj.tolist()]
        elif n_samples > 0 and labels_obj.size % n_samples == 0:
            reshaped = labels_obj.reshape(n_samples, -1)
            labels = [normalize_class_label_value(row.tolist()) for row in reshaped]
        else:
            labels = [normalize_class_label_value(item) for item in labels_obj.tolist()]
    else:
        if n_samples > 0 and labels_obj.shape[0] == n_samples:
            labels = [normalize_class_label_value(row.tolist()) for row in labels_obj]
        elif n_samples > 0 and labels_obj.size == n_samples:
            labels = [normalize_class_label_value(item) for item in labels_obj.reshape(-1).tolist()]
        else:
            labels = [normalize_class_label_value(item) for item in labels_obj.reshape(-1).tolist()]

    return np.asarray(labels, dtype=object)


def prepare_class_labels(raw_labels: Any, n_samples: int) -> np.ndarray:
    """Build validated class-label vector aligned to X sample count."""
    y_array = normalize_class_label_vector(raw_labels, n_samples)

    if y_array.shape[0] != n_samples:
        raise ValueError(
            f"X and y must have the same number of samples (X={n_samples}, y={y_array.shape[0]}). "
            "If labels came from dataset coordinates, ensure one class label exists per sample."
        )

    if any(str(label).strip() == "" for label in y_array):
        raise ValueError("Class labels contain empty values. " "Please provide one non-empty class label per sample.")

    return y_array


def macro_specificity_score(y_true: Any, y_pred: Any, classes: Any) -> float:
    """Return one-vs-rest macro specificity for binary or multiclass labels."""
    from sklearn.metrics import confusion_matrix

    labels = np.asarray(classes)
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    total = float(cm.sum())
    if total <= 0:
        return 0.0

    values: list[float] = []
    for idx in range(len(labels)):
        tp = float(cm[idx, idx])
        fp = float(cm[:, idx].sum() - tp)
        fn = float(cm[idx, :].sum() - tp)
        tn = total - tp - fp - fn
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
