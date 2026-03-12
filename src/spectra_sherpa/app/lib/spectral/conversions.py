"""
Unit conversion utilities with auto-convert to absorbance.

Provides functions to convert between spectral units (transmittance,
reflectance, etc.) with automatic handling of edge cases.

IMPORTANT: Absorbance = log₁₀(I₀/I) requires a reference spectrum (I₀).
If transmittance data hasn't been ratio'd to a reference, conversion
to absorbance will produce incorrect values.
"""

from __future__ import annotations

import logging
import warnings
from typing import TYPE_CHECKING

import numpy as np

from .dataset import SpectralUnit, add_provenance, parse_spectral_unit

if TYPE_CHECKING:
    from spectra_sherpa.app.lib.scp_compat import NDDataset

logger = logging.getLogger(__name__)


class ReferenceNotAppliedWarning(UserWarning):
    """Warning raised when converting data that may not have reference applied."""

    pass


def check_reference_applied(dataset: "NDDataset", operation: str) -> bool:
    """
    Check if reference spectrum has been applied to dataset.

    Looks for reference info in dataset.meta. Warns if reference
    status is unknown or not applied.

    Parameters
    ----------
    dataset : NDDataset
        Dataset to check
    operation : str
        Name of the operation (for warning messages)

    Returns
    -------
    bool
        True if reference is confirmed applied, False otherwise
    """
    meta = dataset.meta if hasattr(dataset, "meta") and dataset.meta else {}

    # Check for structured chemometrics metadata
    if "chemometrics" in meta:
        chem = meta["chemometrics"]
        if isinstance(chem, dict) and "reference" in chem:
            ref = chem["reference"]
            if isinstance(ref, dict):
                return bool(ref.get("applied", False))

    # Check for simple reference_applied flag
    if "reference_applied" in meta:
        return bool(meta["reference_applied"])

    # Check for source type hints
    source_type = meta.get("source_type", "").lower()
    if source_type in ("hitran", "nist", "pnnl"):
        # Database spectra are typically already in absorbance
        return True

    # Unknown - warn but don't block
    return False


def ensure_absorbance(
    dataset: "NDDataset",
    validate_reference: bool = True,
) -> "NDDataset":
    """
    Convert dataset to absorbance if needed, with warning.

    This is the auto-convert function for unit mismatches.
    Returns the original dataset if already in absorbance.

    Parameters
    ----------
    dataset : NDDataset
        Input dataset in any spectral unit
    validate_reference : bool
        If True, warn when reference spectrum status is unknown

    Returns
    -------
    NDDataset
        Dataset converted to absorbance units
    """
    unit = parse_spectral_unit(dataset.units)

    if unit == SpectralUnit.ABSORBANCE:
        return dataset

    if unit == SpectralUnit.TRANSMITTANCE:
        # Check reference status before conversion
        if validate_reference and not check_reference_applied(dataset, "transmittance_to_absorbance"):
            warnings.warn(
                "Converting transmittance to absorbance, but reference spectrum status is unknown. "
                "If transmittance data is raw counts (not I/I₀), absorbance values will be incorrect. "
                "Set dataset.meta['reference_applied'] = True to suppress this warning.",
                ReferenceNotAppliedWarning,
            )
        logger.warning(f"Auto-converting from {unit.value} to absorbance. " "Original data units were transmittance.")
        return transmittance_to_absorbance(dataset, validate_reference=False)

    if unit == SpectralUnit.REFLECTANCE:
        logger.warning(
            f"Auto-converting from {unit.value} to Kubelka-Munk (absorbance-like). "
            "Original data units were reflectance."
        )
        return reflectance_to_kubelka_munk(dataset)

    # Dimensionless or unknown - assume already absorbance-like
    logger.warning(f"Unknown unit '{dataset.units}' - treating as absorbance without conversion.")
    result = dataset.copy()
    result.units = SpectralUnit.ABSORBANCE.value
    return result


