"""Shared IO contract helpers for DAG nodes.

Phase 1 objective:
- Standardize X/y input binding through the canonical dataset.
- Standardize conversion to SherpaDataset / numpy arrays.
- Standardize output dataset wrapping with metadata preservation.

These helpers are intentionally lightweight so imperative nodes can opt in
incrementally without changing business logic.
"""

from __future__ import annotations

import copy
import hashlib
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import EvaluationResult, Provenance, SherpaDataset

from .transport import reject_spectrochempy_transport, require_raw_matrix_container


def _is_dataset_like(value: Any) -> bool:
    """Return whether *value* is the canonical scientific dataset."""

    return isinstance(value, SherpaDataset)


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
    reject_spectrochempy_transport(value, boundary=f"{input_name} canonical dataset admission")
    if isinstance(value, SherpaDataset):
        return value

    if allow_array:
        require_raw_matrix_container(value, input_name=input_name)
        arr = np.asarray(value, dtype=np.float64)
        if arr.ndim == 0:
            err = dataset_error_message or (
                f"{input_name} must be dataset-like or array-like with at least 1 dimension"
            )
            raise ValueError(err)
        if arr.ndim == 1:
            arr = arr.reshape(-1, 1)
        return SherpaDataset(X=arr, backend="numpy")

    err = dataset_error_message or (f"{input_name} must be a SherpaDataset object")
    raise ValueError(err)


