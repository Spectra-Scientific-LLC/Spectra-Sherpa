"""One canonical class-label authority for split, fit, apply, and evaluation."""

from __future__ import annotations

import re
from typing import Any

import numpy as np


def normalize_class_label_value(value: Any) -> str:
    """Normalize one raw class label into a stable, human-readable token."""

    if isinstance(value, np.generic):
        value = value.item()
    if value is None:
        return ""
    if isinstance(value, np.ndarray):
        return normalize_class_label_value(value.tolist())
    if isinstance(value, (list, tuple)):
        # Composite labels may pair acquisition identity with a scientist-facing
        # class name. The readable trailing string is the categorical value;
        # otherwise retain every non-empty component.
        for item in reversed(value):
            if isinstance(item, str) and item.strip():
                return item.strip()
        parts = [normalize_class_label_value(item) for item in value]
        parts = [part for part in parts if part]
        return parts[0] if len(parts) == 1 else " | ".join(parts)
    if isinstance(value, dict):
        for key in ("label", "name"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return str(value)
    if isinstance(value, str):
        trimmed = value.strip()
        if trimmed.startswith(("[", "(")):
            quoted = re.findall(r"'([^']+)'|\"([^\"]+)\"", trimmed)
            if quoted:
                return str(quoted[-1][0] or quoted[-1][1])
        return trimmed
    return str(value)


def normalize_class_label_vector(raw_labels: Any, n_samples: int) -> np.ndarray:
    """Return exactly one canonical string label for every sample."""

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
    elif n_samples > 0 and labels_obj.shape[0] == n_samples:
        labels = [normalize_class_label_value(row.tolist()) for row in labels_obj]
    elif n_samples > 0 and labels_obj.size == n_samples:
        labels = [normalize_class_label_value(item) for item in labels_obj.reshape(-1).tolist()]
    else:
        labels = [normalize_class_label_value(item) for item in labels_obj.reshape(-1).tolist()]
    return np.asarray(labels, dtype=object)


def prepare_class_labels(raw_labels: Any, n_samples: int) -> np.ndarray:
    """Build a finite, non-empty class-label vector aligned to sample count."""

    raw_values = np.asarray(raw_labels, dtype=object).reshape(-1).tolist()
    if any(
        not np.isfinite(value)
        for value in raw_values
        if not isinstance(value, (bool, np.bool_)) and isinstance(value, (int, float, np.integer, np.floating))
    ):
        raise ValueError("Class labels contain non-finite numeric values.")
    labels = normalize_class_label_vector(raw_labels, n_samples)
    if labels.shape[0] != n_samples:
        raise ValueError(
            f"X and y must have the same number of samples (X={n_samples}, y={labels.shape[0]}). "
            "If labels came from dataset coordinates, ensure one class label exists per sample."
        )
    if any(str(label).strip() == "" for label in labels):
        raise ValueError("Class labels contain empty values. Please provide one non-empty class label per sample.")
    return labels


def prepare_declared_class_labels(
    raw_labels: Any,
    n_samples: int,
    *,
    selected_target: str | None = None,
    target_names: list[str] | None = None,
) -> np.ndarray:
    """Select an explicit categorical response before canonical label projection."""

    values = np.asarray(raw_labels)
    if selected_target:
        names = list(target_names or [])
        if selected_target not in names:
            raise ValueError("selected categorical target is absent from target_names")
        if values.ndim == 2:
            if values.shape[1] != len(names):
                raise ValueError("categorical target metadata does not name every target column")
            values = values[:, names.index(selected_target)]
    elif values.ndim == 2 and values.shape[1] > 1:
        raise ValueError("multi-column categorical target requires a selected_target")
    scalar_domains: set[str] = set()
    for value in np.asarray(values, dtype=object).reshape(-1).tolist():
        if isinstance(value, (bool, np.bool_)):
            scalar_domains.add("boolean")
        elif isinstance(value, (int, float, np.integer, np.floating)):
            scalar_domains.add("numeric")
        elif isinstance(value, str):
            scalar_domains.add("text")
        elif value is not None:
            scalar_domains.add("structured")
    if len(scalar_domains) > 1:
        raise ValueError("categorical target mixes source label domains; declare one unambiguous domain")
    return prepare_class_labels(values, n_samples)


__all__ = [
    "normalize_class_label_value",
    "normalize_class_label_vector",
    "prepare_class_labels",
    "prepare_declared_class_labels",
]
