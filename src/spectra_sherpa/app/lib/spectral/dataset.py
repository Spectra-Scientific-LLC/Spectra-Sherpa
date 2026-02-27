"""
Unified spectral dataset with SpectroChemPy integration.

This module provides the core data types and factory functions for
creating properly configured NDDataset objects with spectral metadata.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

import numpy as np

from spectra_sherpa.app.lib.scp_compat import Coord, NDDataset, require_scp, scp


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
        Unit string from NDDataset.units

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
        "t": SpectralUnit.TRANSMITTANCE,
        "%r": SpectralUnit.REFLECTANCE,
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
) -> "NDDataset":
    """
    Factory function to create a properly configured NDDataset.

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
    NDDataset
        Fully configured dataset with coordinates and units
    """
    require_scp("Spectral dataset creation")

    # Ensure 2D
    if data.ndim == 1:
        data = data.reshape(1, -1)

    dataset = scp.NDDataset(data, title=title)

    # Set spectral axis (x)
    dataset.x = Coord(wavenumbers, title="Wavenumber", units=x_units.value)

    # Set sample axis (y) if labels provided
    if sample_labels is not None:
        dataset.y = Coord(sample_labels, title="Samples")
    elif data.shape[0] > 1:
        # Auto-generate sample indices
        dataset.y = Coord(np.arange(data.shape[0]), title="Sample Index")

    # Set intensity units
    dataset.units = units.value

    # Add metadata
    if meta:
        dataset.meta.update(meta)

    return dataset


def add_provenance(
    dataset: "NDDataset",
    operation: str,
    parameters: dict,
) -> None:
    """
    Add provenance metadata to a dataset.

    Parameters
    ----------
    dataset : NDDataset
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