def bind_X(
    X: Any,
    *,
    missing_message: str = "Missing required input: X",
    dataset_error_message: str = "X must be a SherpaDataset object",
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
        return bool(arr.size > 0)
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

    return select_exact_target(dataset, str(selected))


def select_exact_target(dataset: Any, selected_target: str) -> np.ndarray:
    """Return one explicitly named supervised response or fail closed.

    Managed optimization must never infer which column of a multi-response
    reference table the scientist intended to optimize.  This helper is the
    strict counterpart to the local convenience projection above: it requires
    target metadata, checks the declared name against the physical target
    shape, and returns exactly one sample-aligned vector.
    """

    if not isinstance(selected_target, str) or not selected_target.strip():
        raise ValueError("selected target must be one exact non-empty name")
    target = getattr(dataset, "target", None)
    if not _has_values(target):
        raise ValueError("dataset has no supervised response values")
    target_array = np.asarray(target)
    context = getattr(dataset, "target_context", None)
    names = [str(name) for name in (getattr(context, "target_names", None) or [])]
    single_name = getattr(context, "target_name", None)
    context_selected = getattr(context, "selected_target", None)

    if target_array.ndim == 1:
        if context_selected is not None:
            declared = str(context_selected)
        elif len(names) == 1:
            declared = names[0]
        elif single_name is not None:
            declared = str(single_name)
        else:
            raise ValueError("one-dimensional dataset response has no exact target identity")
        if declared != selected_target:
            raise ValueError(f"selected target {selected_target!r} is not the dataset response {str(declared)!r}")
        return np.asarray(target_array)

    if target_array.ndim != 2 or target_array.shape[1] < 1:
        raise ValueError("dataset response must be one- or two-dimensional")
    if len(names) != target_array.shape[1]:
        raise ValueError("dataset response names do not match its target columns")
    if selected_target not in names:
        raise ValueError(f"selected target {selected_target!r} is not present in the dataset response columns")
    return np.asarray(target_array[:, names.index(selected_target)])


def extract_target_like(dataset: Any) -> Any | None:
    """
    Extract target/label vector from a dataset.

    If ``target_context.selected_target`` is set, extract only that
    column from a multi-target array instead of returning all columns.

    Authority: ``SherpaDataset.target``, optionally sliced by the exact
    ``selected_target`` identity.

    A SherpaDataset sample axis is identity/ordering metadata, never an
    implicit supervised target.
    """
    target = getattr(dataset, "target", None)
    if _has_values(target):
        # Honor explicit Y column selection for multi-target datasets
        target = _apply_selected_target(dataset, target)
        return target

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
            selected = getattr(tc, "selected_target", None)
            if selected and selected in tc.target_names:
                return [str(selected)]
            return list(tc.target_names)
        fa = getattr(y_raw, "feature_axis", None)
        if fa is not None and getattr(fa, "labels", None):
            return list(fa.labels)

    if X_ds is not None:
        tc = getattr(X_ds, "target_context", None)
        if tc is not None and tc.target_names:
            selected = getattr(tc, "selected_target", None)
            if selected and selected in tc.target_names:
                return [str(selected)]
            return list(tc.target_names)

    return None


def require_aligned_response_samples(X: SherpaDataset, y: SherpaDataset) -> None:
    """Validate explicit dataset row identities before unwrapping responses.

    Two anonymous datasets retain the positional API. A supplied identity must
    never be discarded to pair rows against an anonymous or contradictory one.
    Raw arrays remain the caller's explicit positional interface.
    """
    if X.n_samples != y.n_samples:
        raise ValueError("X and response datasets have different sample counts")

    def identity(dataset: SherpaDataset) -> list[str | float] | None:
        axis = dataset.sample_axis
        if axis is None:
            return None
        labels = axis.labels
        if labels is not None:
            if any(not isinstance(label, str) or not label.strip() for label in labels):
                raise ValueError("dataset has invalid sample identities")
            table_ids = (axis.sample_table or {}).get("sample_id")
            if table_ids is not None and list(table_ids) != list(labels):
                raise ValueError("sample table identities contradict sample-axis labels")
            return list(labels)
        if (axis.sample_table or {}).get("sample_id") is not None:
            raise ValueError("sample table identities require aligned sample-axis labels")
        if axis.values is not None:
            if not np.isfinite(axis.values).all():
                raise ValueError("dataset has non-finite sample identities")
            return axis.values.tolist()
        return None

    left, right = identity(X), identity(y)
    if left is None and right is None:
        return
    for name, labels in (("X", left), ("response", right)):
        if labels is None or len(labels) != X.n_samples:
            raise ValueError(f"{name} dataset is missing complete sample identities; use an explicit sample join")
        if len(set(labels)) != len(labels):
            raise ValueError(f"{name} dataset has duplicate sample identities")
    if left != right:
        raise ValueError("X and response sample identities/order differ; use an explicit sample join")


def bind_y(
    y: Any,
    *,
    X: SherpaDataset | None = None,
    required: bool = False,
    infer_from_X: bool = True,
    dataset_as_data: bool = False,
    target_type: str | None = None,
    missing_message: str = "Missing required input: y",
    dataset_missing_message: str = (
        "Dataset passed to y port has no embedded labels. Use target or y-axis labels/data."
    ),
) -> Any:
    """
    Bind and normalize y input.

    - If y is omitted and infer_from_X=True, attempts extraction from X.
    - If y is a dataset and dataset_as_data=True, returns y.data.
    - If y is a dataset and dataset_as_data=False, extracts target/labels.
    - Otherwise returns y unchanged.

    target_type: optional contract declaration — "categorical" or "continuous".
        When set, the target_context on X is checked and a clear error is raised
        if the dataset carries an incompatible target type.
        E.g. pass target_type="categorical" in classification nodes so that
        regression datasets (Corn M5, Diesel NIR) are rejected early.
    """

    # Validate target type contract against the source dataset's declared context
    if target_type is not None and X is not None:
        tc = getattr(X, "target_context", None)
        actual_type = getattr(tc, "target_type", None) if tc is not None else None
        if actual_type is not None and actual_type != target_type:
            names = getattr(tc, "target_names", None) or []
            names_str = ", ".join(str(n) for n in names) if names else "unknown"
            if target_type == "categorical":
                raise ValueError(
                    f"Dataset has {actual_type} targets [{names_str}] — "
                    "classification nodes require categorical class labels. "
                    "Use a dataset with discrete class assignments (e.g. wine, iris, breast_cancer) "
                    "or attach a class-label column before connecting to this node."
                )
            else:
                raise ValueError(
                    f"Dataset has {actual_type} targets [{names_str}] — this node requires {target_type} targets."
                )

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
        if target_type is not None:
            y_context = getattr(y_dataset, "target_context", None)
            y_target_type = getattr(y_context, "target_type", None) if y_context is not None else None
            if y_target_type is not None and y_target_type != target_type:
                raise ValueError(
                    f"Dataset connected to y has {y_target_type} targets; this node requires {target_type} targets."
                )
        if X is not None:
            require_aligned_response_samples(X, y_dataset)
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


def clean_regression_target(
    X_ds: SherpaDataset,
    y_array: np.ndarray,
    *,
    model_label: str,
    preserve_1d: bool = True,
) -> tuple[SherpaDataset, np.ndarray]:
    """Compatibility wrapper; producers must retain the population receipt."""
    dataset, target, _ = clean_regression_target_with_population(
        X_ds, y_array, model_label=model_label, preserve_1d=preserve_1d
    )
    return dataset, target


def clean_regression_target_with_population(
    X_ds: SherpaDataset,
    y_array: np.ndarray,
    *,
    model_label: str,
    preserve_1d: bool = True,
    source_scientific_digest: str | None = None,
    response_input_columns: list[int] | None = None,
) -> tuple[SherpaDataset, np.ndarray, dict[str, Any]]:
    """Admit measured regression targets and return an ordered population receipt.

    Partial reference tables are common in spectroscopy benchmark datasets:
    different properties may be measured for different samples. A multi-target
    regression model needs complete rows for every target; otherwise the model
    either crashes in sklearn or emits misleading NaN metrics. If the workflow
    has already selected one target, rows missing that selected property are
    dropped together with their spectra.
    """
    original = np.asarray(y_array, dtype=np.float64)
    original_was_1d = original.ndim == 1
    y_2d = original.reshape(-1, 1) if original.ndim == 1 else original
    if y_2d.ndim != 2:
        raise ValueError(f"y must be 1D or 2D array-like for {model_label}, got {y_2d.ndim}D")
    target_context = getattr(X_ds, "target_context", None)
    selected_target = getattr(target_context, "selected_target", None) if target_context is not None else None

    if y_2d.shape[0] != X_ds.n_samples or y_2d.shape[1] == 0:
        raise ValueError(f"{model_label} target dimensions do not match the input population")
    if np.isinf(y_2d).any():
        raise ValueError(f"{model_label} target contains infinity; invalid references cannot be treated as missing")
    if not np.isfinite(X_ds.X).all():
        raise ValueError(f"{model_label} predictors contain non-finite values; repair predictors explicitly")
    axis = X_ds.sample_axis
    if axis is not None and axis.include_mask is not None and not np.all(axis.include_mask):
        raise ValueError(f"{model_label} input has excluded samples; materialize the active cohort before fitting")
    source_digest = source_scientific_digest or X_ds.scientific_digest
    nonfinite_mask = np.isnan(y_2d)
    row_mask = nonfinite_mask.any(axis=1)
    labels = list(axis.labels) if axis is not None and axis.labels is not None else None
    values = axis.values.tolist() if axis is not None and axis.values is not None else None
    response_bytes = np.array(y_2d, dtype="<f8", order="C", copy=True)
    response_bytes[np.isnan(response_bytes)] = np.nan  # canonical missing-value representation
    population = {
        "schema": "spectrasherpa.regression-population/1",
        "source_scientific_digest": source_digest,
        "scope": "training_fit_only_not_predictive_validation",
        "model": model_label,
        "input_count": int(y_2d.shape[0]),
        "admitted_count": int((~row_mask).sum()),
        "excluded_count": int(row_mask.sum()),
        "selected_target": str(selected_target) if selected_target else None,
        "response_names": list(target_context.target_names or []) if target_context is not None else [],
        "response_units": getattr(target_context, "target_units", None),
        "response_input_columns": response_input_columns or list(range(y_2d.shape[1])),
        "response_shape": list(y_2d.shape),
        "response_sha256": hashlib.sha256(response_bytes.tobytes(order="C")).hexdigest(),
        "identity_basis": "source_digest_and_zero_based_row",
        "sample_labels": labels,
        "sample_values": values,
        "admitted_rows": np.flatnonzero(~row_mask).tolist(),
        "excluded_rows": [
            {"row": int(i), "reason": "missing_reference", "target_columns": np.flatnonzero(nonfinite_mask[i]).tolist()}
            for i in np.flatnonzero(row_mask)
        ],
    }
    if row_mask.any():
        n_targets = int(y_2d.shape[1])
        if n_targets > 1 and not selected_target:
            has_any = np.isfinite(y_2d).any(axis=1)
            has_all = np.isfinite(y_2d).all(axis=1)
            raise ValueError(
                "This dataset has incomplete multi-target reference values: "
                f"{int(has_any.sum())}/{y_2d.shape[0]} samples have at least one target, "
                f"but only {int(has_all.sum())}/{y_2d.shape[0]} have all {n_targets} targets. "
                "Choose a single target property on the My Dataset page, or provide a fully populated "
                f"multi-target table before training {model_label}."
            )

        valid = ~row_mask
        if not valid.any():
            target_hint = f" for target {selected_target!r}" if selected_target else ""
            raise ValueError(
                f"No complete target values are available{target_hint}. "
                "Choose a target property with measured values or provide reference values before training."
            )
        y_2d = y_2d[valid]
        X_ds = X_ds[valid, :]

    if selected_target and y_2d.shape[1] == 1:
        selected = str(selected_target)
        if target_context is not None:
            X_ds.target_context = target_context.model_copy(
                update={
                    "target_name": selected,
                    "target_names": [selected],
                    "selected_target": selected,
                }
            )
        X_ds.meta["target_mode"] = "single"
        X_ds.meta["selected_target"] = selected
        X_ds.meta["target_names"] = [selected]

    if preserve_1d and (original_was_1d or y_2d.shape[1] == 1):
        return X_ds, y_2d.reshape(-1), population
    return X_ds, y_2d, population


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
    inner_axes: dict[int, Any] | None = None
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

    # Create dataset using feature_axis (supports all FeatureAxis types).
    # is_time_series is a top-level SherpaDataset attribute (not stored in
    # meta or domain), so it must be threaded explicitly here. Without this,
    # every preprocessing node that builds output via build_dataset_like
    # silently drops the user's Explore-tab time-series toggle. Sample-order
    # is preserved by all such transforms, so propagating the flag is correct.
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
        is_time_series=bool(src.is_time_series),
        data_role=src.data_role,
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
