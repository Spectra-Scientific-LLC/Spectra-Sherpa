"""Canonical sample-preparation authority for typed data DAG nodes.

This module owns the row-alignment semantics shared by ``data.attach_target``
and ``data.filter_samples``.  Node execution and exported Python both call
these functions; neither surface is allowed to maintain a second projection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from spectra_sherpa.app.lib.axes import SampleAxis
from spectra_sherpa.app.lib.sherpa_dataset import TargetContext
from spectra_sherpa.app.services.dag.io_contracts import (
    bind_X,
    bind_y,
    resolve_target_names,
    select_exact_target,
    to_numpy_2d,
    to_numpy_y,
)
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from spectra_sherpa.app.services.dag.supervision_binding import attach_sample_table_supervision
from spectra_sherpa.core.target_authority import TargetAuthority

from .sample_table import apply_sample_table_to_dataset, validate_sample_table_payload


@dataclass(frozen=True)
class SampleFilterPlan:
    """Closed row-selection result recorded in dataset provenance."""

    selected_indices: np.ndarray
    n_input: int
    n_selected: int
    n_nonfinite_excluded: int
    no_filter: bool


def explicit_filter_values(value: Any) -> list[Any] | None:
    """Return the contract-declared exact-selection list, preserving empty."""

    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("filter_values must be a list of strings")
    return list(value)


def _split_filter_terms(pattern: str) -> list[str]:
    return [term.strip() for term in re.split(r"[\n,]+", pattern) if term.strip()]


def _normalize_filter_strings(values: list[Any], *, case_sensitive: bool) -> list[str]:
    normalized = ["" if value is None else str(value) for value in values]
    if not case_sensitive:
        normalized = [value.lower() for value in normalized]
    return normalized


def _explicit_filter_mask(values: list[Any], selected_values: list[Any]) -> np.ndarray:
    selected = set(_normalize_filter_strings(selected_values, case_sensitive=True))
    value_strings = _normalize_filter_strings(values, case_sensitive=True)
    return np.asarray([value in selected for value in value_strings], dtype=bool)


def _sample_filter_mask(
    values: list[Any],
    *,
    pattern: str,
    match_mode: str,
    case_sensitive: bool,
) -> np.ndarray:
    value_strings = _normalize_filter_strings(values, case_sensitive=case_sensitive)
    pattern_text = pattern if case_sensitive else pattern.lower()

    if match_mode == "contains":
        return np.asarray([pattern_text in value for value in value_strings], dtype=bool)
    if match_mode == "equals":
        return np.asarray([value == pattern_text for value in value_strings], dtype=bool)
    if match_mode == "in_list":
        terms = set(_normalize_filter_strings(_split_filter_terms(pattern), case_sensitive=case_sensitive))
        return np.asarray([value in terms for value in value_strings], dtype=bool)
    if match_mode == "regex":
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(pattern, flags)
        except re.error as exc:
            raise ValueError(f"Invalid regular expression for sample filter: {exc}") from exc
        return np.asarray(
            [regex.search("" if value is None else str(value)) is not None for value in values],
            dtype=bool,
        )
    raise ValueError(f"Unsupported sample filter match mode: {match_mode!r}")


def _sample_index_mask(pattern: str, *, n_samples: int, match_mode: str, case_sensitive: bool) -> np.ndarray:
    if match_mode == "regex":
        values = [str(i + 1) for i in range(n_samples)]
        return _sample_filter_mask(values, pattern=pattern, match_mode=match_mode, case_sensitive=case_sensitive)

    selected: set[int] = set()
    for term in _split_filter_terms(pattern):
        if "-" in term:
            left, right = term.split("-", 1)
            try:
                start = int(left.strip())
                stop = int(right.strip())
            except ValueError as exc:
                raise ValueError(f"Invalid sample index range {term!r}. Use values like 1, 3-5.") from exc
            if start > stop:
                start, stop = stop, start
            selected.update(range(start, stop + 1))
        else:
            try:
                selected.add(int(term))
            except ValueError as exc:
                raise ValueError(f"Invalid sample index {term!r}. Use values like 1, 3-5.") from exc

    invalid = sorted(index for index in selected if index < 1 or index > n_samples)
    if invalid:
        raise ValueError(f"Sample index out of range: {invalid}. Dataset has samples 1 through {n_samples}.")
    return np.asarray([(i + 1) in selected for i in range(n_samples)], dtype=bool)


def _numeric_filter_compare(
    values: np.ndarray,
    *,
    operator: str,
    threshold: float,
    upper_threshold: float,
) -> np.ndarray:
    if operator == "gt":
        return values > threshold
    if operator == "gte":
        return values >= threshold
    if operator == "lt":
        return values < threshold
    if operator == "lte":
        return values <= threshold
    if operator == "eq":
        return np.isclose(values, threshold)
    if operator == "neq":
        return ~np.isclose(values, threshold)
    if operator == "between":
        low, high = sorted((threshold, upper_threshold))
        return (values >= low) & (values <= high)
    raise ValueError(f"Unsupported intensity filter operator: {operator!r}")


def _intensity_filter_mask(
    data: np.ndarray,
    *,
    metric: str,
    operator: str,
    threshold: float,
    upper_threshold: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return selection and eligibility masks for row-wise intensity rules.

    A row without any finite measurement is never selected, including when a
    selection is inverted.  This avoids treating missing spectra as evidence
    for a numerical condition such as ``not equal``.
    """

    finite = np.isfinite(data)
    finite_row = np.any(finite, axis=1)
    safe = np.where(finite, data, np.nan)

    if metric in {"mean", "max", "min"}:
        values = np.full(data.shape[0], np.nan, dtype=np.float64)
        eligible_rows = np.flatnonzero(finite_row)
        if metric == "mean":
            values[eligible_rows] = np.nanmean(safe[eligible_rows], axis=1)
        elif metric == "max":
            values[eligible_rows] = np.nanmax(safe[eligible_rows], axis=1)
        else:
            values[eligible_rows] = np.nanmin(safe[eligible_rows], axis=1)
        return (
            _numeric_filter_compare(
                values,
                operator=operator,
                threshold=threshold,
                upper_threshold=upper_threshold,
            )
            & finite_row,
            finite_row,
        )

    point_mask = (
        _numeric_filter_compare(
            data,
            operator=operator,
            threshold=threshold,
            upper_threshold=upper_threshold,
        )
        & finite
    )
    if metric == "any":
        return np.any(point_mask, axis=1) & finite_row, finite_row
    if metric == "all":
        complete_row = np.all(finite, axis=1)
        return np.all(point_mask, axis=1) & complete_row, complete_row
    raise ValueError(f"Unsupported intensity filter metric: {metric!r}")


