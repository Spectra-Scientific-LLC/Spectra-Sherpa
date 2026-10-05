"""Native spectral dataset construction and unit helpers."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

import numpy as np

from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset


class SpectralUnit(Enum):
    """Valid spectral intensity units."""

    ABSORBANCE = "absorbance"
    TRANSMITTANCE = "transmittance"
    REFLECTANCE = "reflectance"
    KUBELKA_MUNK = "kubelka_munk"
    COUNTS = "counts"
    INTENSITY = "intensity"
    DIMENSIONLESS = "dimensionless"


class SpectralAxisUnit(Enum):
    """Valid spectral axis units."""

    WAVENUMBER = "cm^-1"
    WAVELENGTH_NM = "nm"
    WAVELENGTH_UM = "µm"
    RAMAN_SHIFT = "cm^-1"  # Same unit as wavenumber, different meaning


# Incompatible unit pairs that cannot be combined mathematically
_INCOMPATIBLE_PAIRS = frozenset(
    {
        (SpectralUnit.ABSORBANCE, SpectralUnit.TRANSMITTANCE),
        (SpectralUnit.ABSORBANCE, SpectralUnit.REFLECTANCE),
        (SpectralUnit.TRANSMITTANCE, SpectralUnit.REFLECTANCE),
    }
)


def parse_spectral_unit(unit_str: Optional[str]) -> SpectralUnit:
    """
    Parse a unit string to SpectralUnit enum.

    Parameters
    ----------
    unit_str : str or None
        Unit string from SherpaDataset.units

    Returns
    -------
    SpectralUnit
        Parsed unit, defaults to DIMENSIONLESS if unknown
    """
    if unit_str is None:
        return SpectralUnit.DIMENSIONLESS

    unit_lower = str(unit_str).lower().strip()

    # Direct matches
    for unit in SpectralUnit:
        if unit.value == unit_lower:
            return unit

    # Common aliases
    aliases = {
        "a.u.": SpectralUnit.ABSORBANCE,
        "au": SpectralUnit.ABSORBANCE,
        "abs": SpectralUnit.ABSORBANCE,
        "%t": SpectralUnit.TRANSMITTANCE,
        "%transmittance": SpectralUnit.TRANSMITTANCE,
        "percent transmittance": SpectralUnit.TRANSMITTANCE,
        "t": SpectralUnit.TRANSMITTANCE,
        "%r": SpectralUnit.REFLECTANCE,
        "%reflectance": SpectralUnit.REFLECTANCE,
        "percent reflectance": SpectralUnit.REFLECTANCE,
        "r": SpectralUnit.REFLECTANCE,
        "km": SpectralUnit.KUBELKA_MUNK,
        "k-m": SpectralUnit.KUBELKA_MUNK,
        "cts": SpectralUnit.COUNTS,
        "arb": SpectralUnit.INTENSITY,
        "arb.": SpectralUnit.INTENSITY,
    }

    return aliases.get(unit_lower, SpectralUnit.DIMENSIONLESS)


def validate_unit_compatibility(unit1: SpectralUnit, unit2: SpectralUnit) -> bool:
    """
    Check if two spectral units can be combined mathematically.

    Parameters
    ----------
    unit1, unit2 : SpectralUnit
        Units to check

    Returns
    -------
    bool
        True if units are compatible, False otherwise
    """
    if unit1 == unit2:
        return True

    # Normalize order for comparison
    pair = (unit1, unit2) if unit1.value < unit2.value else (unit2, unit1)
    return pair not in _INCOMPATIBLE_PAIRS


def create_spectral_dataset(
    data: np.ndarray,
    wavenumbers: np.ndarray,
    sample_labels: Optional[List[str]] = None,
    units: SpectralUnit = SpectralUnit.ABSORBANCE,
    x_units: SpectralAxisUnit = SpectralAxisUnit.WAVENUMBER,
    title: str = "Spectral Data",
    meta: Optional[dict] = None,
) -> SherpaDataset:
    """
    Create a native dataset with explicit spectral and sample axes.

    Parameters
    ----------
    data : np.ndarray
        2D array of shape (n_samples, n_wavenumbers) or
        1D array of shape (n_wavenumbers,)
    wavenumbers : np.ndarray
        1D array of spectral axis values
    sample_labels : list[str], optional
        Labels for each sample (row)
    units : SpectralUnit
        Intensity unit (absorbance, transmittance, etc.)
    x_units : SpectralAxisUnit
        Spectral axis unit (cm^-1, nm, etc.)
    title : str
        Dataset title
    meta : dict, optional
        Additional metadata

    Returns
    -------
    SherpaDataset
        Fully configured native dataset.
    """
    matrix = np.asarray(data, dtype=np.float64)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2:
        raise ValueError(f"Spectral data must be 1-D or 2-D, got shape {matrix.shape}")
    axis = np.asarray(wavenumbers, dtype=np.float64).reshape(-1)
    if axis.size != matrix.shape[1]:
        raise ValueError(f"Spectral axis length ({axis.size}) != feature count ({matrix.shape[1]})")
    labels = [str(label) for label in sample_labels] if sample_labels is not None else None
    if labels is not None and len(labels) != matrix.shape[0]:
        raise ValueError(f"Sample label count ({len(labels)}) != sample count ({matrix.shape[0]})")
    sample_axis = SampleAxis(
        values=np.arange(matrix.shape[0], dtype=np.float64),
        labels=labels,
        title="Samples",
    )
    dataset = SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units=x_units.value),
        sample_axis=sample_axis,
        title=title,
        units=units.value,
        data_role="X_spectra",
    )
    if meta:
        dataset.meta.update(meta)
    return dataset


def add_provenance(
    dataset: SherpaDataset,
    operation: str,
    parameters: dict,
) -> None:
    """
    Add provenance metadata to a dataset.

    Parameters
    ----------
    dataset : SherpaDataset
        Dataset to modify in-place
    operation : str
        Name of the operation performed
    parameters : dict
        Parameters used in the operation
    """
    if not hasattr(dataset, "meta"):
        return

    if "provenance" not in dataset.meta:
        dataset.meta["provenance"] = []

    dataset.meta["provenance"].append(
        {
            "op_id": operation,
            "parameters": parameters,
        }
    )
