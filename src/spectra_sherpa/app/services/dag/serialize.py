"""
Single source of truth for dataset -> API JSON serialization.

Called ONLY at the API boundary (in routes/workflows.py).

Usage:
    from spectra_sherpa.app.services.dag.serialize import serialize_for_api

    # In API route:
    result = serialize_for_api(dataset, sanitize_paths=True)
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Dict

import numpy as np

from spectra_sherpa.app.lib.collection_assembly import validate_lossless_sample_table_wire
from spectra_sherpa.app.lib.domain_flags import infer_is_spectra
from spectra_sherpa.app.lib.sample_labels import clean_sample_labels
from spectra_sherpa.app.lib.sherpa_dataset import (
    SherpaDataset,
    _slice_axis,
    _slice_observation_axis,
)
from spectra_sherpa.app.services.dag.transport import reject_spectrochempy_transport

# Scientist-facing workflow responses are previews, not bulk array transport.
# Full typed values remain available through the registered dataset handle.
API_DATASET_FULL_PAYLOAD_MAX_NUMERIC_ELEMENTS = 1_000_000
API_DATASET_PREVIEW_MAX_NUMERIC_ELEMENTS = 100_000
API_DATASET_PREVIEW_CORE_MAX_NUMERIC_ELEMENTS = 30_000
API_DATASET_PREVIEW_TARGET_MAX_NUMERIC_ELEMENTS = 10_000
API_DATASET_PREVIEW_MAX_SAMPLES = 100
API_METADATA_ARRAY_MAX_NUMERIC_ELEMENTS = 100_000
API_METADATA_AGGREGATE_MAX_NUMERIC_ELEMENTS = 40_000
API_METADATA_SEQUENCE_MAX_ITEMS = 10_000
API_METADATA_SEQUENCE_PREVIEW_ITEMS = 32


@dataclass
class _NumericBudget:
    remaining: int

    def consume(self, count: int) -> bool:
        count = max(0, int(count))
        if count > self.remaining:
            return False
        self.remaining -= count
        return True


from .meta_helpers import (
    detect_data_quantity,
    detect_spectral_technique,
)


def _json_safe(obj: Any) -> Any:
    """Recursively convert values to JSON-serializable types.

    Handles datetime, NumPy types, and other non-serializable metadata values.
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (frozenset, set)):
        return sorted(_json_safe(v) for v in obj)
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    # Fallback: convert to string
    return str(obj)


def _numeric_projection_exceeds(dataset: SherpaDataset, limit: int) -> bool:
    """Return whether the ordinary JSON projection exceeds ``limit`` values.

    Repeated ndarray references are counted repeatedly because an ordinary
    recursive JSON projection would box each occurrence independently.
    Traversal stops as soon as the declared output ceiling is crossed.
    """

    remaining = int(limit)

    def account(value: Any) -> bool:
        nonlocal remaining
        if isinstance(value, np.ndarray):
            remaining -= int(value.size)
            return remaining < 0
        if isinstance(value, (np.integer, np.floating, int, float)) and not isinstance(value, bool):
            remaining -= 1
            return remaining < 0
        if isinstance(value, dict):
            return any(account(nested) for nested in value.values())
        if isinstance(value, (list, tuple)):
            return any(account(nested) for nested in value)
        return False

    if account(dataset.X) or account(dataset.target):
        return True
    axes = (dataset.sample_axis, *dataset.inner_axes.values(), dataset.feature_axis)
    for axis in axes:
        if axis is None:
            continue
        if account(axis.model_dump(mode="python")):
            return True
    return account(dataset.meta)


