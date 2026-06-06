"""
Built-in dataset inspection tools.

These tools let the LLM inspect dataset metadata, domain context,
and quality metrics using dataset handles (dataset_id).
"""

from __future__ import annotations

import re
from typing import Any

from spectra_sherpa.app.services.tools.registry import register_tool
from spectra_sherpa.app.services.tools.schemas import ToolCategory

MAX_EXACT_STAT_CELLS = 2_000_000
MAX_OVERALL_SAMPLE_CELLS = 200_000
# Hard cap on how many selector items are resolved per call.  Selector
# resolution is O(n_selectors * n_labels); ``limit`` only bounds the
# returned rows, so without this an LLM-driven (or prompt-injected)
# oversized selector list is an unbounded CPU + context-cost vector.
MAX_SELECTOR_ITEMS = 200
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _metadata_text(value: Any, *, max_len: int = 120) -> str:
    """Compact user/file-supplied metadata before returning it to the LLM."""
    text = _CONTROL_CHARS_RE.sub(" ", str(value))
    text = text.replace("\r", " ").replace("\n", " ")
    text = " ".join(text.split())
    if len(text) > max_len:
        return text[: max_len - 15].rstrip() + "...[truncated]"
    return text


def _load_dataset(dataset_id: str, user: Any = None) -> Any:
    """Fetch a registered dataset for the current user."""
    from spectra_sherpa.app.services.dataset_registry import dataset_registry

    user_id = getattr(user, "id", None) if user is not None else None
    try:
        return dataset_registry.get(dataset_id, user_id=user_id)
    except KeyError as exc:
        raise ValueError(f"Unknown dataset_id: {dataset_id}") from exc
    except PermissionError as exc:
        raise ValueError("Dataset is not accessible for this user") from exc


@register_tool(
    "describe_dataset",
    "Generate a structured summary of a dataset including domain, " "processing state, and quality metrics.",
    category=ToolCategory.data,
    requires_user=True,
    parameters={
        "type": "object",
        "properties": {
            "dataset_id": {
                "type": "string",
                "description": "Dataset handle ID",
            },
            "tier": {
                "type": "integer",
                "description": ("Detail tier: 0=shape+domain, 1=+state+axes, " "2=+provenance, 3=+quality+statistics"),
            },
        },
        "required": ["dataset_id"],
    },
)
def describe_dataset(dataset_id: str, tier: int = 1, user: Any = None) -> dict[str, Any]:
    """Return a tiered summary for a registered dataset handle."""
    from spectra_sherpa.app.lib.dataset_summarizer import DatasetSummarizer

    ds = _load_dataset(dataset_id, user=user)

    summarizer = DatasetSummarizer()
    return {
        "dataset_id": ds.dataset_id,
        "summary": summarizer.summarize(ds, tier=tier),
        "structured": summarizer.to_structured(ds, tier=tier),
    }