def _flatten_filter_values(values: Any, *, field: str, n_samples: int) -> list[Any]:
    arr = np.asarray(values, dtype=object)
    if arr.ndim == 0:
        raise ValueError(f"Sample filter field {field!r} is scalar; expected one value per sample.")
    if arr.ndim > 1:
        if arr.shape[1:] == (1,):
            arr = arr.reshape(n_samples)
        else:
            raise ValueError(
                f"Sample filter field {field!r} has shape {arr.shape}; "
                "multi-column metadata cannot be filtered directly."
            )
    if arr.shape[0] != n_samples:
        raise ValueError(
            f"Sample filter field {field!r} has {arr.shape[0]} values, but dataset has {n_samples} samples."
        )
    return arr.tolist()


def _sample_filter_values(dataset: Any, *, field: str, sample_table_column: str, n_samples: int) -> list[Any]:
    sample_axis = getattr(dataset, "sample_axis", None)
    if field == "sample_label":
        labels = getattr(sample_axis, "labels", None) if sample_axis is not None else None
        if labels is None:
            raise ValueError("Dataset has no sample labels to filter. Use Sample Index or attach sample labels first.")
        return _flatten_filter_values(labels, field=field, n_samples=n_samples)
    if field == "sample_class":
        classes = getattr(sample_axis, "classes", None) if sample_axis is not None else None
        if classes is None:
            raise ValueError("Dataset has no sample classes to filter.")
        return _flatten_filter_values(classes, field=field, n_samples=n_samples)
    if field == "sample_table":
        column = sample_table_column.strip()
        if not column:
            raise ValueError("Sample Table Column is required when filtering by sample table.")
        sample_table = getattr(sample_axis, "sample_table", None) if sample_axis is not None else None
        if sample_table is None or column not in sample_table:
            available = sorted(sample_table) if sample_table else []
            raise ValueError(
                f"Dataset sample table has no column {column!r}. "
                f"Available columns: {', '.join(available) if available else 'none'}."
            )
        return _flatten_filter_values(sample_table[column], field=f"sample_table.{column}", n_samples=n_samples)
    if field == "sample_index":
        return [str(i + 1) for i in range(n_samples)]
    raise ValueError(f"Unsupported sample filter field: {field!r}")