def _bounded_json_safe(
    obj: Any,
    *,
    path: str = "extra",
    seen_arrays: dict[int, str] | None = None,
    numeric_budget: _NumericBudget | None = None,
) -> Any:
    """Project metadata under per-array and aggregate numeric ceilings."""

    if seen_arrays is None:
        seen_arrays = {}
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, (int, float)):
        if numeric_budget is not None and not numeric_budget.consume(1):
            return {"_truncated_numeric": True, "reason": "api_aggregate_numeric_ceiling"}
        return obj
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, np.integer):
        if numeric_budget is not None and not numeric_budget.consume(1):
            return {"_truncated_numeric": True, "reason": "api_aggregate_numeric_ceiling"}
        return int(obj)
    if isinstance(obj, np.floating):
        if numeric_budget is not None and not numeric_budget.consume(1):
            return {"_truncated_numeric": True, "reason": "api_aggregate_numeric_ceiling"}
        return float(obj)
    if isinstance(obj, np.ndarray):
        identity = id(obj)
        previous = seen_arrays.get(identity)
        if previous is not None:
            return {"_array_reference": previous}
        seen_arrays[identity] = path
        if obj.size > API_METADATA_ARRAY_MAX_NUMERIC_ELEMENTS or (
            numeric_budget is not None and not numeric_budget.consume(obj.size)
        ):
            return {
                "_truncated_array": True,
                "shape": "x".join(str(value) for value in obj.shape),
                "dtype": str(obj.dtype),
                "reason": "api_aggregate_numeric_ceiling",
            }
        return obj.tolist()
    if isinstance(obj, (frozenset, set)):
        return sorted(
            _bounded_json_safe(
                value,
                path=f"{path}[]",
                seen_arrays=seen_arrays,
                numeric_budget=numeric_budget,
            )
            for value in obj
        )
    if isinstance(obj, dict):
        return {
            str(key): _bounded_json_safe(
                value,
                path=f"{path}.{key}",
                seen_arrays=seen_arrays,
                numeric_budget=numeric_budget,
            )
            for key, value in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        if len(obj) > API_METADATA_SEQUENCE_MAX_ITEMS:
            return {
                "_truncated_sequence": True,
                "length": len(obj),
                "preview": [
                    _bounded_json_safe(
                        value,
                        path=f"{path}[{index}]",
                        seen_arrays=seen_arrays,
                        numeric_budget=numeric_budget,
                    )
                    for index, value in enumerate(obj[:API_METADATA_SEQUENCE_PREVIEW_ITEMS])
                ],
            }
        return [
            _bounded_json_safe(
                value,
                path=f"{path}[{index}]",
                seen_arrays=seen_arrays,
                numeric_budget=numeric_budget,
            )
            for index, value in enumerate(obj)
        ]
    return str(obj)


def _bounded_dataset_preview(dataset: SherpaDataset) -> Dict[str, Any]:
    """Build an aligned browser preview without materializing the full result."""

    original_shape = tuple(int(value) for value in dataset.shape)
    n_samples, n_features = original_shape[0], original_shape[-1]
    selected_shape = list(original_shape)
    non_sample_cells = math.prod(original_shape[1:])
    if non_sample_cells <= API_DATASET_PREVIEW_CORE_MAX_NUMERIC_ELEMENTS:
        selected_shape[0] = min(
            n_samples,
            API_DATASET_PREVIEW_MAX_SAMPLES,
            max(1, API_DATASET_PREVIEW_CORE_MAX_NUMERIC_ELEMENTS // non_sample_cells),
        )
    else:
        selected_shape[0] = 1
    while math.prod(selected_shape) > API_DATASET_PREVIEW_CORE_MAX_NUMERIC_ELEMENTS:
        candidates = [index for index, size in enumerate(selected_shape) if index > 0 and size > 1]
        if not candidates:
            break
        dimension = max(candidates, key=lambda index: selected_shape[index])
        selected_shape[dimension] = max(1, math.ceil(selected_shape[dimension] / 2))
    strides = [
        max(1, math.ceil(size / selected)) for size, selected in zip(original_shape, selected_shape, strict=True)
    ]
    slices = tuple(slice(0, None, stride) for stride in strides)
    sample_slice = slices[0]
    feature_slice = slices[-1]
    preview_X = dataset.X[slices]
    preview_target = None
    if dataset.target is not None:
        candidate = np.asarray(dataset.target)[sample_slice]
        if candidate.size <= API_DATASET_PREVIEW_TARGET_MAX_NUMERIC_ELEMENTS:
            preview_target = candidate

    preview_layout = dataset.layout.model_copy(deep=True, update={"source_shape": tuple(preview_X.shape)})
    preview = SherpaDataset(
        X=preview_X,
        feature_axis=_slice_axis(dataset.feature_axis, feature_slice),
        sample_axis=(
            sliced if (sliced := _slice_observation_axis(dataset.sample_axis, sample_slice)) is not None else None
        ),
        axes={
            dimension: sliced
            for dimension, axis in dataset.inner_axes.items()
            if (sliced := _slice_axis(axis, slices[dimension])) is not None
        }
        or None,
        target=preview_target,
        target_context=dataset.target_context.model_copy(deep=True),
        domain=dataset.domain.model_copy(deep=True),
        descriptive=dataset.descriptive.model_copy(deep=True),
        source_identity=dataset.source_identity.model_copy(deep=True),
        source_history=dataset.source_history.model_copy(deep=True),
        layout=preview_layout,
        provenance=dataset.provenance.copy(),
        quality=dataset.quality.model_copy(deep=True),
        backend=dataset.backend,
        title=dataset.title,
        units=dataset.units,
        data_role=dataset.data_role,
        is_time_series=dataset.is_time_series,
    )
    result = preview.to_dict(include_extra=False)
    result.update(
        {
            "dataset_id": dataset.dataset_id,
            "shape": list(original_shape),
            "ndim": dataset.X.ndim,
            "n_samples": n_samples,
            "n_features": n_features,
            "preview_shape": list(preview_X.shape),
            "scientific_projection": dataset.scientific_projection(
                include_data=False,
                include_sample_table=False,
            ),
            "extra": _bounded_json_safe(
                dataset.meta,
                numeric_budget=_NumericBudget(API_METADATA_AGGREGATE_MAX_NUMERIC_ELEMENTS),
            ),
        }
    )
    result.setdefault("metadata", {}).update(
        {
            "data_truncated": True,
            "preview_shape": list(preview_X.shape),
            "dimension_strides": strides,
            "sample_stride": strides[0],
            "feature_stride": strides[-1],
            "target_truncated": dataset.target is not None and preview_target is None,
        }
    )
    return result


def _project_dataset_for_api(
    dataset: SherpaDataset,
    *,
    owner_user_id: int | None,
    dataset_register: Callable[[SherpaDataset, int | None], object] | None,
) -> tuple[Dict[str, Any], bool, str | None, str | None]:
    """Register the full typed value and choose a bounded wire projection."""

    sample_axis = dataset.sample_axis
    validate_lossless_sample_table_wire(sample_axis.sample_table if sample_axis is not None else None)

    registered_dataset_id: object | None = None
    if dataset_register is not None:
        registered_dataset_id = dataset_register(dataset, owner_user_id)
    registration_unavailable_reason = None
    if registered_dataset_id is None:
        registration_unavailable_reason = (
            "dataset_registry_not_configured" if dataset_register is None else "dataset_exceeds_in_memory_handle_budget"
        )
    is_bounded_preview = _numeric_projection_exceeds(
        dataset,
        API_DATASET_FULL_PAYLOAD_MAX_NUMERIC_ELEMENTS,
    )
    result = _bounded_dataset_preview(dataset) if is_bounded_preview else dataset.to_dict(include_extra=False)
    if dataset.meta:
        result["extra"] = _bounded_json_safe(
            dataset.meta,
            numeric_budget=_NumericBudget(API_METADATA_AGGREGATE_MAX_NUMERIC_ELEMENTS),
        )
    registered_handle = str(registered_dataset_id) if registered_dataset_id is not None else None
    if registered_handle is not None:
        result["dataset_id"] = registered_handle
    result["scientific_projection"] = dataset.scientific_projection(
        include_data=False,
        include_sample_table=False,
    )
    result["manifest"] = dataset.manifest.model_dump(mode="json")
    return result, is_bounded_preview, registered_handle, registration_unavailable_reason


def _count_wire_numeric_values(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, (int, float, np.integer, np.floating)):
        return 1
    if isinstance(value, dict):
        return sum(_count_wire_numeric_values(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_count_wire_numeric_values(item) for item in value)
    return 0


def _handle_only_projection(result: Dict[str, Any], *, reason: str) -> Dict[str, Any]:
    """Return a minimal truthful response if the final wire budget is exceeded."""

    api_serialization = dict((result.get("metadata") or {}).get("api_serialization") or {})
    api_serialization["mode"] = "handle_only"
    return {
        key: value
        for key, value in {
            "type": result.get("type", "SherpaDataset"),
            "version": result.get("version", "3.0"),
            "dataset_id": result.get("dataset_id"),
            "shape": result.get("shape", []),
            "ndim": result.get("ndim"),
            "data": [],
            "n_samples": result.get("n_samples"),
            "n_features": result.get("n_features"),
            "title": result.get("title"),
            "units": result.get("units"),
            "backend": result.get("backend"),
            "data_role": result.get("data_role"),
            "data_modality": result.get("data_modality"),
            "domain": result.get("domain", {}),
            "target_context": result.get("target_context", {}),
            "descriptive": result.get("descriptive", {}),
            "source_identity": result.get("source_identity", {}),
            "layout": result.get("layout", {}),
            "scientific_projection": result.get("scientific_projection", {}),
            "manifest": result.get("manifest", {}),
            "metadata": {
                "api_serialization": api_serialization,
                "data_truncated": True,
                "preview_unavailable_reason": reason,
            },
        }.items()
        if value is not None
    }


def _enforce_result_wire_limit(result: Dict[str, Any], *, is_bounded_preview: bool) -> Dict[str, Any]:
    wire_limit = (
        API_DATASET_PREVIEW_MAX_NUMERIC_ELEMENTS
        if is_bounded_preview
        else API_DATASET_FULL_PAYLOAD_MAX_NUMERIC_ELEMENTS
    )
    if _count_wire_numeric_values(result) <= wire_limit:
        return result
    return _handle_only_projection(
        result,
        reason="aggregate_wire_numeric_element_ceiling",
    )


def finalize_api_dataset_response(result: Dict[str, Any]) -> Dict[str, Any]:
    """Enforce the canonical wire ceiling after route-specific enrichment."""

    metadata = result.get("metadata")
    api_serialization = metadata.get("api_serialization") if isinstance(metadata, dict) else None
    mode = api_serialization.get("mode") if isinstance(api_serialization, dict) else None
    return _enforce_result_wire_limit(result, is_bounded_preview=mode == "bounded_preview")


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _format_sample_label(value: Any) -> str:
    """Convert raw sample label values to a readable string.

    Handles common coordinate label shapes like:
    - plain strings
    - datetime objects
    - tuples/lists such as [timestamp, sample_name]
    """
    if value is None:
        return ""

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            return _format_sample_label(value.item())
        return _format_sample_label(value.tolist())

    if isinstance(value, (list, tuple)):
        # Common case from imported coordinates: [timestamp, human_readable_name]
        for item in reversed(value):
            if isinstance(item, str) and item.strip():
                return item.strip()
        parts = [_format_sample_label(item) for item in value]
        parts = [part for part in parts if part]
        return " | ".join(parts)

    if isinstance(value, str):
        text = value.strip()
        # Handle stringified tuple/list labels such as:
        # "[datetime.datetime(...), 'Human Sample Name']"
        if text.startswith("[") or text.startswith("("):
            quoted = [
                (m.group(1) or m.group(2)).strip()
                for m in re.finditer(r"'([^']+)'|\"([^\"]+)\"", text)
                if (m.group(1) or m.group(2))
            ]
            if quoted:
                return quoted[-1]
        return text

    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="ignore")
        except Exception:
            return str(value)

    return str(value)


def _safe_coord_data(coord: Any) -> Any:
    """Safely extract coordinate data without raising on malformed coord objects.

    Third-party coordinate-like objects can raise when their ``data`` property
    is accessed with an incomplete internal buffer. This helper keeps legacy
    display metadata best-effort without admitting those objects as scientific
    transport.
    """
    if coord is None:
        return None
    try:
        return coord.data
    except Exception:
        return None


def _safe_coord_labels(coord: Any) -> Any:
    """Safely extract coordinate labels without raising."""
    if coord is None:
        return None
    try:
        labels = getattr(coord, "labels", None)
    except Exception:
        return None
    return labels


def _safe_coord_list(coord_values: Any) -> list[Any]:
    """Convert coordinate payload to a plain Python list safely."""
    if coord_values is None:
        return []
    try:
        if hasattr(coord_values, "tolist"):
            values = coord_values.tolist()
            if isinstance(values, list):
                return values
            return [values]
        if isinstance(coord_values, (list, tuple)):
            return list(coord_values)
        arr = np.asarray(coord_values)
        if arr.ndim == 0:
            return [arr.item()]
        return arr.tolist()
    except Exception:
        try:
            return [coord_values]
        except Exception:
            return []


def _safe_attr(obj: Any, attr: str, default: Any = None) -> Any:
    """Safely access object attribute without propagating backend-internal errors."""
    if obj is None:
        return default
    try:
        value = getattr(obj, attr)
    except Exception:
        return default
    return default if value is None else value


def _safe_str_attr(obj: Any, attr: str, default: str = "") -> str:
    """Safely convert attribute to string."""
    value = _safe_attr(obj, attr, None)
    if value is None:
        return default
    try:
        return str(value)
    except Exception:
        return default


def _meta_get(meta: Any, key: str, default: Any = None) -> Any:
    """Best-effort metadata lookup for dict-like or object-like meta containers."""
    if meta is None:
        return default
    try:
        if isinstance(meta, dict):
            return meta.get(key, default)
        if hasattr(meta, "get"):
            value = meta.get(key, default)
            return default if value is None else value
    except Exception:
        pass
    try:
        return meta[key]
    except Exception:
        pass
    try:
        value = getattr(meta, key)
        return default if value is None else value
    except Exception:
        return default


def _meta_items(meta: Any) -> list[tuple[Any, Any]]:
    """Best-effort conversion of metadata container to key/value pairs."""
    if meta is None:
        return []
    if isinstance(meta, dict):
        return list(meta.items())
    try:
        return list(dict(meta).items())
    except Exception:
        pass
    try:
        keys = list(meta.keys())
        return [(key, _meta_get(meta, key)) for key in keys]
    except Exception:
        return []


def _add_sample_class_metadata(metadata: dict[str, Any], axis: dict[str, Any]) -> None:
    classes = axis.get("classes")
    if not classes:
        return
    metadata["sample_classes"] = [str(value) for value in classes]
    metadata["label_categories"] = list(dict.fromkeys(metadata["sample_classes"]))


def _add_categorical_target_metadata(metadata: dict[str, Any], dataset: SherpaDataset) -> None:
    if metadata.get("sample_classes") or dataset.target_context.target_type != "categorical":
        return
    target = dataset.target
    if target is None:
        return
    values = np.asarray(target, dtype=object)
    if values.ndim == 2 and values.shape[1] == 1:
        values = values[:, 0]
    if values.ndim != 1 or values.shape[0] != dataset.shape[0]:
        return
    metadata["sample_classes"] = [str(value) for value in values.tolist()]
    metadata["label_categories"] = list(dict.fromkeys(metadata["sample_classes"]))


def _detect_dataset_quantities(dataset: SherpaDataset) -> tuple[Any, Any]:
    try:
        return detect_spectral_technique(dataset), detect_data_quantity(dataset)
    except Exception:
        return None, None


def admit_retained_value(value: Any, *, max_values: int = 500_000, max_bytes: int = 8 * 1024 * 1024) -> None:
    """Bound JSON materialization without depending on application storage."""
    remaining = max_values
    text_bytes = 0

    def visit(item: Any, depth: int = 0) -> None:
        nonlocal remaining, text_bytes
        if depth > 64:
            raise ValueError("Output exceeds the retained nesting limit")
        remaining -= 1
        if isinstance(item, SherpaDataset):
            for part in (
                item.X,
                item.target,
                item.meta,
                item.sample_axis,
                item.feature_axis,
                item.inner_axes,
                item.layout,
                item.extra,
                item.domain,
                item.target_context,
                item.descriptive,
                item.source_identity,
                item.source_history,
                item.quality,
                item.state,
                item.branch_info,
                item.provenance.to_list(),
            ):
                visit(part, depth + 1)
        elif isinstance(item, np.ndarray):
            remaining -= item.size
            if item.dtype.kind in "OUS":
                text_bytes += item.nbytes
                if item.size <= max_values:
                    for part in item.flat:
                        visit(str(part), depth + 1)
        elif isinstance(item, dict):
            for key, part in item.items():
                visit(key, depth + 1)
                visit(part, depth + 1)
        elif isinstance(item, (list, tuple)):
            for part in item:
                visit(part, depth + 1)
        elif isinstance(item, str):
            text_bytes += len(item) * 6
        elif hasattr(item, "model_dump"):
            visit(item.model_dump(mode="python"), depth + 1)
        if remaining < 0 or text_bytes > max_bytes:
            raise ValueError("Output exceeds the retained materialization budget")

    visit(value)


def _retained_dataset_projection(dataset: SherpaDataset) -> Dict[str, Any]:
    admit_retained_value(dataset)
    result = dataset.to_dict(include_extra=True)
    result["scientific_projection"] = dataset.scientific_projection(include_data=False, include_sample_table=False)
    result["manifest"] = dataset.manifest.model_dump(mode="json")
    if not np.isfinite(dataset.X).all():
        result["retention_nonfinite_values"] = True
    return result


def _serialize_sherpa_dataset(
    dataset: SherpaDataset,
    sanitize_paths: bool = False,
    owner_user_id: int | None = None,
    dataset_register: Callable[[SherpaDataset, int | None], object] | None = None,
    retain_full: bool = False,
) -> Dict[str, Any]:
    """Serialize SherpaDataset to API-compatible JSON format."""
    if retain_full:
        result = _retained_dataset_projection(dataset)
        is_bounded_preview, registered_handle, registration_unavailable_reason = False, None, None
    else:
        result, is_bounded_preview, registered_handle, registration_unavailable_reason = _project_dataset_for_api(
            dataset,
            owner_user_id=owner_user_id,
            dataset_register=dataset_register,
        )

    # Remap axis keys for frontend compatibility
    # SherpaDataset.to_dict() uses spectral_axis/sample_axis but the
    # frontend expects the canonical x_axis/y_axis wire projection.
    if "feature_axis" in result:
        result["x_axis"] = result.pop("feature_axis")
    if "sample_axis" in result:
        result["y_axis"] = result.pop("sample_axis")

    # Enrich with spectral detection
    technique, data_quantity = _detect_dataset_quantities(dataset)
    feature_axis = dataset.get_feature_axis()
    is_spectra = infer_is_spectra(
        dataset.meta.get("is_spectra") if isinstance(dataset.meta, dict) else None,
        technique=technique or dataset.domain.technique,
        x_title=feature_axis.title if feature_axis is not None else None,
        x_units=feature_axis.units if feature_axis is not None else None,
    )

    metadata = result.setdefault("metadata", {})
    metadata["api_serialization"] = {
        "mode": "bounded_preview" if is_bounded_preview else "full",
        "full_payload_numeric_element_ceiling": API_DATASET_FULL_PAYLOAD_MAX_NUMERIC_ELEMENTS,
        "preview_numeric_element_ceiling": API_DATASET_PREVIEW_MAX_NUMERIC_ELEMENTS,
        "metadata_array_numeric_element_ceiling": API_METADATA_ARRAY_MAX_NUMERIC_ELEMENTS,
        "metadata_aggregate_numeric_element_ceiling": API_METADATA_AGGREGATE_MAX_NUMERIC_ELEMENTS,
        "full_dataset_handle": registered_handle,
        "full_dataset_handle_unavailable_reason": registration_unavailable_reason,
    }
    metadata["data_type"] = "spectra" if is_spectra else "generic"
    metadata["is_spectra"] = is_spectra
    metadata["is_time_series"] = dataset.is_time_series
    metadata["spectral_technique"] = technique
    if data_quantity is not None:
        metadata["data_quantity"] = data_quantity

    # Convenience copies of axis info into metadata (frontend compat)
    if result.get("x_axis"):
        x_ax = result["x_axis"]
        x_units = x_ax.get("units") or ""
        if x_units == "dimensionless":
            x_ax["units"] = ""
            x_units = ""
        if not is_bounded_preview and x_ax.get("data") is not None:
            metadata["wavenumbers"] = x_ax["data"]
        else:
            # A categorical feature axis has labels, not zero coordinates.
            # Do not manufacture a contradictory empty aligned vector.
            metadata.pop("wavenumbers", None)
        x_title = _optional_text(x_ax.get("title"))
        if x_title is not None:
            metadata["x_title"] = x_title
        if x_units:
            metadata["x_units"] = x_units
        if x_ax.get("labels"):
            metadata["feature_names"] = x_ax["labels"]

    if result.get("y_axis"):
        y_ax = result["y_axis"]
        y_units = y_ax.get("units") or ""
        if y_units == "dimensionless":
            y_ax["units"] = ""
            y_units = ""
        y_title = _optional_text(y_ax.get("title"))
        if y_title is not None:
            metadata["y_title"] = y_title
        if y_units:
            metadata["y_units"] = y_units
        if y_ax.get("labels"):
            formatted = clean_sample_labels(y_ax["labels"], len(y_ax["labels"]), fallback_prefix="Sample")
            metadata["sample_labels"] = formatted
            metadata["labels"] = formatted
        _add_sample_class_metadata(metadata, y_ax)
    _add_categorical_target_metadata(metadata, dataset)

    # Data units: emit only when the dataset or source metadata defines them.
    if dataset.units and str(dataset.units) != "dimensionless":
        metadata["value_units"] = str(dataset.units)
    semantic_units = dataset.get_extra("spectrasherpa.value_units_label")
    if semantic_units:
        metadata["value_units_label"] = str(semantic_units)
        metadata.setdefault("value_units", str(semantic_units))

    # Rich provenance from SherpaDataset.provenance
    history = dataset.provenance.to_list()
    if history:
        metadata["processing_history"] = history
        metadata["provenance"] = {
            "operations": [step.get("op_id", "unknown") for step in history],
            "last_modified": history[-1].get("timestamp") if history else None,
        }

    # Path sanitization
    if sanitize_paths:
        PATH_FIELDS = {"original_file_path", "original_source", "background_file", "original_filename"}
        for key in PATH_FIELDS:
            if key in metadata and isinstance(metadata[key], str):
                metadata[key] = os.path.basename(metadata[key])

    # Merge canonical extra metadata into the frontend metadata projection.
    if result.get("extra") and not is_bounded_preview:
        for k, v in result["extra"].items():
            if k not in metadata:
                metadata[k] = v

    # Quality metrics summary — merge regression-centric evaluation keys into
    # whatever quality_summary the node may have already set (e.g. PCA emits
    # explained_variance_ratio, T²/SPE limits). Must run AFTER the extras
    # merge so the node-native dict is visible in metadata; otherwise the
    # regression shim would clobber PCA/PLS/etc. keys.
    if dataset.quality.evaluations:
        latest = dataset.quality.latest
        evaluation_summary = {
            "n_evaluations": len(dataset.quality.evaluations),
            "latest_model_type": latest.model_type if latest else None,
            "latest_r2": latest.r2 if latest else None,
            "latest_rmse": latest.rmse if latest else None,
        }
        existing = metadata.get("quality_summary")
        if isinstance(existing, dict):
            for k, v in evaluation_summary.items():
                if v is not None and k not in existing:
                    existing[k] = v
        else:
            metadata["quality_summary"] = evaluation_summary

    # Title fallback
    if not result.get("title"):
        result["title"] = "Spectra" if is_spectra else "Data"

    # Final JSON-safety pass
    result["metadata"] = _json_safe(metadata)

    return result if retain_full else finalize_api_dataset_response(result)


def serialize_for_api(
    dataset,
    sanitize_paths: bool = False,
    owner_user_id: int | None = None,
    dataset_register: Callable[[SherpaDataset, int | None], object] | None = None,
    retain_full: bool = False,
) -> Dict[str, Any]:
    """
    Serialize dataset to API-compatible JSON format.

    This is the SINGLE SOURCE OF TRUTH for serialization.
    Called only at API boundary, not inside nodes.

    Args:
        dataset: Canonical SherpaDataset
        sanitize_paths: If True, strip file paths to basenames

    Returns:
        Dict ready for JSON response
    """
    reject_spectrochempy_transport(dataset, boundary="dataset API serialization")

    # Primary path: SherpaDataset
    if isinstance(dataset, SherpaDataset):
        return _serialize_sherpa_dataset(
            dataset,
            sanitize_paths,
            owner_user_id=owner_user_id,
            dataset_register=dataset_register,
            retain_full=retain_full,
        )

    raise TypeError(f"serialize_for_api requires SherpaDataset, received {type(dataset).__name__}")