@register_tool(
    "compute_dataset_statistics",
    "Compute bounded descriptive statistics from registered dataset values and axis/target metadata.",
    category=ToolCategory.data,
    requires_user=True,
    parameters={
        "type": "object",
        "properties": {
            "dataset_id": {
                "type": "string",
                "description": "Dataset handle ID from workflow context or describe_dataset.",
            },
            "statistics": {
                "type": "array",
                "description": "Statistics to compute.",
                "items": {
                    "type": "string",
                    "enum": ["mean", "median", "std", "min", "max", "q1", "q3"],
                },
                "default": ["mean", "median", "std", "min", "max"],
            },
            "axis": {
                "type": "string",
                "enum": ["features", "samples", "overall", "target"],
                "description": (
                    "Compute per feature, per sample, over the whole X matrix, " "or summarize target/Y values."
                ),
                "default": "features",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "description": "Maximum number of per-feature or per-sample rows returned.",
                "default": 50,
            },
            "feature_selectors": {
                "type": "array",
                "description": (
                    "Optional feature selectors for axis='features'. Items may be feature indices, "
                    "exact/partial feature labels, numeric spectral coordinates, or objects like "
                    '{"index": 3}, {"label": "sepal length"}, {"coordinate": 1720.0}. '
                    "At most 200 selectors are resolved per call."
                ),
                "items": {},
                "maxItems": 200,
            },
            "sample_selectors": {
                "type": "array",
                "description": (
                    "Optional sample selectors for axis='samples'. Items may be sample indices, "
                    "exact/partial sample labels, numeric sample coordinates, or objects like "
                    '{"index": 3}, {"label": "sample A"}. '
                    "At most 200 selectors are resolved per call."
                ),
                "items": {},
                "maxItems": 200,
            },
        },
        "required": ["dataset_id"],
    },
)
def compute_dataset_statistics(
    dataset_id: str,
    statistics: list[str] | str | None = None,
    axis: str = "features",
    limit: int = 50,
    feature_selectors: list[Any] | Any | None = None,
    sample_selectors: list[Any] | Any | None = None,
    user: Any = None,
) -> dict[str, Any]:
    """Compute bounded descriptive statistics from a registered dataset handle."""
    import numpy as np

    ds = _load_dataset(dataset_id, user=user)
    try:
        X = np.asarray(ds.X)
        if not np.issubdtype(X.dtype, np.number):
            if X.size > MAX_EXACT_STAT_CELLS:
                raise ValueError(
                    "Dataset values are non-numeric and too large to coerce safely. "
                    "Use a numeric data matrix or a smaller dataset."
                )
            X = X.astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError("Dataset X values are not numeric enough for descriptive statistics.") from exc

    if X.ndim == 0:
        X = X.reshape(1, 1)
    elif X.ndim == 1:
        X = X.reshape(-1, 1)
    elif X.ndim > 2:
        X = X.reshape((-1, X.shape[-1]))

    if isinstance(statistics, str):
        statistics = [statistics]

    requested = statistics or ["mean", "median", "std", "min", "max"]
    allowed = {"mean", "median", "std", "min", "max", "q1", "q3"}
    requested = [item.lower() for item in requested if item.lower() in allowed]
    if not requested:
        raise ValueError("No supported statistics requested.")

    limit = max(1, min(int(limit), 100))
    axis = axis.lower()
    axis = axis if axis in {"features", "samples", "overall", "target"} else "features"

    funcs = {
        "mean": np.nanmean,
        "median": np.nanmedian,
        "std": np.nanstd,
        "min": np.nanmin,
        "max": np.nanmax,
        "q1": lambda values, axis=None: np.nanpercentile(values, 25, axis=axis),
        "q3": lambda values, axis=None: np.nanpercentile(values, 75, axis=axis),
    }

    def _safe_float(value: Any) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if np.isfinite(number) else None

    def _compute(values: np.ndarray, stat_axis: int | None) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for stat in requested:
            try:
                raw = funcs[stat](values, axis=stat_axis)
            except (ValueError, FloatingPointError):
                raw = np.nan
            if isinstance(raw, np.ndarray):
                output[stat] = [_safe_float(item) for item in raw.tolist()]
            else:
                output[stat] = _safe_float(raw)
        return output

    def _axis_metadata(axis_info: Any, *, count: int, default_title: str) -> dict[str, Any]:
        values = getattr(axis_info, "values", None) if axis_info is not None else None
        labels = getattr(axis_info, "labels", None) if axis_info is not None else None
        values_arr = np.asarray(values) if values is not None else None
        label_count = len(labels) if labels is not None else 0
        metadata: dict[str, Any] = {
            "title": (
                _metadata_text(getattr(axis_info, "title", None) or default_title)
                if axis_info is not None
                else default_title
            ),
            "units": (
                _metadata_text(getattr(axis_info, "units", None), max_len=40)
                if axis_info is not None and getattr(axis_info, "units", None) is not None
                else None
            ),
            "n_points": count,
            "has_coordinates": values_arr is not None and values_arr.size > 0,
            "has_labels": label_count > 0,
        }
        if values_arr is not None and values_arr.size > 0 and np.issubdtype(values_arr.dtype, np.number):
            metadata["min"] = _safe_float(np.nanmin(values_arr))
            metadata["max"] = _safe_float(np.nanmax(values_arr))
        return metadata

    def _selector_list(selectors: list[Any] | Any | None) -> list[Any]:
        if selectors is None:
            return []
        if isinstance(selectors, list):
            return selectors
        return [selectors]

    def _resolve_label(normalized_labels: list[str], label: str) -> int | None:
        # ``normalized_labels`` is precomputed once per axis (see
        # ``_resolve_axis_selectors``) so label resolution is O(n_labels)
        # per selector instead of re-sanitizing every label per selector.
        normalized = label.casefold()
        for index, item in enumerate(normalized_labels):
            if item == normalized:
                return index
        for index, item in enumerate(normalized_labels):
            if normalized in item:
                return index
        return None

    def _resolve_coordinate(coordinates: np.ndarray | None, coordinate: float) -> tuple[int, float | None] | None:
        if coordinates is None or coordinates.size == 0 or not np.issubdtype(coordinates.dtype, np.number):
            return None
        distances = np.abs(coordinates.astype(float) - coordinate)
        if not np.any(np.isfinite(distances)):
            return None
        index = int(np.nanargmin(distances))
        return index, _safe_float(coordinates[index])

    def _resolve_axis_selectors(
        selectors: list[Any] | Any | None,
        *,
        axis_info: Any,
        count: int,
        axis_name: str,
    ) -> tuple[list[int] | None, dict[str, Any] | None]:
        requested = _selector_list(selectors)
        if not requested:
            return None, None
        selectors_truncated = len(requested) > MAX_SELECTOR_ITEMS
        requested = requested[:MAX_SELECTOR_ITEMS]

        labels = list(axis_info.labels) if axis_info is not None and axis_info.labels is not None else []
        normalized_labels = [_metadata_text(item, max_len=240).casefold() for item in labels]
        coordinates = np.asarray(axis_info.values) if axis_info is not None and axis_info.values is not None else None
        resolved: list[dict[str, Any]] = []
        unresolved: list[Any] = []
        seen: set[int] = set()

        def _add(index: int, selector: Any, matched_by: str, coordinate: float | None = None) -> None:
            if index < 0 or index >= count:
                unresolved.append(selector)
                return
            if index in seen:
                return
            seen.add(index)
            item: dict[str, Any] = {
                "selector": _metadata_text(selector if not isinstance(selector, dict) else selector),
                "index": index,
                "matched_by": matched_by,
            }
            if labels and index < len(labels):
                item["label"] = _metadata_text(labels[index])
            if coordinate is not None:
                item["coordinate"] = coordinate
            elif coordinates is not None and index < len(coordinates):
                item["coordinate"] = _safe_float(coordinates[index])
            resolved.append(item)

        for selector in requested:
            index: int | None = None
            coordinate: float | None = None
            matched_by = "index"

            if isinstance(selector, dict):
                if "index" in selector:
                    try:
                        index = int(selector["index"])
                    except (TypeError, ValueError):
                        index = None
                    matched_by = "index"
                elif "label" in selector:
                    label = _metadata_text(selector["label"], max_len=240)
                    index = _resolve_label(normalized_labels, label)
                    matched_by = "label"
                elif "coordinate" in selector:
                    try:
                        coord_value = float(selector["coordinate"])
                    except (TypeError, ValueError):
                        coord_value = None
                    match = _resolve_coordinate(coordinates, coord_value) if coord_value is not None else None
                    if match:
                        index, coordinate = match
                    matched_by = "coordinate"
            elif isinstance(selector, int):
                if 0 <= selector < count:
                    index = selector
                    matched_by = "index"
                else:
                    match = _resolve_coordinate(coordinates, float(selector))
                    if match:
                        index, coordinate = match
                        matched_by = "coordinate"
            elif isinstance(selector, float):
                match = _resolve_coordinate(coordinates, selector)
                if match:
                    index, coordinate = match
                    matched_by = "coordinate"
            elif isinstance(selector, str):
                text = _metadata_text(selector, max_len=240)
                index = _resolve_label(normalized_labels, text)
                matched_by = "label"
                if index is None:
                    try:
                        numeric = float(text)
                    except ValueError:
                        numeric = None
                    if numeric is not None:
                        match = _resolve_coordinate(coordinates, numeric)
                        if match:
                            index, coordinate = match
                            matched_by = "coordinate"
                        elif numeric.is_integer() and 0 <= int(numeric) < count:
                            index = int(numeric)
                            matched_by = "index"

            if index is None:
                unresolved.append(selector)
            else:
                _add(index, selector, matched_by, coordinate)

        if not resolved:
            raise ValueError(f"No {axis_name} selectors matched this dataset.")

        truncated = len(resolved) > limit
        selected = resolved[:limit]
        return [int(item["index"]) for item in selected], {
            "axis": axis_name,
            "requested": [_metadata_text(item if not isinstance(item, dict) else item) for item in requested],
            "resolved": selected,
            "unresolved": [_metadata_text(item if not isinstance(item, dict) else item) for item in unresolved],
            "truncated": truncated,
            "selectors_truncated": selectors_truncated,
        }

    def _class_counts(values: np.ndarray, max_items: int = 20) -> list[dict[str, Any]]:
        unique, counts = np.unique(values.astype(str), return_counts=True)
        order = np.argsort(counts)[::-1]
        return [{"value": _metadata_text(unique[index]), "count": int(counts[index])} for index in order[:max_items]]

    def _numeric_target_stats(values: np.ndarray) -> dict[str, Any]:
        numeric = values.astype(float)
        return _compute(numeric, None)

    def _target_summary() -> dict[str, Any] | None:
        target = getattr(ds, "target", None)
        sample_axis = ds.sample_axis
        target_context = ds.target_context
        classes = getattr(sample_axis, "classes", None)
        if target is None and classes is None:
            return None

        summary: dict[str, Any] = {
            "target_type": _metadata_text(target_context.target_type),
            "target_name": _metadata_text(target_context.target_name) if target_context.target_name else None,
            "target_names": (
                [_metadata_text(name) for name in target_context.target_names] if target_context.target_names else []
            ),
            "target_units": (
                _metadata_text(target_context.target_units, max_len=40) if target_context.target_units else None
            ),
            "class_names": (
                [_metadata_text(name) for name in target_context.class_names] if target_context.class_names else []
            ),
        }

        if target is None:
            class_values = np.asarray(classes)
            summary["source"] = "sample_axis.classes"
            summary["kind"] = "categorical"
            summary["n_values"] = int(class_values.size)
            summary["counts"] = _class_counts(class_values)
            return summary

        values = np.asarray(target)
        summary["source"] = "target"
        summary["shape"] = list(values.shape)
        if values.ndim == 1:
            columns = [(target_context.target_name or target_context.selected_target or "target", values)]
        else:
            flat = values.reshape(values.shape[0], -1)
            names = target_context.target_names or []
            columns = [
                (names[index] if index < len(names) else f"target_{index}", flat[:, index])
                for index in range(min(flat.shape[1], limit))
            ]
            summary["truncated"] = flat.shape[1] > limit

        outputs = []
        for name, column in columns:
            item: dict[str, Any] = {"name": _metadata_text(name), "n_values": int(column.size)}
            try:
                item["kind"] = "numeric"
                item["statistics"] = _numeric_target_stats(np.asarray(column))
            except (TypeError, ValueError):
                item["kind"] = "categorical"
                item["counts"] = _class_counts(np.asarray(column))
            outputs.append(item)
        summary["targets"] = outputs
        return summary

    feature_axis = ds.get_feature_axis()
    sample_axis = ds.sample_axis
    value_units = ds.units if ds.units and str(ds.units) != "dimensionless" else None
    value_units = value_units or ds.get_extra("scp.value_units_label") or ds.domain.expected_units
    base: dict[str, Any] = {
        "dataset_id": ds.dataset_id,
        "axis": axis,
        "shape": list(X.shape),
        "data_values": {
            "title": _metadata_text(ds.domain.data_quantity or "value"),
            "units": _metadata_text(value_units, max_len=40) if value_units is not None else None,
        },
        "feature_axis": _axis_metadata(feature_axis, count=X.shape[1], default_title="Feature"),
        "sample_axis": _axis_metadata(sample_axis, count=X.shape[0], default_title="Sample"),
        "target_summary": _target_summary(),
        "approximate": False,
        "sampled": False,
    }

    if axis == "target":
        return base

    if axis == "overall":
        values = X
        if X.size > MAX_EXACT_STAT_CELLS:
            flat = X.ravel()
            step = max(1, int(np.ceil(flat.size / MAX_OVERALL_SAMPLE_CELLS)))
            values = flat[::step]
            base["approximate"] = True
            base["sampled"] = True
            base["sample_plan"] = {
                "reason": "overall dataset exceeds exact statistics cell limit",
                "source_cells": int(X.size),
                "sampled_cells": int(values.size),
                "step": step,
            }
        base["statistics"] = _compute(values, None)
        return {
            **base,
        }

    if axis == "features":
        count = X.shape[1]
        selected_indices, selection = _resolve_axis_selectors(
            feature_selectors,
            axis_info=feature_axis,
            count=count,
            axis_name="features",
        )
        if selected_indices is None:
            returned = min(count, limit)
            selected_indices = list(range(returned))
            truncated = count > limit
        else:
            returned = len(selected_indices)
            truncated = bool(selection and selection["truncated"])
            base["selection"] = selection
        values = X[:, selected_indices]
        if values.size > MAX_EXACT_STAT_CELLS:
            step = max(1, int(np.ceil(values.shape[0] / max(1, MAX_EXACT_STAT_CELLS // returned))))
            values = values[::step, :]
            base["approximate"] = True
            base["sampled"] = True
            base["sample_plan"] = {
                "reason": "feature statistics exceed exact cell limit",
                "source_rows": int(X.shape[0]),
                "sampled_rows": int(values.shape[0]),
                "row_step": step,
            }
        stat_values = _compute(values, 0)
        labels = list(feature_axis.labels) if feature_axis and feature_axis.labels is not None else None
        coordinates = np.asarray(feature_axis.values) if feature_axis and feature_axis.values is not None else None
        rows = []
        for offset, index in enumerate(selected_indices):
            row: dict[str, Any] = {"index": index}
            if labels and index < len(labels):
                row["label"] = _metadata_text(labels[index])
            if coordinates is not None and index < len(coordinates):
                row["coordinate"] = _safe_float(coordinates[index])
            for stat, values in stat_values.items():
                if isinstance(values, list) and offset < len(values):
                    row[stat] = values[offset]
            rows.append(row)
        base.update({"n_features": count, "truncated": truncated, "features": rows})
        return base

    count = X.shape[0]
    selected_indices, selection = _resolve_axis_selectors(
        sample_selectors,
        axis_info=sample_axis,
        count=count,
        axis_name="samples",
    )
    if selected_indices is None:
        returned = min(count, limit)
        selected_indices = list(range(returned))
        truncated = count > limit
    else:
        returned = len(selected_indices)
        truncated = bool(selection and selection["truncated"])
        base["selection"] = selection
    values = X[selected_indices, :]
    if values.size > MAX_EXACT_STAT_CELLS:
        step = max(1, int(np.ceil(values.shape[1] / max(1, MAX_EXACT_STAT_CELLS // returned))))
        values = values[:, ::step]
        base["approximate"] = True
        base["sampled"] = True
        base["sample_plan"] = {
            "reason": "sample statistics exceed exact cell limit",
            "source_columns": int(X.shape[1]),
            "sampled_columns": int(values.shape[1]),
            "column_step": step,
        }
    stat_values = _compute(values, 1)
    labels = list(sample_axis.labels) if sample_axis and sample_axis.labels is not None else None
    coordinates = np.asarray(sample_axis.values) if sample_axis and sample_axis.values is not None else None
    classes = list(sample_axis.classes) if sample_axis and sample_axis.classes is not None else None
    rows = []
    for offset, index in enumerate(selected_indices):
        row: dict[str, Any] = {"index": index}
        if labels and index < len(labels):
            row["label"] = _metadata_text(labels[index])
        if coordinates is not None and index < len(coordinates):
            row["coordinate"] = _safe_float(coordinates[index])
        if classes and index < len(classes):
            row["class"] = _metadata_text(classes[index])
        for stat, values in stat_values.items():
            if isinstance(values, list) and offset < len(values):
                row[stat] = values[offset]
        rows.append(row)
    base.update({"n_samples": count, "truncated": truncated, "samples": rows})
    return base


@register_tool(
    "get_dataset_quality",
    "Get quality metrics and evaluation results for a dataset.",
    category=ToolCategory.data,
    requires_user=True,
    parameters={
        "type": "object",
        "properties": {
            "dataset_id": {
                "type": "string",
                "description": "Dataset handle ID",
            },
        },
        "required": ["dataset_id"],
    },
)
def get_dataset_quality(dataset_id: str, user: Any = None) -> dict[str, Any]:
    """Extract quality metrics and evaluation history from a dataset handle."""
    ds = _load_dataset(dataset_id, user=user)

    q = ds.quality
    result: dict[str, Any] = {
        "dataset_id": ds.dataset_id,
        "snr": q.snr,
        "n_evaluations": len(q.evaluations),
    }
    if q.latest:
        result["latest"] = q.latest.model_dump(exclude_none=True)
    return result
