"""One fitted-state identity for feature-axis coordinates and semantics."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np

from spectra_sherpa.core.axis_semantics import AxisQuantity, axis_semantics

FeatureAxisIdentity = tuple[str | None, str | None, str | None, str | None]


def feature_axis_identity(dataset: Any, *, features: int, context: str) -> FeatureAxisIdentity:
    """Return coordinate, label, unit, and physical-quantity identity."""

    feature_axis = getattr(dataset, "feature_axis", None)
    values = None if feature_axis is None else getattr(feature_axis, "values", None)
    labels = None if feature_axis is None else getattr(feature_axis, "labels", None)
    units = None if feature_axis is None else getattr(feature_axis, "units", None)
    title = None if feature_axis is None else getattr(feature_axis, "title", None)
    quantity = None if feature_axis is None else getattr(feature_axis, "quantity", None)
    values_digest = None
    if values is not None:
        axis = np.asarray(values, dtype="<f8")
        if axis.shape != (features,) or not np.isfinite(axis).all():
            raise ValueError(f"{context} feature axis must be a finite vector matching the feature count")
        values_digest = hashlib.sha256(axis.tobytes(order="C")).hexdigest()
    labels_digest = None
    if labels is not None:
        if not isinstance(labels, list) or len(labels) != features or not all(isinstance(item, str) for item in labels):
            raise ValueError(f"{context} feature-axis labels must match the feature count")
        labels_digest = hashlib.sha256(
            json.dumps(labels, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    semantics = axis_semantics(
        axis_class=type(feature_axis).__name__ if feature_axis is not None else "FeatureAxis",
        title=title,
        units=units,
        quantity=quantity,
    )
    return (
        values_digest,
        labels_digest,
        semantics.units,
        None if semantics.quantity is None else semantics.quantity.value,
    )


def validated_axis_quantity(value: object, *, context: str) -> str | None:
    """Validate a serialized optional quantity against the closed vocabulary."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{context} state has invalid feature_axis_quantity")
    try:
        return AxisQuantity(value).value
    except ValueError as exc:
        raise ValueError(f"{context} state has invalid feature_axis_quantity") from exc


__all__ = ["FeatureAxisIdentity", "feature_axis_identity", "validated_axis_quantity"]
