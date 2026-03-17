"""Helpers for normalizing spectral-domain booleans across mixed dataset sources."""

from __future__ import annotations

from typing import Any

_TRUE_LITERALS = {"1", "true", "yes", "y", "on"}
_FALSE_LITERALS = {"0", "false", "no", "n", "off"}

_SPECTRAL_TECHNIQUE_HINTS = {
    "ftir",
    "ir",
    "infrared",
    "nir",
    "near infrared",
    "raman",
    "uv-vis",
    "uv/vis",
    "uv vis",
    "oes",
    "optical emission spectroscopy",
    "nmr",
    "nmr spectroscopy",
    "ms",
    "mass spectrometry",
    "spectroscopy",
}

_NON_SPECTRAL_TECHNIQUE_HINTS = {
    "generic",
    "non-spectroscopic",
    "non-spectroscopic (tabular)",
    "tabular",
    "ml/statistics",
    "machine learning",
    "process sensors",
    "rf monitor",
    "dsc",
    "differential scanning calorimetry",
    "various",
}

_SPECTRAL_AXIS_UNITS = {
    "cm-1",
    "cm^-1",
    "cm⁻¹",
    "nm",
    "um",
    "µm",
    "ppm",
    "m/z",
    "mz",
    "thz",
    "ev",
}

_SPECTRAL_AXIS_TITLE_HINTS = {
    "wavenumber",
    "wavelength",
    "ppm",
    "chemical shift",
    "m/z",
    "mass/charge",
    "frequency",
}


def _normalize_text(value: Any) -> str:
    return str(value).strip().lower() if value is not None else ""


def coerce_optional_bool(value: Any) -> bool | None:
    """Best-effort coercion for booleans that may arrive as strings or ints."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)

    text = _normalize_text(value)
    if text in _TRUE_LITERALS:
        return True
    if text in _FALSE_LITERALS:
        return False
    return None


def technique_is_spectral(technique: Any) -> bool | None:
    """Return whether a technique label implies spectral data."""
    text = _normalize_text(technique)
    if not text:
        return None
    if text in _SPECTRAL_TECHNIQUE_HINTS:
        return True
    if text in _NON_SPECTRAL_TECHNIQUE_HINTS:
        return False
    if any(hint in text for hint in _SPECTRAL_TECHNIQUE_HINTS if len(hint) > 3):
        return True
    if any(hint in text for hint in _NON_SPECTRAL_TECHNIQUE_HINTS if len(hint) > 3):
        return False
    return None


def axis_hints_imply_spectra(x_title: Any = None, x_units: Any = None) -> bool | None:
    """Infer spectral-ness from axis labels when no explicit boolean exists."""
    title = _normalize_text(x_title)
    units = _normalize_text(x_units)

    if units in _SPECTRAL_AXIS_UNITS:
        return True
    if title in _SPECTRAL_AXIS_TITLE_HINTS:
        return True
    return None


def infer_is_spectra(
    *values: Any,
    technique: Any = None,
    x_title: Any = None,
    x_units: Any = None,
) -> bool:
    """Resolve a canonical ``is_spectra`` boolean from mixed inputs."""
    for value in values:
        coerced = coerce_optional_bool(value)
        if coerced is not None:
            return coerced

    inferred = technique_is_spectral(technique)
    if inferred is not None:
        return inferred

    inferred = axis_hints_imply_spectra(x_title=x_title, x_units=x_units)
    if inferred is not None:
        return inferred

    return False
