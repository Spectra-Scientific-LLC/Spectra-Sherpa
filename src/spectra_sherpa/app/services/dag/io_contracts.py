"""Shared IO contract helpers for DAG nodes.

Phase 1 objective:
- Standardize X/y input binding and legacy port fallback.
- Standardize conversion to SherpaDataset / numpy arrays.
- Standardize output dataset wrapping with metadata preservation.

These helpers are intentionally lightweight so imperative nodes can opt in
incrementally without changing business logic.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.scp_compat import HAS_SCP, NDDataset
from spectra_sherpa.app.lib.sherpa_dataset import EvaluationResult, Provenance, SherpaDataset

from .meta_helpers import safe_get_coord


def _is_dataset_like(value: Any) -> bool:
    """Return True for dataset containers (SherpaDataset or NDDataset)."""
    if isinstance(value, SherpaDataset):
        return True
    if HAS_SCP and isinstance(value, NDDataset):
        return True
    return False


def resolve_legacy_input(value: Any, kwargs: dict[str, Any], key: str) -> Any:
    """Apply legacy positional-via-kwargs fallback (e.g. input_0, input_1)."""
    if value is None and key in kwargs:
        return kwargs[key]
    return value


def coerce_to_sherpa(
    value: Any,
    *,
    input_name: str = "input",
    allow_array: bool = False,
    dataset_error_message: str | None = None,
) -> SherpaDataset:
    """
    Coerce a value to SherpaDataset.

    Args:
        value: Input value.
        input_name: Logical input name for error messages.
        allow_array: If True, wraps array-like input into SherpaDataset.
        dataset_error_message: Optional custom error message.
    """
    if isinstance(value, SherpaDataset):
        return value

    if HAS_SCP and isinstance(value, NDDataset):
        from spectra_sherpa.app.lib.adapters.scp_adapter import from_nddataset

        return from_nddataset(value)

    if allow_array:
        arr = np.asarray(value, dtype=np.float64)
        if arr.ndim == 0:
            err = dataset_error_message or (
                f"{input_name} must be dataset-like or array-like with at least 1 dimension"
            )
            raise ValueError(err)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        return SherpaDataset(X=arr, backend="numpy")

    err = dataset_error_message or (f"{input_name} must be an NDDataset or SherpaDataset object")
    raise ValueError(err)


def bind_X(
    X: Any,
    kwargs: dict[str, Any],
    *,
    missing_message: str = "Missing required input: X",
    dataset_error_message: str = "X must be an NDDataset or SherpaDataset object",
    allow_array: bool = False,
) -> SherpaDataset:
    """Bind and normalize the X input (with legacy input_0 fallback)."""
    X = resolve_legacy_input(X, kwargs, "input_0")
    if X is None:
        raise ValueError(missing_message)
    return coerce_to_sherpa(
        X,
        input_name="X",
        allow_array=allow_array,
        dataset_error_message=dataset_error_message,
    )


def _has_values(value: Any) -> bool:
    """Return True when value is array-like and non-empty."""
    if value is None:
        return False
    try:
        arr = np.asarray(value)
        return arr.size > 0
    except Exception:
        return False


def extract_target_like(dataset: Any) -> Any | None:
    """
    Extract target/label vector from a dataset.

    Priority:
    1. dataset.target
    2. dataset.y.labels
    3. dataset.y.data
    """
    target = getattr(dataset, "target", None)
    if _has_values(target):
        return target

    if isinstance(dataset, SherpaDataset):
        sample_axis = dataset.sample_axis
        if sample_axis is None:
            return None
        if _has_values(sample_axis.labels):
            return sample_axis.labels
        if _has_values(sample_axis.values):
            return sample_axis.values
        return None

    y_coord = safe_get_coord(dataset, "y")
    if y_coord is None:
        return None

    labels = getattr(y_coord, "labels", None)
    if _has_values(labels):
        return labels

    y_data = getattr(y_coord, "data", None)
    if _has_values(y_data):
        return y_data

    return None


def bind_y(
    y: Any,
    kwargs: dict[str, Any],
    *,
    X: SherpaDataset | None = None,
    required: bool = False,
    infer_from_X: bool = True,
    dataset_as_data: bool = False,
    missing_message: str = "Missing required input: y",
    dataset_missing_message: str = (
        "Dataset passed to y port has no embedded labels. " "Use target or y-axis labels/data."
    ),
) -> Any:
    """
    Bind and normalize y input (with legacy input_1 fallback).

    - If y is omitted and infer_from_X=True, attempts extraction from X.
    - If y is a dataset and dataset_as_data=True, returns y.data.
    - If y is a dataset and dataset_as_data=False, extracts target/labels.
    - Otherwise returns y unchanged.
    """
    y = resolve_legacy_input(y, kwargs, "input_1")

    if y is None and infer_from_X and X is not None:
        inferred = extract_target_like(X)
        if inferred is not None:
            return inferred

    if y is None:
        if required:
            raise ValueError(missing_message)
        return None

    if _is_dataset_like(y):
        y_dataset = coerce_to_sherpa(y, input_name="y", allow_array=False)
        if dataset_as_data:
            return y_dataset.data
        inferred = extract_target_like(y_dataset)
        if inferred is None:
            raise ValueError(dataset_missing_message)
        return inferred

    return y


def to_numpy_2d(
    value: Any,
    *,
    name: str = "input",
    dtype: Any = np.float64,
) -> np.ndarray:
    """Convert input to a 2D numpy array (1D inputs are reshaped to column vectors)."""
    raw = value.data if isinstance(value, SherpaDataset) else value
    arr = np.asarray(raw, dtype=dtype)

    if arr.ndim == 0:
        raise ValueError(f"{name} must be 1D or 2D array-like, got scalar")
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    if arr.ndim != 2:
        raise ValueError(f"{name} must be 1D or 2D array-like, got {arr.ndim}D")
    return arr


def to_numpy_1d(
    value: Any,
    *,
    name: str = "input",
    expected_length: int | None = None,
    dtype: Any | None = None,
) -> np.ndarray:
    """Convert input to a flattened 1D numpy array."""
    raw = value.data if isinstance(value, SherpaDataset) else value
    arr = np.asarray(raw, dtype=dtype) if dtype is not None else np.asarray(raw)

    if arr.ndim == 0:
        arr = arr.reshape(1)
    arr = arr.reshape(-1)

    if expected_length is not None and arr.shape[0] != expected_length:
        raise ValueError(f"{name} must have {expected_length} samples, got {arr.shape[0]}")
    return arr


def build_dataset_like(
    data: Any,
    source: Any,
    *,
    units: str | None = None,
    title: str | None = None,
    backend: str | None = None,
    copy_history: bool = True,
) -> SherpaDataset:
    """
    Wrap numeric output as SherpaDataset while preserving source metadata.
    """
    src = coerce_to_sherpa(source, input_name="source", allow_array=True)
    arr = np.asarray(data, dtype=np.float64)
    if arr.ndim == 0:
        raise ValueError("data must be 1D or 2D array-like, got scalar")
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    if arr.ndim != 2:
        raise ValueError(f"data must be 1D or 2D array-like, got {arr.ndim}D")

    spectral_axis = src.spectral_axis.copy() if src.spectral_axis is not None else None
    sample_axis = src.sample_axis.copy() if src.sample_axis is not None else None
    target = copy.deepcopy(src.target) if src.target is not None else None

    # If shape changed, keep only compatible metadata.
    if spectral_axis is not None and spectral_axis.length > 0 and spectral_axis.length != arr.shape[1]:
        spectral_axis = None
    if sample_axis is not None and sample_axis.length > 0 and sample_axis.length != arr.shape[0]:
        sample_axis = None
    if target is not None and np.asarray(target).shape[0] != arr.shape[0]:
        target = None

    result = SherpaDataset(
        X=arr,
        spectral_axis=spectral_axis,
        sample_axis=sample_axis,
        target=target,
        target_context=src.target_context.model_copy(deep=True),
        domain=src.domain.model_copy(deep=True),
        provenance=(src.provenance.copy() if copy_history else Provenance()),
        quality=src.quality.model_copy(deep=True),
        backend=backend or src.backend,
        title=src.title if title is None else title,
        units=src.units if units is None else units,
        extra=copy.deepcopy(src.extra),
    )

    return result


def attach_evaluation(
    dataset: SherpaDataset,
    evaluation: EvaluationResult,
) -> None:
    """Attach an EvaluationResult to a dataset's quality metrics.

    Mutates the dataset in place.
    """
    dataset.quality.add_evaluation(evaluation)
