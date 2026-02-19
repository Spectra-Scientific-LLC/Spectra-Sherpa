"""
Unit-aware validation for spectral operations.

Provides validation functions that check unit compatibility and
optionally auto-convert incompatible units with warnings.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

from .conversions import ensure_absorbance
from .dataset import parse_spectral_unit, validate_unit_compatibility

if TYPE_CHECKING:
    from spectra_sherpa.app.lib.scp_compat import NDDataset

logger = logging.getLogger(__name__)


class UnitMismatchWarning(UserWarning):
    """Warning raised when incompatible spectral units are auto-converted."""

    pass


def assert_compatible_units(
    datasets: List["NDDataset"],
    operation: str,
) -> None:
    """
    Validate that all datasets have compatible units for the operation.

    Parameters
    ----------
    datasets : list[NDDataset]
        Datasets to validate
    operation : str
        Name of the operation (for error messages)

    Raises
    ------
    ValueError
        If datasets have incompatible units
    """
    if len(datasets) < 2:
        return

    units = [parse_spectral_unit(d.units) for d in datasets]

    for i, u1 in enumerate(units):
        for j, u2 in enumerate(units[i + 1 :], i + 1):
            if not validate_unit_compatibility(u1, u2):
                raise ValueError(
                    f"Cannot {operation}: Dataset {i} has {u1.value} units, "
                    f"Dataset {j} has {u2.value} units. "
                    f"Convert to same unit type first."
                )


def validate_and_normalize_units(
    datasets: List["NDDataset"],
    operation: str,
) -> List["NDDataset"]:
    """
    Check unit compatibility. If incompatible, warn and auto-convert.

    This implements the "warning + auto-convert" policy for unit mismatches.

    Parameters
    ----------
    datasets : list[NDDataset]
        Input datasets
    operation : str
        Name of the operation (for warning messages)

    Returns
    -------
    list[NDDataset]
        Datasets with compatible units (auto-converted if necessary)
    """
    if len(datasets) < 2:
        return datasets

    units = [parse_spectral_unit(d.units) for d in datasets]
    unique_units = set(units)

    if len(unique_units) <= 1:
        return datasets  # All same unit, no conversion needed

    # Check for incompatible combinations
    needs_conversion = False
    for u1 in unique_units:
        for u2 in unique_units:
            if u1 != u2 and not validate_unit_compatibility(u1, u2):
                needs_conversion = True
                break
        if needs_conversion:
            break

    if needs_conversion:
        # WARNING + AUTO-CONVERT
        unit_list = [u.value for u in units]
        logger.warning(
            f"[{operation}] Incompatible units detected: {unit_list}. " f"Auto-converting all inputs to absorbance."
        )
        import warnings

        warnings.warn(
            f"[{operation}] Auto-converting incompatible units {unit_list} to absorbance",
            UnitMismatchWarning,
        )
        return [ensure_absorbance(d) for d in datasets]

    return datasets  # Different but compatible units
