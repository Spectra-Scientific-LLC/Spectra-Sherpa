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
    *,
    missing_message: str = "Missing required input: X",
    dataset_error_message: str = "X must be an NDDataset or SherpaDataset object",
    allow_array: bool = False,
) -> SherpaDataset:
    """Bind and normalize the X input."""
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


def _apply_selected_target(dataset: Any, target: Any) -> Any:
    """Slice a multi-column target down to the ``selected_target`` column.

    Returns *target* unchanged if no selection is active or if the
    target is not multi-column.
    """
    tc = getattr(dataset, "target_context", None)
    if tc is None:
        return target
    selected = getattr(tc, "selected_target", None)
    if not selected:
        return target

    target_arr = np.asarray(target)
    if target_arr.ndim < 2:
        return target  # 1D — nothing to slice

    # Match by name from target_names
    names = getattr(tc, "target_names", None)
    if names and selected in names:
        idx = list(names).index(selected)
        return target_arr[:, idx]

    return target  # name not found — return all columns


def extract_target_like(dataset: Any) -> Any | None:
    """
    Extract target/label vector from a dataset.

    If ``target_context.selected_target`` is set, extract only that
    column from a multi-target array instead of returning all columns.

    Priority:
    1. dataset.target (optionally sliced by selected_target)
    2. dataset.y.labels
    3. dataset.y.data
    """
    target = getattr(dataset, "target", None)
    if _has_values(target):
        # Honor explicit Y column selection for multi-target datasets
        target = _apply_selected_target(dataset, target)
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


def resolve_target_names(
    y_raw: Any,
    X_ds: "SherpaDataset | None" = None,
) -> list[str] | None:
    """Extract target column names from available metadata.

    Must be called **before** ``bind_y()`` which may strip dataset metadata.

    Priority:
    1. y.target_context.target_names  (if y is a SherpaDataset)
    2. y.feature_axis.labels          (if y is a SherpaDataset — property column names)
    3. X_ds.target_context.target_names
    """
    if isinstance(y_raw, SherpaDataset):
        tc = getattr(y_raw, "target_context", None)
        if tc is not None and tc.target_names:
            return list(tc.target_names)
        fa = getattr(y_raw, "feature_axis", None)
        if fa is not None and getattr(fa, "labels", None):
            return list(fa.labels)

    if X_ds is not None:
        tc = getattr(X_ds, "target_context", None)
        if tc is not None and tc.target_names:
            return list(tc.target_names)

    return None