def _slice_dataset_rows(source: Any, data: np.ndarray, indices: np.ndarray) -> Any:
    mask = np.zeros(data.shape[0], dtype=bool)
    mask[indices] = True
    return source[mask]


def _source_include_mask(dataset: Any, *, n_samples: int) -> np.ndarray:
    """Resolve row inclusion from sample or unfolded-image source authority."""

    sample_axis = getattr(dataset, "sample_axis", None)
    received = getattr(sample_axis, "include_mask", None) if sample_axis is not None else None
    if received is None:
        layout = getattr(dataset, "layout", None)
        received = getattr(layout, "image_include", None) if layout is not None else None
    if received is None:
        return np.ones(n_samples, dtype=bool)
    mask = np.asarray(received)
    if mask.dtype != np.bool_ or mask.shape != (n_samples,):
        raise ValueError("Source inclusion state must contain one exact boolean per sample")
    return mask.copy()


def filter_samples_dataset(
    X: Any,
    *,
    field: str,
    pattern: str,
    match_mode: str,
    case_sensitive: bool,
    invert: bool,
    sample_table_column: str,
    allow_empty: bool,
    intensity_metric: str,
    intensity_operator: str,
    intensity_threshold: float,
    intensity_upper_threshold: float,
    filter_values: list[Any] | None,
    node_id: str,
) -> Any:
    """Apply one canonical, row-aligned sample filter."""

    dataset = bind_X(
        X,
        missing_message="Missing required input: X (dataset)",
        dataset_error_message="X must be a SherpaDataset or compatible spectral dataset object",
        allow_array=True,
    )
    data = to_numpy_2d(dataset, name="X", dtype=np.float64)
    n_samples = data.shape[0]
    eligible = np.ones(n_samples, dtype=bool)

    if field == "source_inclusion":
        mask = _source_include_mask(dataset, n_samples=n_samples)
        if invert:
            mask = ~mask
        no_filter = bool(np.all(mask))
    elif field == "intensity":
        mask, eligible = _intensity_filter_mask(
            data,
            metric=intensity_metric,
            operator=intensity_operator,
            threshold=intensity_threshold,
            upper_threshold=intensity_upper_threshold,
        )
        if invert:
            mask = ~mask & eligible
        no_filter = False
    elif filter_values is not None and field != "sample_index":
        values = _sample_filter_values(
            dataset,
            field=field,
            sample_table_column=sample_table_column,
            n_samples=n_samples,
        )
        mask = _explicit_filter_mask(values, filter_values)
        if invert:
            mask = ~mask
        no_filter = False
    elif not pattern.strip():
        mask = np.ones(n_samples, dtype=bool)
        no_filter = True
    else:
        if field == "sample_index":
            mask = _sample_index_mask(
                pattern,
                n_samples=n_samples,
                match_mode=match_mode,
                case_sensitive=case_sensitive,
            )
        else:
            values = _sample_filter_values(
                dataset,
                field=field,
                sample_table_column=sample_table_column,
                n_samples=n_samples,
            )
            mask = _sample_filter_mask(
                values,
                pattern=pattern,
                match_mode=match_mode,
                case_sensitive=case_sensitive,
            )
        if invert:
            mask = ~mask
        no_filter = False

    indices = np.flatnonzero(mask)
    if indices.size == 0 and not allow_empty:
        raise ValueError(
            f"Sample filter selected 0 of {n_samples} samples. Check the selection rule or enable Allow Empty Result."
        )
    result = dataset.copy() if no_filter else _slice_dataset_rows(dataset, data, indices)
    if field == "source_inclusion" and str(dataset.data_role) == "X_hsi":
        result.data_role = "X_spectra"
    plan = SampleFilterPlan(
        selected_indices=indices,
        n_input=n_samples,
        n_selected=int(indices.size),
        n_nonfinite_excluded=int(np.count_nonzero(~eligible)),
        no_filter=no_filter,
    )
    add_processing_step(
        result,
        "data.filter_samples",
        {
            "field": field,
            "pattern": pattern,
            "match_mode": match_mode,
            "case_sensitive": case_sensitive,
            "invert": invert,
            "sample_table_column": sample_table_column,
            "allow_empty": allow_empty,
            "n_input": plan.n_input,
            "n_selected": plan.n_selected,
            "n_nonfinite_excluded": plan.n_nonfinite_excluded,
            "selected_indices": [] if plan.no_filter else plan.selected_indices.tolist(),
            "no_filter": plan.no_filter,
            "intensity_metric": intensity_metric,
            "intensity_operator": intensity_operator,
            "intensity_threshold": intensity_threshold,
            "intensity_upper_threshold": intensity_upper_threshold,
            "filter_values": filter_values,
        },
        node_id=node_id,
    )
    return result


