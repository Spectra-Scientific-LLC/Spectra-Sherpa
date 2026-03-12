"""Shared utility functions used across data source nodes.

These helpers handle index-column detection, SCP file loading,
metadata extraction, and axis slicing.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

from spectra_sherpa.app.lib.scp_compat import (
    HAS_SCP,
    NDDataset,
    require_scp,
    scp,
)
from spectra_sherpa.app.lib.sherpa_dataset import (
    AxisInfo,
    SampleAxis,
    SherpaDataset,
    SpectralAxis,
)
from spectra_sherpa.app.services.dag.meta_helpers import safe_get_coord

from ...io_contracts import build_dataset_like

logger = logging.getLogger(__name__)


def is_index_column(data_column: np.ndarray) -> bool:
    """
    Detect if a column is a monotonic integer sequence (likely an index).

    Checks if the column:
    - Contains only integers (or floats that are whole numbers)
    - Is monotonically increasing
    - Has consistent step size of 1

    Args:
        data_column: 1D numpy array representing a column

    Returns:
        True if column appears to be an index, False otherwise
    """
    try:
        # Convert to numeric if not already
        col = np.array(data_column).flatten()

        # Check if all values are integers or whole numbers
        if not np.allclose(col, np.round(col)):
            return False

        col_int = np.round(col).astype(int)

        # Check if monotonically increasing
        if not np.all(np.diff(col_int) > 0):
            return False

        # Check if step size is consistently 1
        steps = np.diff(col_int)
        if not np.all(steps == 1):
            return False

        return True
    except (ValueError, TypeError):
        return False


def remove_index_columns(dataset: NDDataset | SherpaDataset) -> NDDataset | SherpaDataset:
    """
    Remove index columns from dataset if detected.

    Detects and removes columns that appear to be row indices
    (monotonic integer sequences with step=1).

    Handles both NDDataset (from raw SCP loading) and SherpaDataset,
    preserving the input type in the return value.

    Args:
        dataset: Input dataset (NDDataset or SherpaDataset)

    Returns:
        Dataset of the same type with index columns removed (if any were found)
    """
    if not hasattr(dataset, "data") or dataset.ndim != 2:
        return dataset

    data = np.array(dataset.data)
    n_rows, n_cols = data.shape

    # Check first column for index pattern
    if n_cols > 1:  # Only remove if there are other columns
        first_col = data[:, 0]
        if is_index_column(first_col):
            logger.debug(
                f"[DATA] Detected index column in first position "
                f"(values: {first_col[0]:.0f}-{first_col[-1]:.0f}), removing from data"
            )
            # Remove first column
            cleaned_data = data[:, 1:]

            # Create new dataset without the index column
            if isinstance(dataset, SherpaDataset):
                cleaned_dataset = build_dataset_like(cleaned_data, dataset)
                # Trim feature axis if it matched original column count
                if (
                    cleaned_dataset.feature_axis
                    and cleaned_dataset.feature_axis.values is not None
                    and len(cleaned_dataset.feature_axis.values) == n_cols
                ):
                    cleaned_dataset.feature_axis = SpectralAxis(
                        values=cleaned_dataset.feature_axis.values[1:],
                        labels=(
                            cleaned_dataset.feature_axis.labels[1:]
                            if cleaned_dataset.feature_axis.labels
                            and len(cleaned_dataset.feature_axis.labels) == n_cols
                            else cleaned_dataset.feature_axis.labels
                        ),
                        units=cleaned_dataset.feature_axis.units,
                        title=cleaned_dataset.feature_axis.title,
                    )
            elif HAS_SCP and isinstance(dataset, NDDataset):
                cleaned_dataset = scp.NDDataset(cleaned_data)

                # Preserve coordinate system if present
                ric_x_coord = safe_get_coord(dataset, "x")
                if ric_x_coord is not None and len(ric_x_coord) == n_cols:
                    cleaned_dataset.x = ric_x_coord[1:].copy() if hasattr(ric_x_coord, "__getitem__") else ric_x_coord
                elif ric_x_coord is not None:
                    cleaned_dataset.x = ric_x_coord.copy()

                ric_y_coord = safe_get_coord(dataset, "y")
                if ric_y_coord is not None:
                    cleaned_dataset.y = ric_y_coord.copy()

                # Preserve metadata
                if hasattr(dataset, "meta") and dataset.meta:
                    cleaned_dataset.meta = dataset.meta.copy()

                if hasattr(dataset, "title"):
                    cleaned_dataset.title = dataset.title

                if hasattr(dataset, "units"):
                    cleaned_dataset.units = dataset.units
            else:
                # Plain ndarray fallback
                cleaned_dataset = build_dataset_like(cleaned_data, dataset, copy_history=False)

            return cleaned_dataset

    return dataset


def slice_axis_for_indices(coord: Any, indices: np.ndarray) -> Any | None:
    """
    Slice sample-axis metadata for integer index selection.

    Supports both SherpaDataset AxisInfo and SCP Coord-like objects.
    """
    if coord is None:
        return None

    if isinstance(coord, AxisInfo):
        values = None
        if coord.values is not None:
            values = np.asarray(coord.values)[indices]

        labels = None
        if coord.labels is not None:
            labels = np.asarray(coord.labels, dtype=object)[indices].astype(str).tolist()

        # SampleAxis extends AxisInfo with per-sample fields; preserve them.
        if isinstance(coord, SampleAxis):
            classes = None
            if coord.classes is not None:
                classes = np.asarray(coord.classes)[indices]
            include_mask = None
            if coord.include_mask is not None:
                include_mask = np.asarray(coord.include_mask)[indices]
            exclusion_reasons = None
            if coord.exclusion_reasons is not None:
                exclusion_reasons = [coord.exclusion_reasons[i] for i in indices]
            sample_table = None
            if coord.sample_table is not None:
                sample_table = {k: [v[i] for i in indices] for k, v in coord.sample_table.items()}
            return SampleAxis(
                values=values,
                labels=labels,
                units=coord.units,
                title=coord.title,
                classes=classes,
                include_mask=include_mask,
                exclusion_reasons=exclusion_reasons,
                sample_table=sample_table,
            )

        return AxisInfo(
            values=values,
            labels=labels,
            units=coord.units,
            title=coord.title,
        )

    try:
        sliced = coord[indices]
        return sliced.copy() if hasattr(sliced, "copy") else sliced
    except Exception:
        return coord.copy() if hasattr(coord, "copy") else coord


def extract_dataset_from_result(result: Any, file_path: str) -> NDDataset:
    """
    Extract a single NDDataset from a SpectroChemPy file read result.

    Handles ScpObjectList which is returned by read_matlab() when .MAT files
    contain multiple variables (common for MCR-ALS datasets like als2004dataset.MAT).

    Strategy: Select the 2D dataset with the largest total size (rows * cols),
    which is typically the main spectral matrix D = C * S^T.

    This is an SCP-internal utility called before the NDDataset-to-SherpaDataset
    conversion step.  Callers are responsible for calling ``from_nddataset()``
    on the returned value when a SherpaDataset is needed downstream.

    Args:
        result: The result from SpectroChemPy read operation
        file_path: Path to the file being read (for error messages)

    Returns:
        A single NDDataset extracted from the result
    """
    require_scp("File loading")

    # If already an NDDataset, return as-is
    if isinstance(result, NDDataset):
        return result

    # Handle ScpObjectList (list of datasets)
    if hasattr(result, "__iter__") and not isinstance(result, (str, bytes)):
        datasets = list(result)

        if len(datasets) == 0:
            raise ValueError(f"No datasets found in {file_path}")

        if len(datasets) == 1:
            return datasets[0]

        # Multiple datasets - find the best candidate
        # Prefer 2D datasets (spectral matrices) over 1D
        candidates_2d = [d for d in datasets if hasattr(d, "shape") and len(d.shape) == 2]

        if candidates_2d:
            # Select largest 2D dataset by total elements
            best = max(candidates_2d, key=lambda d: np.prod(d.shape))
            logger.debug(f"MAT file contains {len(datasets)} items, selected shape {best.shape}")
            return best
        else:
            # No 2D candidates - select largest overall (encapsulate as NDDataset)
            best = max(datasets, key=lambda d: np.prod(getattr(d, "shape", (0,))))
            logger.debug(
                f"MAT file contains {len(datasets)} items with no 2D arrays, "
                f"selected largest dataset with shape {getattr(best, 'shape', 'unknown')}"
            )
            return best

    # Ensure result is encapsulated as NDDataset for consistency
    if not isinstance(result, NDDataset):
        # Convert array-like objects to NDDataset
        try:
            if isinstance(result, np.ndarray):
                result = scp.NDDataset(result)
            elif hasattr(result, "__array__"):
                result = scp.NDDataset(np.array(result))
            else:
                # Last resort - try direct conversion
                result = scp.NDDataset(result)
        except Exception as e:
            raise TypeError(
                f"Cannot convert to NDDataset: {type(result).__name__}\n" f"File: {file_path}\n" f"Error: {str(e)}"
            ) from e
    return result


_SCP_KNOWN_DEFAULTS: dict[str, tuple[str, str]] = {
    # category: (relative_path, explicit reader name)
    "irdata": ("irdata/nh4y-activation.spg", "read_omnic"),
}


def _normalize_scp_read_output(result: Any) -> NDDataset | None:
    """Normalize SpectroChemPy reader outputs across versions.

    SCP-internal: recursively unwraps dicts, lists, and iterables returned
    by various SCP reader functions to find the first NDDataset.

    Returns:
        The first NDDataset found in the result, or None.
    """
    if result is None:
        return None
    if isinstance(result, NDDataset):
        return result

    if isinstance(result, dict):
        for value in result.values():
            candidate = _normalize_scp_read_output(value)
            if candidate is not None:
                return candidate
        return None

    if isinstance(result, (list, tuple)):
        for item in result:
            candidate = _normalize_scp_read_output(item)
            if candidate is not None:
                return candidate
        return None

    # Some SCP objects are iterable but not list/tuple.
    if hasattr(result, "__iter__") and not isinstance(result, (str, bytes)):
        try:
            for item in result:
                candidate = _normalize_scp_read_output(item)
                if candidate is not None:
                    return candidate
        except Exception:
            return None

    return None


def _try_load_scp_file(path: Path) -> NDDataset | None:
    """Load one SCP file with extension-aware reader selection.

    SCP-internal: returns a raw NDDataset before SherpaDataset conversion.
    For CSV files, index columns are stripped via ``remove_index_columns()``.

    Returns:
        An NDDataset on success, or None if the file cannot be read.
    """
    from spectra_sherpa.app.core.config import get_reader_for_extension

    try:
        reader_name = get_reader_for_extension(path.suffix)
    except ValueError:
        return None

    dataset = None
    reader_fn = getattr(scp, reader_name, None)
    if callable(reader_fn):
        try:
            dataset = _normalize_scp_read_output(reader_fn(str(path)))
        except Exception:
            dataset = None

    # If the mapped reader is missing or couldn't parse, try generic read().
    if dataset is None and reader_name != "read":
        generic_reader = getattr(scp, "read", None)
        if callable(generic_reader):
            try:
                dataset = _normalize_scp_read_output(generic_reader(str(path)))
            except Exception:
                dataset = None

    if dataset is None:
        return None

    if path.suffix.lower() == ".csv":
        return remove_index_columns(dataset)

    return dataset


def _try_load_first_file(folder: Path) -> NDDataset | None:
    """Find the first readable file in a dataset folder (recursive).

    SCP-internal: delegates to ``_try_load_scp_file()`` and returns a raw
    NDDataset before SherpaDataset conversion.

    Returns:
        An NDDataset from the first successfully loaded file, or None.
    """
    for file_path in sorted(folder.rglob("*")):
        if not file_path.is_file() or file_path.name.startswith((".", "_")):
            continue
        dataset = _try_load_scp_file(file_path)
        if dataset is not None:
            return dataset
    return None


def extract_instrument_metadata(dataset: NDDataset, file_path: str) -> dict:
    """
    Extract and normalize instrument metadata from a loaded NDDataset.

    This is a wrapper around the metadata extraction service that provides
    format-specific extractors (OPUS, SPA, JCAMP, SPC) and a normalizer
    that maps raw keys to our SpectraMeta schema.

    The new architecture supports:
    - Bruker OPUS files: Comprehensive instrument/acquisition params
    - Thermo SPA/SPG files: Full metadata extraction
    - JCAMP-DX files: Standard header fields + vendor extensions
    - Galactic SPC files: Instrument metadata
    - Generic fallback for CSV, MAT, etc.

    Args:
        dataset: Loaded NDDataset with potential metadata
        file_path: Original file path (for format detection)

    Returns:
        Dict with normalized metadata fields ready for SpectraMeta:
        {
            "instrument_metadata": {...},   # -> InstrumentInfo
            "acquisition_params": {...},    # -> AcquisitionParams
            "experimental_conditions": {...}, # -> ExperimentalConditions
            "sample_info": {...},           # Sample-related fields
            "provenance": {...},            # -> DataProvenance + AuditInfo
            "raw_file_metadata": {...},     # Preserved but excluded from API
        }
    """
    try:
        # Use the new metadata extraction service
        from spectra_sherpa.app.services.metadata import extract_metadata

        return extract_metadata(dataset, file_path)
    except ImportError:
        # Fallback if metadata service not available (shouldn't happen)
        logger.warning("Metadata service not available, using minimal extraction")
        return _minimal_metadata_extraction(dataset, file_path)


def _minimal_metadata_extraction(dataset: NDDataset, file_path: str) -> dict:
    """
    Minimal fallback metadata extraction if the service is unavailable.

    This preserves basic functionality if there's an import error.
    SECURITY: Only stores filename, not full path, to prevent server path leakage.
    """
    metadata = {
        "provenance": {
            "original_file_format": os.path.splitext(file_path)[1].lower().lstrip("."),
            "original_filename": os.path.basename(file_path),
        }
    }

    # Extract x-axis info if available
    mme_x_coord = safe_get_coord(dataset, "x")
    if mme_x_coord is not None:
        try:
            x_data = np.array(mme_x_coord.data) if hasattr(mme_x_coord, "data") else np.array(mme_x_coord)
            if len(x_data) > 0:
                metadata["acquisition_params"] = {
                    "wavenumber_min": str(float(np.min(x_data))),
                    "wavenumber_max": str(float(np.max(x_data))),
                    "n_points": str(len(x_data)),
                }
        except Exception:
            pass

    return metadata