def bind_y(
    y: Any,
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
    Bind and normalize y input.

    - If y is omitted and infer_from_X=True, attempts extraction from X.
    - If y is a dataset and dataset_as_data=True, returns y.data.
    - If y is a dataset and dataset_as_data=False, extracts target/labels.
    - Otherwise returns y unchanged.
    """

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
    flatten_nd: bool = False,
) -> np.ndarray:
    """Convert input to a 2D numpy array.

    1D inputs are reshaped to column vectors. If *flatten_nd* is True,
    arrays with ndim > 2 are flattened by merging inner dimensions into the
    feature dimension: ``(n_samples, *inner, n_features) -> (n_samples, prod(inner)*n_features)``.
    """
    raw = value.data if isinstance(value, SherpaDataset) else value
    arr = np.asarray(raw, dtype=dtype)

    if arr.ndim == 0:
        raise ValueError(f"{name} must be 1D or 2D array-like, got scalar")
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    if arr.ndim > 2:
        if flatten_nd:
            arr = arr.reshape(arr.shape[0], -1)
        else:
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


def to_numpy_y(
    value: Any,
    *,
    name: str = "y",
    expected_samples: int | None = None,
    dtype: Any | None = None,
) -> np.ndarray:
    """Convert y target input to numpy array, preserving dimensionality.

    - 1D input -> kept as (n_samples,)
    - 2D input -> kept as (n_samples, n_targets)
    - Dict with ``"data"`` key -> extracted and converted (legacy eigenvector format)

    *dtype* defaults to ``None`` (preserve original dtype).  Pass
    ``np.float64`` explicitly for regression targets.
    """
    if isinstance(value, dict) and "data" in value:
        value = value["data"]
    raw = value.data if isinstance(value, SherpaDataset) else value
    arr = np.asarray(raw, dtype=dtype) if dtype is not None else np.asarray(raw)
    if arr.ndim == 0:
        raise ValueError(f"{name} must be 1D or 2D array-like, got scalar")
    if arr.ndim > 2:
        raise ValueError(f"{name} must be 1D or 2D array-like, got {arr.ndim}D")
    if expected_samples is not None and arr.shape[0] != expected_samples:
        raise ValueError(f"{name} must have {expected_samples} samples, got {arr.shape[0]}")
    return arr


class FlattenedView:
    """Provides a flat 2D view of nD data with unflatten capability.

    Merges inner dimensions into the feature dimension:
    ``(n_samples, d1, d2, ..., n_features) -> (n_samples, d1*d2*...*n_features)``

    For 2D data this is a no-op wrapper.
    """

    def __init__(self, dataset: SherpaDataset) -> None:
        self.original_shape = dataset.shape
        self.n_samples = dataset.shape[0]
        self.is_2d = dataset.ndim == 2
        self.flat = dataset.data if self.is_2d else dataset.data.reshape(self.n_samples, -1)

    def unflatten(self, result_2d: np.ndarray) -> np.ndarray:
        """Restore original nD shape from a flattened 2D result."""
        if self.is_2d:
            return result_2d
        total = int(np.prod(self.original_shape[1:]))
        if result_2d.shape[-1] == total:
            return result_2d.reshape(result_2d.shape[0], *self.original_shape[1:])
        # Feature count changed (e.g. region selection) — cannot unflatten
        return result_2d


def build_dataset_like(
    data: Any,
    source: Any,
    *,
    units: str | None = None,
    title: str | None = None,
    backend: str | None = None,
    copy_history: bool = True,
    restore_shape: tuple[int, ...] | None = None,
) -> SherpaDataset:
    """
    Wrap numeric output as SherpaDataset while preserving source metadata.

    If *restore_shape* is provided and *data* is 2D, attempt to reshape back to
    the original nD shape before constructing the dataset (useful after
    flattening for 2D-only operations).
    """
    src = coerce_to_sherpa(source, input_name="source", allow_array=True)
    arr = np.asarray(data, dtype=np.float64)
    if arr.ndim == 0:
        raise ValueError("data must be at least 1D array-like, got scalar")
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)

    # Attempt to restore nD shape from a flattened 2D result
    if restore_shape is not None and arr.ndim == 2 and len(restore_shape) > 2:
        expected_flat = int(np.prod(restore_shape[1:]))
        if arr.shape[-1] == expected_flat:
            arr = arr.reshape(arr.shape[0], *restore_shape[1:])

    # Use property accessor for feature axis and generic accessor for dim-0 observation axis.
    feature_axis = src.feature_axis  # Any FeatureAxis subclass
    obs_axis = src.get_observation_axis()  # Any axis type (SampleAxis, TimeAxis, etc.)

    target = copy.deepcopy(src.target) if src.target is not None else None

    # If shape changed, keep only compatible metadata
    if feature_axis is not None and feature_axis.length > 0 and feature_axis.length != arr.shape[-1]:
        feature_axis = None
    if obs_axis is not None and obs_axis.length > 0 and obs_axis.length != arr.shape[0]:
        obs_axis = None
    if target is not None and np.asarray(target).shape[0] != arr.shape[0]:
        target = None

    # Propagate inner axes from source if shapes match
    inner_axes = None
    if arr.ndim > 2 and src.ndim > 2:
        inner_axes = {}
        for dim, ax in src.inner_axes.items():
            if dim < arr.ndim - 1 and arr.shape[dim] == ax.length:
                inner_axes[dim] = ax
        if not inner_axes:
            inner_axes = None

    # Determine sample_axis for backward compatibility
    from spectra_sherpa.app.lib.axes import SampleAxis

    sample_axis = obs_axis if isinstance(obs_axis, SampleAxis) else None

    # Create dataset using feature_axis (supports all FeatureAxis types)
    result = SherpaDataset(
        X=arr,
        feature_axis=feature_axis,
        sample_axis=sample_axis,
        axes=inner_axes,
        target=target,
        target_context=src.target_context.model_copy(deep=True),
        domain=src.domain.model_copy(deep=True),
        provenance=(src.provenance.copy() if copy_history else Provenance()),
        quality=src.quality.model_copy(deep=True),
        backend=backend or src.backend,
        title=src.title if title is None else title,
        units=src.units if units is None else units,
        extra=copy.deepcopy(src.meta),
    )

    # If observation axis is NOT a SampleAxis (e.g., TimeAxis for time-resolved data),
    # manually set it in the _axes dict since __init__ only accepts sample_axis parameter
    if obs_axis is not None and not isinstance(obs_axis, SampleAxis):
        obs_copy = obs_axis.copy()
        obs_copy.bind_expected_length(arr.shape[0])
        result._axes[result._SAMPLE_DIM] = obs_copy

    return result


def attach_evaluation(
    dataset: SherpaDataset,
    evaluation: EvaluationResult,
) -> None:
    """Attach an EvaluationResult to a dataset's quality metrics.

    Mutates the dataset in place.
    """
    dataset.quality.add_evaluation(evaluation)