def _sample_labels(value: Any) -> list[str] | None:
    axis = getattr(value, "sample_axis", None)
    labels = getattr(axis, "labels", None) if axis is not None else None
    return None if labels is None else [str(label) for label in labels]


def _single_target_vector(target: np.ndarray) -> np.ndarray:
    if target.ndim == 1:
        return target
    if target.ndim == 2 and target.shape[1] == 1:
        return target[:, 0]
    raise ValueError("A portable sample table can bind exactly one target column")


def _target_cell_equal(left: Any, right: Any, *, target_type: str) -> bool:
    left_state = np.asarray(pd.isna(left))
    right_state = np.asarray(pd.isna(right))
    if left_state.ndim != 0 or right_state.ndim != 0:
        raise ValueError("sample_table target cells must be scalar values")
    left_missing = bool(left_state.item())
    right_missing = bool(right_state.item())
    if left_missing or right_missing:
        return left_missing and right_missing
    if target_type == "continuous":
        return float(left) == float(right)
    return str(left) == str(right)


def _verify_sample_table_target(target: np.ndarray, sample_table: object, *, target_type: str) -> None:
    table = validate_sample_table_payload(sample_table)
    if table["target_type"] != target_type:
        raise ValueError("sample_table target_type does not match data.attach_target target_type")
    vector = _single_target_vector(target)
    if len(vector) != len(table["target_values"]):
        raise ValueError("sample_table target values are not row-aligned with y")
    if not all(
        _target_cell_equal(actual, declared, target_type=target_type)
        for actual, declared in zip(vector, table["target_values"], strict=True)
    ):
        raise ValueError("sample_table target values do not exactly match the connected y values")


