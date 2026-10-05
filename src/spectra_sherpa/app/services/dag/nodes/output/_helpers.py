"""
Shared helper functions for output nodes.
"""

from __future__ import annotations

from typing import Any


def get_axis_display_info(axis: Any) -> dict[str, Any]:
    """
    Get display information for any axis type.

    Returns dict with:
        - title: Human-readable axis title
        - units: Unit string (empty if dimensionless)
        - label: Formatted label with units
        - should_reverse: Whether axis should be reversed (e.g., wavenumber)
        - default_title: Default title if axis.title is None
    """
    from spectra_sherpa.app.lib.axes import (
        FrequencyAxis,
        MZAxis,
        PotentialAxis,
        SpectralAxis,
        TimeAxis,
    )

    if axis is None:
        return {
            "title": "Index",
            "units": "",
            "label": "Index",
            "should_reverse": False,
            "default_title": "Index",
        }

    # Get units (handle None and "dimensionless")
    units_str = ""
    if hasattr(axis, "units") and axis.units:
        units_str = str(axis.units)
        if units_str == "dimensionless":
            units_str = ""

    # Determine title and default based on axis type
    if isinstance(axis, SpectralAxis):
        quantity = getattr(axis, "quantity", None)
        quantity_value = getattr(quantity, "value", quantity)
        declared_title = str(getattr(axis, "title", "") or "").strip()
        title_key = declared_title.casefold().replace("-", " ")
        if quantity_value == "wavenumber" or "wavenumber" in title_key or "wave number" in title_key:
            default_title = "Wavenumber"
            should_reverse = True
        elif quantity_value == "raman_shift" or "raman shift" in title_key:
            default_title = "Raman Shift"
            should_reverse = False
        elif quantity_value == "wavelength":
            default_title = "Wavelength"
            should_reverse = False
        else:
            # Inverse centimetres alone do not distinguish absolute
            # wavenumber from Raman shift, so an unknown quantity remains in
            # acquisition order rather than being reversed by guesswork.
            default_title = "Spectral Coordinate"
            should_reverse = False
    elif isinstance(axis, TimeAxis):
        default_title = "Time"
        should_reverse = False
    elif isinstance(axis, MZAxis):
        default_title = "m/z"
        should_reverse = False
    elif isinstance(axis, PotentialAxis):
        default_title = "Potential"
        should_reverse = False
    elif isinstance(axis, FrequencyAxis):
        default_title = "Frequency" if "Hz" in units_str else "Chemical Shift"
        should_reverse = False
    else:
        # Generic FeatureAxis or SampleAxis
        default_title = str(axis.title) if hasattr(axis, "title") and axis.title else "Feature"
        should_reverse = False

    # Use axis title if available, otherwise use default
    title = str(axis.title) if hasattr(axis, "title") and axis.title else default_title

    # Build formatted label
    if units_str:
        label = f"{title} ({units_str})"
    else:
        label = title

    return {
        "title": title,
        "units": units_str,
        "label": label,
        "should_reverse": should_reverse,
        "default_title": default_title,
    }