def transmittance_to_absorbance(
    dataset: "NDDataset",
    validate_reference: bool = True,
) -> "NDDataset":
    """
    Convert Transmittance to Absorbance.

    Formula: A = -log₁₀(T) where T = I/I₀

    IMPORTANT: This assumes transmittance is already ratio'd to reference (I₀).
    If raw counts are provided, results will be meaningless.

    Parameters
    ----------
    dataset : NDDataset
        Dataset in transmittance units (0-1 scale or 0-100%)
    validate_reference : bool
        If True, warn when reference spectrum status is unknown

    Returns
    -------
    NDDataset
        Dataset in absorbance units
    """
    # Check reference status
    if validate_reference and not check_reference_applied(dataset, "transmittance_to_absorbance"):
        warnings.warn(
            "Converting transmittance to absorbance, but reference spectrum status is unknown. "
            "If transmittance data is raw counts (not I/I₀), absorbance values will be incorrect. "
            "Set dataset.meta['reference_applied'] = True to suppress this warning.",
            ReferenceNotAppliedWarning,
        )

    result = dataset.copy()

    # Handle both 0-1 and 0-100 scales
    data = dataset.data.copy()
    if np.nanmax(data) > 1.5:
        # Likely percentage, convert to fraction
        data = data / 100.0
        add_provenance(result, "scale_correction", {"from": "percent", "to": "fraction"})

    # Clip to avoid log(0) and log(negative)
    data = np.clip(data, 1e-10, 1.0)
    result.data = -np.log10(data)
    result.units = SpectralUnit.ABSORBANCE.value

    # Mark reference as applied in output (since we did the conversion)
    if hasattr(result, "meta"):
        result.meta["reference_applied"] = True

    add_provenance(result, "transmittance_to_absorbance", {"source_units": "transmittance"})
    return result


def absorbance_to_transmittance(dataset: "NDDataset") -> "NDDataset":
    """
    Convert Absorbance to Transmittance.

    Formula: T = 10^(-A)

    Parameters
    ----------
    dataset : NDDataset
        Dataset in absorbance units

    Returns
    -------
    NDDataset
        Dataset in transmittance units (0-1 scale)
    """
    result = dataset.copy()
    result.data = np.power(10.0, -dataset.data)
    result.units = SpectralUnit.TRANSMITTANCE.value

    add_provenance(result, "absorbance_to_transmittance", {"source_units": "absorbance"})
    return result


def reflectance_to_kubelka_munk(dataset: "NDDataset") -> "NDDataset":
    """
    Convert Reflectance to Kubelka-Munk.

    Formula: f(R) = (1-R)² / (2R)

    This transforms reflectance data into a quantity that is linear
    with concentration, similar to absorbance.

    Parameters
    ----------
    dataset : NDDataset
        Dataset in reflectance units (0-1 scale or 0-100%)

    Returns
    -------
    NDDataset
        Dataset in Kubelka-Munk units
    """
    result = dataset.copy()

    # Handle both 0-1 and 0-100 scales
    R = dataset.data.copy()
    if np.nanmax(R) > 1.5:
        R = R / 100.0

    # Clip to avoid division by zero
    R = np.clip(R, 1e-10, 1.0)
    result.data = ((1 - R) ** 2) / (2 * R)
    result.units = SpectralUnit.KUBELKA_MUNK.value

    add_provenance(result, "reflectance_to_kubelka_munk", {"source_units": "reflectance"})
    return result


def kubelka_munk_to_reflectance(dataset: "NDDataset") -> "NDDataset":
    """
    Convert Kubelka-Munk to Reflectance.

    Inverse of reflectance_to_kubelka_munk.

    Parameters
    ----------
    dataset : NDDataset
        Dataset in Kubelka-Munk units

    Returns
    -------
    NDDataset
        Dataset in reflectance units (0-1 scale)
    """
    result = dataset.copy()

    # K = (1-R)^2 / (2R)
    # 2KR = (1-R)^2
    # 2KR = 1 - 2R + R^2
    # R^2 - 2R(1+K) + 1 = 0
    # R = (1+K) - sqrt((1+K)^2 - 1)
    K = np.maximum(dataset.data, 0.0)
    discriminant = (1 + K) ** 2 - 1
    discriminant = np.maximum(discriminant, 0.0)  # Numerical safety
    R = (1 + K) - np.sqrt(discriminant)
    R = np.clip(R, 0.0, 1.0)

    result.data = R
    result.units = SpectralUnit.REFLECTANCE.value

    add_provenance(result, "kubelka_munk_to_reflectance", {"source_units": "kubelka_munk"})
    return result