def attach_target_dataset(
    X: Any,
    y: Any,
    *,
    target_type: str,
    node_id: str,
    sample_table: object = None,
    target_source: str = "connected_target",
    target_column: str = "",
    group_column: str = "",
    target_authority: TargetAuthority | None = None,
) -> Any:
    """Attach targets while preserving target identity and row alignment."""

    dataset = bind_X(X, missing_message="Missing required input: X (dataset)", allow_array=True)
    if target_source == "sample_table_column":
        if y is not None or sample_table is not None:
            raise ValueError("sample-table-column target attachment does not accept connected y or sample_table input")
        return attach_sample_table_supervision(
            dataset,
            target_column=target_column,
            target_type=target_type,
            group_column=group_column or None,
            node_id=node_id,
            target_authority=target_authority,
        )
    if target_source == "dataset_response":
        if y is not None or sample_table is not None or group_column:
            raise ValueError("dataset-response target attachment accepts only the admitted dataset response")
        if target_authority is None:
            raise ValueError("dataset-response target attachment requires an exact target authority")
        if target_column != target_authority.column or target_type != target_authority.target_type:
            raise ValueError("dataset-response target selection differs from its target authority")
        context = dataset.target_context
        if context is None or context.target_type != target_type:
            raise ValueError("dataset response type does not match the selected target type")
        target = select_exact_target(dataset, target_column)
        target_names = [target_column]
        X_labels = _sample_labels(dataset)
        y_labels = X_labels
        table = None
    elif target_source == "connected_target":
        target_names = resolve_target_names(y, dataset)
        y_raw = bind_y(
            y,
            X=dataset,
            required=True,
            infer_from_X=False,
            dataset_as_data=True,
            missing_message="Missing required input: y (target values)",
        )
        target = to_numpy_y(y_raw, name="y", expected_samples=dataset.shape[0], dtype=None)
        table = None
        if sample_table is not None:
            table = validate_sample_table_payload(sample_table)
            _verify_sample_table_target(target, table, target_type=target_type)
            if target_names is not None and list(target_names) != [table["target_name"]]:
                raise ValueError("sample_table target_name does not match the connected y target identity")
            target_names = [table["target_name"]]

        X_labels = _sample_labels(dataset)
        y_labels = _sample_labels(y)
        if X_labels is not None and y_labels is not None and X_labels != y_labels:
            raise ValueError("Target sample labels do not exactly match dataset sample labels and order")
    else:
        raise ValueError(f"Unsupported target source: {target_source!r}")

    result = dataset.snapshot()
    # Attaching supervision changes the target context, not the durable
    # scientific collection identity.  Preserve its declared dataset id so a
    # restart/re-import can reproduce the same capability envelope.
    result.meta.pop("supervision_binding", None)
    result.target = target
    if table is not None:
        apply_sample_table_to_dataset(result, table)
    if target_authority is not None:
        # The numeric target port cannot carry column labels. An explicit,
        # source-bound authority supplies that identity, never a guessed name.
        if target.ndim > 1 and target.shape[1] != 1:
            raise ValueError("one target authority cannot describe multiple response columns")
        if target_names is not None and list(target_names) != [target_authority.column]:
            raise ValueError("connected target names differ from the selected target authority")
        if target_type != target_authority.target_type:
            raise ValueError("connected target type differs from the selected target authority")
        target_names = [target_authority.column]
    # Preserve positional identity before any split. These are explicitly row
    # labels, not invented sample IDs or claims of cross-file identity matching.
    # Do not adopt Y's labels when X is anonymous: equal row counts do not
    # establish that those identifiers describe X. Alignment remains positional.
    if _sample_labels(result) is None:
        axis = result.sample_axis.copy() if result.sample_axis is not None else SampleAxis()
        axis.labels = [f"Source row {i + 1}" for i in range(result.n_samples)]
        result.sample_axis = axis
        result.meta["sample_label_origin"] = "source_row_index"
    single_target_name = target_names[0] if target_names is not None and len(target_names) == 1 else None
    if target_type == "categorical":
        class_names = sorted({str(value) for value in _single_target_vector(target) if not pd.isna(value)})
        result.target_context = TargetContext(
            target_type="categorical",
            target_name=single_target_name,
            target_names=target_names,
            selected_target=single_target_name,
            n_classes=len(class_names),
            class_names=class_names,
            target_units=target_authority.units if target_authority is not None else None,
            selected_authority=target_authority,
        )
    elif target_type == "continuous":
        result.target_context = TargetContext(
            target_type="continuous",
            target_name=single_target_name,
            target_names=target_names,
            selected_target=single_target_name,
            target_units=target_authority.units if target_authority is not None else None,
            selected_authority=target_authority,
        )
    else:
        raise ValueError(f"Unsupported target type: {target_type!r}")

    add_processing_step(
        result,
        "data.attach_target",
        {
            "target_authority": (target_authority.canonical_dict() if target_authority is not None else None),
            "target_type": target_type,
            "target_source": target_source,
            "target_column": target_column if target_source in {"sample_table_column", "dataset_response"} else None,
            "group_column": (group_column or None) if target_source == "sample_table_column" else None,
            "target_shape": list(target.shape),
            "target_names": list(target_names) if target_names is not None else None,
            "sample_identity_checked": X_labels is not None and y_labels is not None,
            "sample_table_schema": table["schema_version"] if table is not None else None,
            "sample_table_source_file_id": table["source_file_id"] if table is not None else None,
            "sample_table_identity_checked": table is not None,
            "supervision_binding_sha256": None,
        },
        node_id=node_id,
    )
    return result


def attach_selected_target_dataset(
    dataset: Any,
    *,
    target_type: str,
    target_column: str,
    node_id: str,
    target_authority: TargetAuthority,
    group_column: str = "",
) -> Any:
    """Attach an exact native response or its aligned sample-table column."""

    context = getattr(dataset, "target_context", None)
    names = [str(name) for name in (getattr(context, "target_names", None) or [])]
    single_name = getattr(context, "target_name", None)
    selected_name = getattr(context, "selected_target", None)
    has_named_response = getattr(dataset, "target", None) is not None and target_column in {
        *names,
        *([str(single_name)] if single_name else []),
        *([str(selected_name)] if selected_name else []),
    }
    target_source = "dataset_response" if has_named_response and not group_column else "sample_table_column"
    return attach_target_dataset(
        dataset,
        None,
        target_type=target_type,
        target_source=target_source,
        target_column=target_column,
        group_column=group_column,
        node_id=node_id,
        target_authority=target_authority,
    )
