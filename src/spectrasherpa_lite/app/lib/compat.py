"""
Compatibility layer for migrating from SpectrumRecord to NDDataset.

This module provides bidirectional conversion between the legacy SpectrumRecord
dataclass and the new NDDataset-based data model.

DEPRECATION: This module is temporary. Once all consumers are migrated to
NDDataset, this module should be removed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import numpy as np

try:
    import spectrochempy as scp
    from spectrochempy import NDDataset

    HAS_SCP = True
except ImportError:
    HAS_SCP = False
    scp = None
    NDDataset = None

from .spectral.dataset import create_spectral_dataset, SpectralUnit


# ═══════════════════════════════════════════════════════════════════════════════
# LEGACY DATA CLASSES (for compatibility)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class SpectrumRecord:
    """
    Container describing a single spectrum.

    DEPRECATED: Use NDDataset with appropriate metadata instead.
    This class is preserved for backward compatibility with existing code.
    """

    label: str
    filepath: Path
    wavenumber: np.ndarray
    absorbance: np.ndarray
    source: str = "csv"  # "csv" or "json"
    model_type: Optional[str] = None  # "linear", "saturation", "hybrid", or None

    # Model parameters (for JSON signatures with calibrated models)
    model_at_wavenumber: Optional[np.ndarray] = None
    slope: Optional[np.ndarray] = None
    intercept: Optional[np.ndarray] = None
    s: Optional[np.ndarray] = None
    p: Optional[np.ndarray] = None
    c: Optional[np.ndarray] = None
    reference_concentration: Optional[float] = None

    # Metadata fields
    concentration_mode: Optional[str] = None
    x_label: Optional[str] = None
    x_unit: Optional[str] = None
    pathlength_m: Optional[float] = None


@dataclass
class PreprocessingSettings:
    """
    Configuration bundle for optional spectral preprocessing.

    DEPRECATED: Use PreprocessingSettings from app.lib.preprocessing instead.
    """

    align_wavenumbers: bool = False
    wavenumber_alignment_method: str = "none"
    wavenumber_alignment_tolerance: float = 1e-6
    wavenumber_merge_tolerance: float = 0.05
    filter_direction: str = "wavenumber"
    apply_cosmic_ray_removal: bool = False
    cosmic_ray_window: int = 11
    cosmic_ray_zscore: float = 6.0
    apply_savgol: bool = False
    savgol_window: int = 15
    savgol_polyorder: int = 3
    apply_range_limit: bool = False
    min_wavenumber: Optional[float] = 400
    max_wavenumber: Optional[float] = 4000
    apply_clip_floor: bool = False
    clip_floor: float = 0.0
    apply_scale: bool = False
    scale_max_to: float = 1.0


# ═══════════════════════════════════════════════════════════════════════════════
# CONVERSION UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════


def record_to_dataset(record: SpectrumRecord) -> "NDDataset":
    """
    Convert a SpectrumRecord to an NDDataset.

    Parameters
    ----------
    record : SpectrumRecord
        Legacy spectrum record

    Returns
    -------
    NDDataset
        SpectroChemPy dataset with equivalent data and metadata
    """
    if not HAS_SCP:
        raise ImportError("spectrochempy is required for NDDataset conversion")

    # Create base dataset
    dataset = create_spectral_dataset(
        data=record.absorbance,
        wavenumbers=record.wavenumber,
        units=SpectralUnit.ABSORBANCE,
        title=record.label,
    )

    # Add source metadata
    dataset.meta["source_file"] = str(record.filepath) if record.filepath else None
    dataset.meta["source_type"] = record.source

    # Add calibration metadata if present
    if record.model_type:
        calibration = {
            "model_type": record.model_type,
            "concentration_mode": record.concentration_mode,
        }

        if record.reference_concentration is not None:
            calibration["reference_concentration"] = record.reference_concentration

        # Add model parameters as lists (for JSON serialization compatibility)
        if record.slope is not None:
            calibration["slope"] = _array_to_list(record.slope)
        if record.intercept is not None:
            calibration["intercept"] = _array_to_list(record.intercept)
        if record.s is not None:
            calibration["s"] = _array_to_list(record.s)
        if record.p is not None:
            calibration["p"] = _array_to_list(record.p)
        if record.c is not None:
            calibration["c"] = _array_to_list(record.c)
        if record.model_at_wavenumber is not None:
            calibration["model_at_wavenumber"] = _array_to_list(record.model_at_wavenumber)

        dataset.meta["calibration"] = calibration

    # Add additional metadata
    if record.x_label:
        dataset.meta["x_label"] = record.x_label
    if record.x_unit:
        dataset.meta["x_unit"] = record.x_unit
    if record.pathlength_m is not None:
        dataset.meta["pathlength_m"] = record.pathlength_m

    return dataset


def dataset_to_record(dataset: "NDDataset") -> SpectrumRecord:
    """
    Convert an NDDataset to a SpectrumRecord.

    Parameters
    ----------
    dataset : NDDataset
        SpectroChemPy dataset

    Returns
    -------
    SpectrumRecord
        Legacy spectrum record with equivalent data
    """
    # Extract wavenumbers
    if hasattr(dataset, "x") and dataset.x is not None:
        wavenumber = np.asarray(dataset.x.data, dtype=float)
    else:
        wavenumber = np.arange(dataset.shape[-1], dtype=float)

    # Extract absorbance
    absorbance = np.asarray(dataset.data, dtype=float)
    if absorbance.ndim > 1:
        absorbance = absorbance.flatten()

    # Extract metadata
    meta = dataset.meta if hasattr(dataset, "meta") else {}
    calibration = meta.get("calibration", {})

    # Build filepath
    source_file = meta.get("source_file")
    filepath = Path(source_file) if source_file else Path(".")

    return SpectrumRecord(
        label=dataset.title if hasattr(dataset, "title") and dataset.title else "UNKNOWN",
        filepath=filepath,
        wavenumber=wavenumber,
        absorbance=absorbance,
        source=meta.get("source_type", "csv"),
        model_type=calibration.get("model_type"),
        model_at_wavenumber=_list_to_array(calibration.get("model_at_wavenumber")),
        slope=_list_to_array(calibration.get("slope")),
        intercept=_list_to_array(calibration.get("intercept")),
        s=_list_to_array(calibration.get("s")),
        p=_list_to_array(calibration.get("p")),
        c=_list_to_array(calibration.get("c")),
        reference_concentration=calibration.get("reference_concentration"),
        concentration_mode=calibration.get("concentration_mode"),
        x_label=meta.get("x_label"),
        x_unit=meta.get("x_unit"),
        pathlength_m=meta.get("pathlength_m"),
    )


def records_to_datasets(records: List[SpectrumRecord]) -> List["NDDataset"]:
    """Convert a list of SpectrumRecords to NDDatasets."""
    return [record_to_dataset(r) for r in records]


def datasets_to_records(datasets: List["NDDataset"]) -> List[SpectrumRecord]:
    """Convert a list of NDDatasets to SpectrumRecords."""
    return [dataset_to_record(ds) for ds in datasets]


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════


def _array_to_list(arr: Optional[np.ndarray]) -> Optional[List]:
    """Convert numpy array to list, handling None and object arrays."""
    if arr is None:
        return None
    if arr.dtype == object:
        return [x if x is not None else None for x in arr.tolist()]
    return arr.tolist()


def _list_to_array(lst: Optional[List]) -> Optional[np.ndarray]:
    """Convert list to numpy array, handling None values."""
    if lst is None:
        return None
    # Check if list contains None values (mixed type)
    if any(x is None for x in lst):
        return np.array(lst, dtype=object)
    return np.array(lst, dtype=float)


def serializable_array(arr: Optional[np.ndarray]) -> Optional[List]:
    """
    Convert numpy array to JSON-serializable list.

    Handles object arrays with None values.
    """
    return _array_to_list(arr)


def dataset_to_payload(dataset: "NDDataset") -> Dict[str, Any]:
    """
    Convert NDDataset directly to a JSON-serializable payload dict.

    This function bypasses SpectrumRecord to preserve all metadata.

    Parameters
    ----------
    dataset : NDDataset
        SpectroChemPy dataset

    Returns
    -------
    dict
        JSON-serializable payload with all metadata preserved
    """
    # Extract wavenumbers
    if hasattr(dataset, "x") and dataset.x is not None:
        wavenumber = np.asarray(dataset.x.data, dtype=float)
    else:
        wavenumber = np.arange(dataset.shape[-1], dtype=float)

    # Extract absorbance
    absorbance = np.asarray(dataset.data, dtype=float)
    if absorbance.ndim > 1:
        absorbance = absorbance.flatten()

    # Extract metadata
    meta = dict(dataset.meta) if hasattr(dataset, "meta") and dataset.meta else {}
    calibration = meta.get("calibration", {})

    # Build payload preserving all fields
    payload: Dict[str, Any] = {
        "label": dataset.title if hasattr(dataset, "title") and dataset.title else "UNKNOWN",
        "file_path": meta.get("source_file"),
        "wavenumber": wavenumber.tolist(),
        "absorbance": absorbance.tolist(),
        "source": meta.get("source_type", "csv"),
        "model_type": calibration.get("model_type"),
        "model_at_wavenumber": calibration.get("model_at_wavenumber"),
        "slope": calibration.get("slope"),
        "intercept": calibration.get("intercept"),
        "s": calibration.get("s"),
        "p": calibration.get("p"),
        "c": calibration.get("c"),
        "reference_concentration": calibration.get("reference_concentration"),
        "concentration_mode": calibration.get("concentration_mode"),
        "x_label": meta.get("x_label"),
        "x_unit": meta.get("x_unit"),
        "pathlength_m": meta.get("pathlength_m"),
    }

    # Include chemometrics metadata if present (preserves rich metadata)
    if "chemometrics" in meta:
        payload["chemometrics"] = meta["chemometrics"]

    # Include provenance if present
    if "provenance" in meta:
        payload["provenance"] = meta["provenance"]

    # Include spectral resolution info if present
    if "spectral_resolution" in meta:
        payload["spectral_resolution"] = meta["spectral_resolution"]

    return payload


__all__ = [
    # Legacy classes
    "SpectrumRecord",
    "PreprocessingSettings",
    # Conversion utilities
    "record_to_dataset",
    "dataset_to_record",
    "records_to_datasets",
    "datasets_to_records",
    # Helpers
    "serializable_array",
    "dataset_to_payload",
]
