"""Canonical physical meaning for analytical feature axes.

Coordinate values are not scientifically identified by their numeric grid
alone.  In particular, absolute wavenumber and Raman shift share inverse-
centimetre units while representing different physical quantities.  This
module owns the small, closed vocabulary used by readers, collection
assembly, fitted-state admission, and multi-input DAG operations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class AxisQuantity(StrEnum):
    WAVENUMBER = "wavenumber"
    RAMAN_SHIFT = "raman_shift"
    WAVELENGTH = "wavelength"
    TIME = "time"
    MASS_TO_CHARGE = "mass_to_charge"
    POTENTIAL = "potential"
    FREQUENCY = "frequency"
    SPATIAL = "spatial"
    INDEX = "index"


_SPACE_RE = re.compile(r"\s+")
_SUPERSCRIPT_MINUS_ONE = str.maketrans({"⁻": "-", "−": "-", "¹": "1"})


def _unit_key(value: str) -> str:
    return _SPACE_RE.sub("", value.strip().lower().translate(_SUPERSCRIPT_MINUS_ONE))


_CANONICAL_UNITS: dict[str, str] = {
    "cm-1": "cm-1",
    "cm^-1": "cm-1",
    "1/cm": "cm-1",
    "cm−1": "cm-1",
    "wavenumber(cm-1)": "cm-1",
    "wavenumbers(cm-1)": "cm-1",
    "wavenumber(cm^-1)": "cm-1",
    "wavenumbers(cm^-1)": "cm-1",
    "ramanshift(cm-1)": "cm-1",
    "ramanshift(cm^-1)": "cm-1",
    "nm": "nm",
    "nanometer": "nm",
    "nanometers": "nm",
    "nanometre": "nm",
    "nanometres": "nm",
    "um": "µm",
    "µm": "µm",
    "μm": "µm",
    "micron": "µm",
    "microns": "µm",
    "micrometer": "µm",
    "micrometers": "µm",
    "micrometre": "µm",
    "micrometres": "µm",
    "s": "s",
    "sec": "s",
    "second": "s",
    "seconds": "s",
    "ms": "ms",
    "millisecond": "ms",
    "milliseconds": "ms",
    "min": "min",
    "minute": "min",
    "minutes": "min",
    "h": "h",
    "hr": "h",
    "hour": "h",
    "hours": "h",
    "m/z": "m/z",
    "mz": "m/z",
    "v": "V",
    "volt": "V",
    "volts": "V",
    "mv": "mV",
    "millivolt": "mV",
    "millivolts": "mV",
    "hz": "Hz",
    "hertz": "Hz",
    "mhz": "MHz",
    "megahertz": "MHz",
    "ghz": "GHz",
    "gigahertz": "GHz",
    "mm": "mm",
    "cm": "cm",
    "px": "px",
    "pixel": "px",
    "pixels": "px",
}


_QUANTITY_TOKENS: tuple[tuple[AxisQuantity, tuple[str, ...]], ...] = (
    (AxisQuantity.RAMAN_SHIFT, ("raman shift", "raman-shift", "ramanshift")),
    (AxisQuantity.WAVENUMBER, ("wavenumber", "wave number")),
    (AxisQuantity.WAVELENGTH, ("wavelength", "wave length")),
    (AxisQuantity.MASS_TO_CHARGE, ("mass-to-charge", "mass to charge", "m/z")),
    (AxisQuantity.POTENTIAL, ("potential", "voltage")),
    (AxisQuantity.FREQUENCY, ("frequency",)),
    (AxisQuantity.TIME, ("retention time", "elution time", "process time", "time")),
    (AxisQuantity.SPATIAL, ("spatial", "position", "pixel", "distance")),
    (AxisQuantity.INDEX, ("index", "channel", "data point")),
)


_CLASS_QUANTITY: dict[str, AxisQuantity] = {
    "TimeAxis": AxisQuantity.TIME,
    "MZAxis": AxisQuantity.MASS_TO_CHARGE,
    "PotentialAxis": AxisQuantity.POTENTIAL,
    "FrequencyAxis": AxisQuantity.FREQUENCY,
    "SpatialAxis": AxisQuantity.SPATIAL,
}


def canonical_axis_unit(value: str | None) -> str | None:
    """Return the canonical spelling for a known physical unit.

    Unknown units are retained verbatim after whitespace validation.  A reader
    may know a valid domain-specific unit that is not yet in this deliberately
    small vocabulary; preserving it is safer than guessing or erasing it.
    """

    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError("axis units must be non-empty whitespace-canonical text")
    return _CANONICAL_UNITS.get(_unit_key(value), value)


def infer_axis_quantity(
    *,
    axis_class: str,
    title: str | None,
    units: str | None,
    declared: AxisQuantity | str | None = None,
) -> AxisQuantity | None:
    """Resolve quantity without treating a unit as sufficient authority."""

    if declared is not None:
        return declared if isinstance(declared, AxisQuantity) else AxisQuantity(declared)
    class_quantity = _CLASS_QUANTITY.get(axis_class)
    if class_quantity is not None:
        return class_quantity
    evidence = " ".join(part.strip().lower() for part in (title, units) if part)
    for quantity, tokens in _QUANTITY_TOKENS:
        if any(token in evidence for token in tokens):
            return quantity
    # Wavelength units identify wavelength unambiguously.  Inverse centimetres
    # do not: they may be absolute wavenumber or Raman shift.
    canonical = canonical_axis_unit(units)
    if axis_class == "SpectralAxis" and canonical in {"nm", "µm"}:
        return AxisQuantity.WAVELENGTH
    return None


@dataclass(frozen=True, slots=True)
class AxisSemantics:
    """Canonical quantity and unit identity, separate from coordinate values."""

    quantity: AxisQuantity | None
    units: str | None


def axis_semantics(
    *,
    axis_class: str,
    title: str | None,
    units: str | None,
    quantity: AxisQuantity | str | None = None,
) -> AxisSemantics:
    canonical_units = canonical_axis_unit(units)
    return AxisSemantics(
        quantity=infer_axis_quantity(
            axis_class=axis_class,
            title=title,
            units=units,
            declared=quantity,
        ),
        units=canonical_units,
    )


def require_compatible_axis_semantics(
    left: AxisSemantics,
    right: AxisSemantics,
    *,
    context: str,
    require_quantity: bool = True,
) -> None:
    """Refuse missing or different physical axis identities.

    Spectral operations require an explicit quantity because identical units
    can represent different science (for example wavenumber and Raman shift).
    Generic feature tables may have no physical axis at all; callers can allow
    that case while still refusing asymmetric or contradictory declarations.
    """

    if require_quantity and (left.quantity is None or right.quantity is None):
        raise ValueError(
            f"{context} requires explicit feature-axis quantities; "
            "declare the missing quantity and units before combining inputs"
        )
    if (left.quantity is None) != (right.quantity is None):
        raise ValueError(
            f"{context} requires matching feature-axis quantity declarations; "
            "declare the missing quantity and units before combining inputs"
        )
    if left.quantity != right.quantity:
        assert left.quantity is not None and right.quantity is not None
        raise ValueError(f"{context} cannot combine {left.quantity.value!r} and {right.quantity.value!r} feature axes")
    # An explicitly declared index/channel axis is dimensionless.  Requiring a
    # made-up physical unit for it would turn honest source metadata into a
    # collection-admission failure.
    unitless_index = left.quantity is AxisQuantity.INDEX and right.quantity is AxisQuantity.INDEX
    if require_quantity and not unitless_index and (left.units is None or right.units is None):
        raise ValueError(
            f"{context} requires explicit feature-axis units; "
            "declare the missing quantity and units before combining inputs"
        )
    if (left.units is None) != (right.units is None):
        raise ValueError(
            f"{context} requires matching feature-axis unit declarations; "
            "declare the missing quantity and units before combining inputs"
        )
    if left.units != right.units:
        raise ValueError(f"{context} requires matching canonical feature-axis units")


__all__ = [
    "AxisQuantity",
    "AxisSemantics",
    "axis_semantics",
    "canonical_axis_unit",
    "infer_axis_quantity",
    "require_compatible_axis_semantics",
]
