"""
Single source of truth for NDDataset -> API JSON serialization.

This replaces SpectralResult.to_api_json() with a standalone function.
Called ONLY at API boundary (in routes/workflows.py).

Usage:
    from app.services.dag.serialize import serialize_for_api

    # In API route:
    result = serialize_for_api(dataset, sanitize_paths=True)
"""

from __future__ import annotations

import os
import re
from datetime import datetime, date
from typing import Any, Dict, Optional
import numpy as np

from app.lib.scp_compat import NDDataset, HAS_SCP
HAS_NDDATASET = HAS_SCP

from .meta_helpers import (
    get_processing_history,
    detect_spectral_technique,
    detect_data_quantity,
)


def _json_safe(obj: Any) -> Any:
    """Recursively convert values to JSON-serializable types.

    Handles datetime, numpy types, and other non-serializable objects
    that may appear in SpectroChemPy metadata.
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
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    # Fallback: convert to string
    return str(obj)


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

    Some SpectroChemPy coordinate objects can raise errors (including
    `TypeError: object of type 'NoneType' has no len()`) when their `data`
    property is accessed if internal buffers are missing. This helper ensures
    serialization remains best-effort and never fails hard on coordinate access.
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


def serialize_for_api(
    dataset: NDDataset,
    sanitize_paths: bool = False,
) -> Dict[str, Any]:
    """
    Serialize NDDataset to API-compatible JSON format.

    This is the SINGLE SOURCE OF TRUTH for serialization.
    Called only at API boundary, not inside nodes.

    Args:
        dataset: NDDataset to serialize
        sanitize_paths: If True, strip file paths to basenames

    Returns:
        Dict ready for JSON response
    """
    # Convert data, replacing NaN/Inf with None for JSON safety
    try:
        raw_data = np.asarray(dataset.data, dtype=float)
    except Exception:
        # Defensive fallback: keep serializer alive even if backend data payload
        # is temporarily malformed.
        raw_data = np.asarray([], dtype=float)
    # Replace NaN and Inf with None (JSON-safe)
    data_list = np.where(np.isfinite(raw_data), raw_data, None).tolist()

    try:
        dataset_shape = list(dataset.shape)
    except Exception:
        dataset_shape = list(raw_data.shape)
    if len(dataset_shape) == 0:
        dataset_shape = [0]

    result = {
        "type": "NDDataset",
        "shape": dataset_shape,
        "data": data_list,
        "n_samples": dataset_shape[0] if len(dataset_shape) > 1 else 1,
        "n_features": dataset_shape[-1] if len(dataset_shape) > 0 else 0,
        "metadata": {},
    }

    # X-axis
    # NOTE: SpectroChemPy's __getattr__ raises KeyError (not AttributeError)
    # when a coordinate name like 'x' is not found, so hasattr() alone is insufficient.
    try:
        x_coord = dataset.x
    except Exception:
        x_coord = None

    if x_coord is not None:
        x_raw = _safe_coord_data(x_coord)
        try:
            x_data = np.array(x_raw, dtype=float).tolist() if x_raw is not None else []
        except Exception:
            x_data = [str(v) for v in _safe_coord_list(x_raw)]
        x_title = _safe_str_attr(x_coord, "title", "Feature") or "Feature"
        x_units = _safe_str_attr(x_coord, "units", "")
        if x_units == "dimensionless":
            x_units = ""

        result["x_axis"] = {
            "title": x_title,
            "units": x_units,
            "data": x_data,
        }
        result["metadata"]["wavenumbers"] = x_data
        result["metadata"]["x_title"] = x_title
        result["metadata"]["x_units"] = x_units

    # Spectral detection
    try:
        technique = detect_spectral_technique(dataset)
        data_quantity = detect_data_quantity(dataset)
    except Exception:
        technique = None
        data_quantity = None
    is_spectra = technique is not None

    result["metadata"]["data_type"] = "spectra" if is_spectra else "generic"
    result["metadata"]["is_spectra"] = is_spectra
    result["metadata"]["spectral_technique"] = technique
    result["metadata"]["data_quantity"] = data_quantity
    dataset_meta = _safe_attr(dataset, "meta", None)

    # Y-axis (sample labels)
    try:
        y_coord = dataset.y
    except Exception:
        y_coord = None

    if y_coord is not None:
        y_title = _safe_str_attr(y_coord, "title", "Sample") or "Sample"
        y_units = _safe_str_attr(y_coord, "units", "")
        if y_units == "dimensionless":
            y_units = ""
        y_raw = _safe_coord_data(y_coord)
        try:
            y_data = np.array(y_raw, dtype=float).tolist() if y_raw is not None else []
        except Exception:
            # String or non-numeric y-axis data — convert to string list
            y_data = [str(v) for v in _safe_coord_list(y_raw)]

        # Extract labels from y-axis (file names, sample names, etc.)
        y_labels = None
        try:
            labels_raw = _safe_coord_labels(y_coord)
            if labels_raw is not None:
                # Handle both list and ndarray of labels
                if hasattr(labels_raw, 'tolist'):
                    labels_list = labels_raw.tolist()
                elif isinstance(labels_raw, (list, tuple)):
                    labels_list = list(labels_raw)
                else:
                    labels_list = None

                if labels_list is not None:
                    # Convert to readable strings. Labels may contain
                    # datetime objects or tuple/list payloads.
                    y_labels = [_format_sample_label(v) for v in labels_list]
        except Exception:
            y_labels = None

        # If coord values are unavailable but we do have labels, synthesize row indices.
        if len(y_data) == 0 and y_labels:
            y_data = list(range(len(y_labels)))

        result["y_axis"] = {
            "title": y_title,
            "units": y_units,
            "data": y_data,
            "labels": y_labels,  # Include labels in y_axis
        }
        result["metadata"]["y_title"] = y_title
        result["metadata"]["y_units"] = y_units

        # Also add to metadata for frontend compatibility (DataTableModal expects these)
        if y_labels:
            result["metadata"]["sample_labels"] = y_labels
            result["metadata"]["labels"] = y_labels  # Alias for backwards compat

    # Data units
    dataset_units = _safe_str_attr(dataset, "units", "")
    if dataset_units and dataset_units != "dimensionless":
        result["metadata"]["value_units"] = dataset_units
    if dataset_meta is not None:
        semantic_units = _meta_get(dataset_meta, "value_units_label")
        if semantic_units:
            semantic_units_text = str(semantic_units)
            result["metadata"]["value_units_label"] = semantic_units_text
            result["metadata"].setdefault("value_units", semantic_units_text)

    # Processing history from meta
    try:
        history = get_processing_history(dataset)
    except Exception:
        history = []
    if history:
        result["metadata"]["processing_history"] = history

    # Build provenance: merge rich provenance from meta with processing history summary
    # Start with rich provenance from dataset.meta (original_source_type, operator, lab_name, etc.)
    rich_provenance: dict | Any | None = None
    if dataset_meta:
        meta_provenance = _meta_get(dataset_meta, "provenance")
        if isinstance(meta_provenance, dict):
            rich_provenance = dict(meta_provenance)
        elif meta_provenance:
            rich_provenance = meta_provenance

    # Add/update processing history derived fields without clobbering rich provenance
    if history:
        if rich_provenance is None:
            rich_provenance = {
                "operations": [step.get("operation", "unknown") for step in history],
                "last_modified": history[-1].get("timestamp") if history else None,
            }
        elif isinstance(rich_provenance, dict):
            rich_provenance.setdefault(
                "operations",
                [step.get("operation", "unknown") for step in history],
            )
            rich_provenance.setdefault(
                "last_modified",
                history[-1].get("timestamp") if history else None,
            )

    if rich_provenance is not None:
        result["metadata"]["provenance"] = rich_provenance

    # Include all other meta fields
    PATH_FIELDS = {"original_file_path", "original_source", "background_file", "original_filename"}

    meta_items = _meta_items(dataset_meta)
    if meta_items:
        for key, value in meta_items:
            if key in ("processing_history", "samples", "provenance", "raw_file_metadata"):
                continue  # Already handled or internal
            if isinstance(key, str) and key.startswith("_"):
                continue  # Internal/debug-only fields
            if sanitize_paths and key in PATH_FIELDS and isinstance(value, str):
                value = os.path.basename(value)
            result["metadata"][key] = _json_safe(value)

    # Title
    dataset_title = _safe_str_attr(dataset, "title", "")
    result["title"] = dataset_title if dataset_title else (
        "Spectra" if is_spectra else "Data"
    )

    # Ensure all metadata values are JSON-serializable
    # SpectroChemPy may include datetime, numpy types, or other non-serializable objects
    result["metadata"] = _json_safe(result["metadata"])

    return result
