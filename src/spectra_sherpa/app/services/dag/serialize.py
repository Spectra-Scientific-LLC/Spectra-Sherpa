"""
Single source of truth for dataset -> API JSON serialization.

Called ONLY at the API boundary (in routes/workflows.py).

Usage:
    from spectra_sherpa.app.services.dag.serialize import serialize_for_api

    # In API route:
    result = serialize_for_api(dataset, sanitize_paths=True)
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Any, Dict

import numpy as np

from spectra_sherpa.app.lib.domain_flags import infer_is_spectra
from spectra_sherpa.app.lib.scp_compat import HAS_SCP, NDDataset
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

HAS_NDDATASET = HAS_SCP

from .meta_helpers import (
    detect_data_quantity,
    detect_spectral_technique,
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
    if isinstance(obj, (frozenset, set)):
        return sorted(_json_safe(v) for v in obj)
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


def _serialize_sherpa_dataset(
    dataset: SherpaDataset,
    sanitize_paths: bool = False,
    owner_user_id: int | None = None,
) -> Dict[str, Any]:
    """Serialize SherpaDataset to API-compatible JSON format."""
    from spectra_sherpa.app.services.dataset_registry import dataset_registry

    dataset_registry.register(dataset, owner_user_id=owner_user_id)
    result = dataset.to_dict()
    result["manifest"] = dataset.manifest.model_dump(mode="json")

    # Remap axis keys for frontend compatibility
    # SherpaDataset.to_dict() uses spectral_axis/sample_axis but the
    # frontend expects x_axis/y_axis (legacy NDDataset convention).
    if "feature_axis" in result:
        result["x_axis"] = result.pop("feature_axis")
    if "sample_axis" in result:
        result["y_axis"] = result.pop("sample_axis")

    # Enrich with spectral detection
    try:
        technique = detect_spectral_technique(dataset)
        data_quantity = detect_data_quantity(dataset)
    except Exception:
        technique = None
        data_quantity = None
    feature_axis = dataset.get_feature_axis()
    is_spectra = infer_is_spectra(
        dataset.meta.get("is_spectra") if isinstance(dataset.meta, dict) else None,
        technique=technique or dataset.domain.technique,
        x_title=feature_axis.title if feature_axis is not None else None,
        x_units=feature_axis.units if feature_axis is not None else None,
    )

    metadata = result.setdefault("metadata", {})
    metadata["data_type"] = "spectra" if is_spectra else "generic"
    metadata["is_spectra"] = is_spectra
    metadata["is_time_series"] = dataset.is_time_series
    metadata["spectral_technique"] = technique
    metadata["data_quantity"] = data_quantity

    # Convenience copies of axis info into metadata (frontend compat)
    if result.get("x_axis"):
        x_ax = result["x_axis"]
        x_units = x_ax.get("units") or ""
        if x_units == "dimensionless":
            x_ax["units"] = ""
            x_units = ""
        metadata["wavenumbers"] = x_ax.get("data", [])
        metadata["x_title"] = x_ax.get("title") or "Feature"
        metadata["x_units"] = x_units
        if x_ax.get("labels"):
            metadata["feature_names"] = x_ax["labels"]

    if result.get("y_axis"):
        y_ax = result["y_axis"]
        y_units = y_ax.get("units") or ""
        if y_units == "dimensionless":
            y_ax["units"] = ""
            y_units = ""
        metadata["y_title"] = y_ax.get("title") or "Sample"
        metadata["y_units"] = y_units
        if y_ax.get("labels"):
            formatted = [_format_sample_label(v) for v in y_ax["labels"]]
            metadata["sample_labels"] = formatted
            metadata["labels"] = formatted

    # Data units — always emit value_units so consumers don't need per-node fallbacks
    if dataset.units and str(dataset.units) != "dimensionless":
        metadata["value_units"] = str(dataset.units)
    semantic_units = dataset.get_extra("scp.value_units_label")
    if semantic_units:
        metadata["value_units_label"] = str(semantic_units)
        metadata.setdefault("value_units", str(semantic_units))
    # Final fallback — only if nothing above set value_units
    metadata.setdefault("value_units", "Response")

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

    # Merge extra metadata into metadata (strips scp. prefix).
    # Nodes store scientific metadata via NDDataset .meta which from_nddataset()
    # moves to SherpaDataset._extra with "scp." prefix.  The frontend expects
    # these keys (e.g. explained_variance_ratio, isPCA, quality_summary)
    # in .metadata.
    if result.get("extra"):
        for k, v in result["extra"].items():
            clean_key = k[4:] if k.startswith("scp.") else k
            if clean_key not in metadata:
                metadata[clean_key] = v

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

    return result


def serialize_for_api(
    dataset,
    sanitize_paths: bool = False,
    owner_user_id: int | None = None,
) -> Dict[str, Any]:
    """
    Serialize dataset to API-compatible JSON format.

    This is the SINGLE SOURCE OF TRUTH for serialization.
    Called only at API boundary, not inside nodes.

    Args:
        dataset: SherpaDataset (primary) or NDDataset (legacy)
        sanitize_paths: If True, strip file paths to basenames

    Returns:
        Dict ready for JSON response
    """
    import logging

    _logger = logging.getLogger(__name__)

    # Guard: reject stray NDDataset — nodes must emit SherpaDataset
    if HAS_SCP and isinstance(dataset, NDDataset):
        raise TypeError(
            "NDDataset reached serialize_for_api — node must emit SherpaDataset. "
            "Use scp_roundtrip() or from_nddataset() in the node's execute() method."
        )

    # Primary path: SherpaDataset
    if isinstance(dataset, SherpaDataset):
        return _serialize_sherpa_dataset(dataset, sanitize_paths, owner_user_id=owner_user_id)

    # Non-dataset fallback (shouldn't happen in normal flow)
    return {
        "type": "NDDataset",
        "shape": [],
        "data": [],
        "metadata": {"error": f"Unexpected type: {type(dataset).__name__}"},
    }
