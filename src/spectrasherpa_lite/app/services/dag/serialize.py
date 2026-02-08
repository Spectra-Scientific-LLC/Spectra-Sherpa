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
from datetime import datetime, date
from typing import Any, Dict, Optional
import numpy as np

try:
    from spectrochempy import NDDataset
    HAS_NDDATASET = True
except ImportError:
    NDDataset = None
    HAS_NDDATASET = False

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
    raw_data = np.asarray(dataset.data, dtype=float)
    # Replace NaN and Inf with None (JSON-safe)
    data_list = np.where(np.isfinite(raw_data), raw_data, None).tolist()

    result = {
        "type": "NDDataset",
        "shape": list(dataset.shape),
        "data": data_list,
        "n_samples": dataset.shape[0] if dataset.ndim == 2 else 1,
        "n_features": dataset.shape[-1],
        "metadata": {},
    }

    # X-axis
    # NOTE: SpectroChemPy's __getattr__ raises KeyError (not AttributeError)
    # when a coordinate name like 'x' is not found, so hasattr() alone is insufficient.
    try:
        x_coord = dataset.x
    except (KeyError, AttributeError):
        x_coord = None

    if x_coord is not None:
        try:
            x_data = np.array(x_coord.data, dtype=float).tolist()
        except (ValueError, TypeError):
            x_data = [str(v) for v in x_coord.data]
        x_title = str(x_coord.title) if hasattr(x_coord, 'title') and x_coord.title else "Feature"
        x_units = str(x_coord.units) if hasattr(x_coord, 'units') and str(x_coord.units) != "dimensionless" else ""

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
    except (KeyError, AttributeError):
        technique = None
        data_quantity = None
    is_spectra = technique is not None

    result["metadata"]["data_type"] = "spectra" if is_spectra else "generic"
    result["metadata"]["is_spectra"] = is_spectra
    result["metadata"]["spectral_technique"] = technique
    result["metadata"]["data_quantity"] = data_quantity

    # Y-axis (sample labels)
    try:
        y_coord = dataset.y
    except (KeyError, AttributeError):
        y_coord = None

    if y_coord is not None:
        y_title = str(y_coord.title) if hasattr(y_coord, 'title') else "Sample"
        try:
            y_data = np.array(y_coord.data, dtype=float).tolist()
        except (ValueError, TypeError):
            # String or non-numeric y-axis data — convert to string list
            y_data = [str(v) for v in y_coord.data]

        # Extract labels from y-axis (file names, sample names, etc.)
        y_labels = None
        try:
            if hasattr(y_coord, 'labels') and y_coord.labels is not None:
                labels_raw = y_coord.labels
                # Handle both list and ndarray of labels
                if hasattr(labels_raw, 'tolist'):
                    labels_list = labels_raw.tolist()
                elif isinstance(labels_raw, (list, tuple)):
                    labels_list = list(labels_raw)
                else:
                    labels_list = None

                if labels_list is not None:
                    # Convert to JSON-safe strings. Labels may contain
                    # datetime objects, numpy types, or multi-element arrays.
                    y_labels = [str(v) for v in labels_list]
        except (KeyError, AttributeError, TypeError):
            y_labels = None

        result["y_axis"] = {
            "title": y_title,
            "units": "",
            "data": y_data,
            "labels": y_labels,  # Include labels in y_axis
        }

        # Also add to metadata for frontend compatibility (DataTableModal expects these)
        if y_labels:
            result["metadata"]["sample_labels"] = y_labels
            result["metadata"]["labels"] = y_labels  # Alias for backwards compat

    # Data units
    if hasattr(dataset, 'units') and dataset.units:
        result["metadata"]["value_units"] = str(dataset.units)

    # Processing history from meta
    history = get_processing_history(dataset)
    if history:
        result["metadata"]["processing_history"] = history

    # Build provenance: merge rich provenance from meta with processing history summary
    # Start with rich provenance from dataset.meta (original_source_type, operator, lab_name, etc.)
    rich_provenance: dict | Any | None = None
    if hasattr(dataset, 'meta') and dataset.meta:
        meta_provenance = dataset.meta.get("provenance")
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

    if hasattr(dataset, 'meta') and dataset.meta:
        for key, value in dataset.meta.items():
            if key in ("processing_history", "samples", "provenance", "raw_file_metadata"):
                continue  # Already handled or internal
            if key.startswith("_"):
                continue  # Internal/debug-only fields
            if sanitize_paths and key in PATH_FIELDS and isinstance(value, str):
                value = os.path.basename(value)
            result["metadata"][key] = _json_safe(value)

    # Title
    result["title"] = str(dataset.title) if hasattr(dataset, 'title') and dataset.title else (
        "Spectra" if is_spectra else "Data"
    )

    # Ensure all metadata values are JSON-serializable
    # SpectroChemPy may include datetime, numpy types, or other non-serializable objects
    result["metadata"] = _json_safe(result["metadata"])

    return result
