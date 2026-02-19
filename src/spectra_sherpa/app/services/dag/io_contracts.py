"""
Shared IO contract helpers for DAG nodes.

Phase 1 objective:
- Standardize X/y input binding and legacy port fallback.
- Standardize conversion to AnalysisDataset / numpy arrays.
- Standardize output dataset wrapping with metadata preservation.

These helpers are intentionally lightweight so imperative nodes can opt in
incrementally without changing business logic.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.analysis_dataset import AnalysisDataset
from spectra_sherpa.app.lib.scp_compat import HAS_SCP, NDDataset, from_nddataset

from .meta_helpers import copy_processing_history, safe_get_coord


def _is_dataset_like(value: Any) -> bool:
    """Return True for AnalysisDataset (and NDDataset when SCP is available)."""
    if isinstance(value, AnalysisDataset):
        return True
    if HAS_SCP and isinstance(value, NDDataset):
        return True
    return False


def resolve_legacy_input(value: Any, kwargs: dict[str, Any], key: str) -> Any:
    """Apply legacy positional-via-kwargs fallback (e.g. input_0, input_1)."""
    if value is None and key in kwargs:
        return kwargs[key]
    return value


def coerce_dataset(
    value: Any,
    *,
    input_name: str = "input",
    allow_array: bool = False,
    dataset_error_message: str | None = None,
) -> AnalysisDataset:
    """
    Coerce a value to AnalysisDataset.

    Args:
        value: Input value.
        input_name: Logical input name for error messages.
        allow_array: If True, wraps array-like input into AnalysisDataset.
        dataset_error_message: Optional custom error message.
    """
    if isinstance(value, AnalysisDataset):
        return value

    if HAS_SCP and isinstance(value, NDDataset):
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
        return AnalysisDataset(X=arr, backend="numpy")

    err = dataset_error_message or (f"{input_name} must be an NDDataset or AnalysisDataset object")
    raise ValueError(err)


def bind_X(
    X: Any,
    kwargs: dict[str, Any],
    *,
    missing_message: str = "Missing required input: X",
    dataset_error_message: str = "X must be an NDDataset or AnalysisDataset object",
    allow_array: bool = False,
) -> AnalysisDataset:
    """Bind and normalize the X input (with legacy input_0 fallback)."""
    X = resolve_legacy_input(X, kwargs, "input_0")
    if X is None:
        raise ValueError(missing_message)
    return coerce_dataset(
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


def extract_target_like(dataset: AnalysisDataset) -> Any | None:
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
    X: AnalysisDataset | None = None,
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
        y_dataset = coerce_dataset(y, input_name="y", allow_array=False)
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
    raw = value.data if isinstance(value, AnalysisDataset) else value
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
    raw = value.data if isinstance(value, AnalysisDataset) else value
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
) -> AnalysisDataset:
    """
    Wrap numeric output as AnalysisDataset while preserving source metadata.
    """
    src = coerce_dataset(source, input_name="source", allow_array=True)
    meta = copy.deepcopy(src.meta) if isinstance(src.meta, dict) else {}
    if not copy_history:
        meta.pop("processing_history", None)

    result = AnalysisDataset(
        X=np.asarray(data, dtype=np.float64),
        target=copy.deepcopy(getattr(src, "target", None)),
        meta=meta,
        backend=backend or src.backend,
    )

    x_coord = safe_get_coord(src, "x")
    if x_coord is not None:
        result.x = x_coord.copy()

    y_coord = safe_get_coord(src, "y")
    if y_coord is not None:
        result.y = y_coord.copy()

    result.title = src.title if title is None else title
    result.units = src.units if units is None else units

    if copy_history:
        copy_processing_history(src, result)

    return result
