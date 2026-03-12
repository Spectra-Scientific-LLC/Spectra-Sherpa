"""
Parsing utilities for metadata normalization.

This module provides robust parsing functions for:
- Physical units (temperature, pressure, length, wavenumber)
- Date/time strings (various formats from different instruments)
- Enumeration mapping (detector types, sampling techniques, etc.)

All parsers use regex for flexibility and return None on failure
rather than raising exceptions.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, Optional, overload

UnitSource = Literal["explicit", "inferred", "default"]
ParsedValueWithSource = tuple[float | None, UnitSource | None]

# =============================================================================
# UNIT PARSING
# =============================================================================

# Temperature patterns - capture value and unit
TEMPERATURE_PATTERN = re.compile(
    r"(?P<value>[-+]?\d+\.?\d*)\s*" r"(?P<unit>°?[CcFfKk]|celsius|fahrenheit|kelvin|deg\s*[CcFfKk])?", re.IGNORECASE
)


@overload
def parse_temperature(
    value: Any, target_unit: str = "C", return_unit_source: Literal[False] = False
) -> float | None: ...


@overload
def parse_temperature(
    value: Any, target_unit: str = "C", return_unit_source: Literal[True] = True
) -> ParsedValueWithSource: ...


def parse_temperature(
    value: Any, target_unit: str = "C", return_unit_source: bool = False
) -> float | None | ParsedValueWithSource:
    """
    Parse temperature from various formats and convert to target unit.

    Args:
        value: Temperature value (number or string like "25C", "77F", "298K")
        target_unit: Target unit ("C", "F", or "K")
        return_unit_source: If True, return tuple (value, source) where source is
                           "explicit", "inferred", or "default"

    Returns:
        Temperature in target unit or None if parsing fails.
        If return_unit_source=True, returns (value, source) tuple.

    Examples:
        >>> parse_temperature("25°C")
        25.0
        >>> parse_temperature("77F", target_unit="C")
        25.0
        >>> parse_temperature(298.15, target_unit="C")  # Inferred as Kelvin
        25.0
        >>> parse_temperature(25.0, return_unit_source=True)
        (25.0, "inferred")

    WARNING: Numeric values without units are INFERRED based on typical ranges.
    This can lead to significant errors (~270°C) if the assumption is wrong.
    Always prefer explicit units (e.g., "298K" instead of 298).
    """
    if value is None:
        return (None, None) if return_unit_source else None

    import logging

    logger = logging.getLogger(__name__)

    # If already a number, try to infer unit from magnitude with better heuristics
    if isinstance(value, (int, float)):
        num_value = float(value)
        unit_source = "inferred"

        # Improved heuristic with explicit reasoning:
        # - Lab conditions: typically -80°C to 400°C (cryogenic to high-temp furnace)
        # - Kelvin values: 77K (liquid N2) to 673K (400°C)
        # - The overlap zone is 200-400 where both units are plausible
        #
        # Decision tree:
        # 1. Values < -100: Almost certainly Celsius (Kelvin can't be negative)
        # 2. Values 0-77: Likely Celsius (room temp range), but could be cryogenic K
        # 3. Values 77-200: Ambiguous - could be warm Celsius or cryogenic Kelvin
        # 4. Values 200-373: HIGHLY AMBIGUOUS - could be hot Celsius or room temp Kelvin
        # 5. Values > 373: More likely Kelvin (would be >100°C boiling point)

        if num_value < -100:
            # Must be Celsius (Kelvin can't be negative, -100°C is reasonable cryo)
            source_unit = "C"
        elif num_value < 0:
            # Negative values must be Celsius
            source_unit = "C"
        elif num_value <= 77:
            # 0-77: Common Celsius range (freezing to warm), assume Celsius
            # Note: 77K is liquid nitrogen, but 77°C is also reasonable
            source_unit = "C"
        elif num_value <= 200:
            # 77-200: Warm lab conditions. Assume Celsius but log warning.
            source_unit = "C"
            logger.warning(
                f"Temperature {num_value} is ambiguous (could be {num_value}°C or {num_value}K). "
                f"Assuming Celsius. For accuracy, use explicit units like '{num_value}K' or '{num_value}°C'."
            )
        elif num_value <= 373:
            # 200-373: CRITICAL AMBIGUOUS ZONE
            # 200°C = 473K (hot but possible), 200K = -73°C (cryo)
            # 373°C = 646K (very hot), 373K = 100°C (boiling point)
            # Default to Kelvin (safer assumption for spectroscopy lab conditions)
            # but issue a strong warning
            source_unit = "K"
            logger.warning(
                f"CRITICAL: Temperature {num_value} is in the highly ambiguous range. "
                f"Interpreted as {num_value}K = {num_value - 273.15:.1f}°C. "
                f"If this should be {num_value}°C, explicitly specify '{num_value}°C' or '{num_value} degC'."
            )
        else:
            # > 373: Likely Kelvin (very high temps are less common in Celsius)
            source_unit = "K"

        result = _convert_temperature(num_value, source_unit, target_unit)
        return (result, unit_source) if return_unit_source else result  # type: ignore[return-value]

    # Parse string
    match = TEMPERATURE_PATTERN.search(str(value))
    if not match:
        return (None, None) if return_unit_source else None

    try:
        num_value = float(match.group("value"))
        unit_str = match.group("unit")

        # Determine if unit was explicit or default
        if unit_str:
            unit_source = "explicit"
            # Normalize unit
            unit_upper = unit_str.upper().replace("°", "").replace("DEG", "").strip()
            if "C" in unit_upper or "CELSIUS" in unit_str.upper():
                source_unit = "C"
            elif "F" in unit_upper or "FAHRENHEIT" in unit_str.upper():
                source_unit = "F"
            elif "K" in unit_upper or "KELVIN" in unit_str.upper():
                source_unit = "K"
            else:
                source_unit = "C"  # Default for unrecognized unit
                unit_source = "default"
        else:
            # No unit specified, default to Celsius
            source_unit = "C"
            unit_source = "default"

        result = _convert_temperature(num_value, source_unit, target_unit)
        return (result, unit_source) if return_unit_source else result  # type: ignore[return-value]

    except (ValueError, TypeError):
        return (None, None) if return_unit_source else None


def _convert_temperature(value: float, from_unit: str, to_unit: str) -> float:
    """Convert temperature between units."""
    # Convert to Celsius first
    if from_unit == "F":
        celsius = (value - 32) * 5 / 9
    elif from_unit == "K":
        celsius = value - 273.15
    else:
        celsius = value

    # Convert from Celsius to target
    if to_unit == "F":
        return celsius * 9 / 5 + 32
    elif to_unit == "K":
        return celsius + 273.15
    else:
        return celsius


# Pressure patterns
PRESSURE_PATTERN = re.compile(
    r"(?P<value>[-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)\s*" r"(?P<unit>mbar|bar|atm|pa|kpa|mpa|torr|mmhg|psi|hpa)?",
    re.IGNORECASE,
)


@overload
def parse_pressure(
    value: Any, target_unit: str = "mbar", return_unit_source: Literal[False] = False
) -> float | None: ...


@overload
def parse_pressure(
    value: Any, target_unit: str = "mbar", return_unit_source: Literal[True] = True
) -> ParsedValueWithSource: ...


def parse_pressure(
    value: Any, target_unit: str = "mbar", return_unit_source: bool = False
) -> float | None | ParsedValueWithSource:
    """
    Parse pressure from various formats and convert to target unit.

    Args:
        value: Pressure value (number or string like "1013 mbar", "1 atm")
        target_unit: Target unit ("mbar", "atm", "Pa", "kPa", "Torr")
        return_unit_source: If True, return tuple (value, source) where source is
                           "explicit" or "default"

    Returns:
        Pressure in target unit or None if parsing fails.
        If return_unit_source=True, returns (value, source) tuple.

    WARNING: Numeric values without units are assumed to be mbar (common FTIR unit).
    Different instruments may use Torr, atm, or Pa. Always prefer explicit units.
    """
    if value is None:
        return (None, None) if return_unit_source else None

    import logging

    logger = logging.getLogger(__name__)

    # If already a number, assume mbar (common FTIR unit) but log warning
    if isinstance(value, (int, float)):
        logger.debug(
            f"Pressure value {value} has no unit specified. "
            f"Assuming mbar (common FTIR unit). If this is incorrect, use explicit units like '{value} Torr'."
        )
        result = _convert_pressure(float(value), "mbar", target_unit)
        return (result, "default") if return_unit_source else result

    match = PRESSURE_PATTERN.search(str(value))
    if not match:
        return (None, None) if return_unit_source else None

    try:
        num_value = float(match.group("value"))
        raw_unit = match.group("unit")
        if raw_unit:
            unit_str = raw_unit.lower()
            unit_source = "explicit"
        else:
            unit_str = "mbar"
            unit_source = "default"

        result = _convert_pressure(num_value, unit_str, target_unit)
        return (result, unit_source) if return_unit_source else result  # type: ignore[return-value]

    except (ValueError, TypeError):
        return (None, None) if return_unit_source else None


def _convert_pressure(value: float, from_unit: str, to_unit: str) -> float:
    """Convert pressure between units."""
    # Conversion factors to mbar
    to_mbar = {
        "mbar": 1.0,
        "bar": 1000.0,
        "atm": 1013.25,
        "pa": 0.01,
        "kpa": 10.0,
        "mpa": 10000.0,
        "hpa": 1.0,  # hPa = mbar
        "torr": 1.33322,
        "mmhg": 1.33322,
        "psi": 68.9476,
    }

    from_unit = from_unit.lower()
    to_unit = to_unit.lower()

    # Convert to mbar
    mbar_value = value * to_mbar.get(from_unit, 1.0)

    # Convert from mbar to target
    return mbar_value / to_mbar.get(to_unit, 1.0)


# Length patterns (for pathlength, aperture, etc.)
LENGTH_PATTERN = re.compile(
    r"(?P<value>[-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)\s*" r"(?P<unit>mm|cm|m|um|µm|nm|in|inch)?", re.IGNORECASE
)


@overload
def parse_length(value: Any, target_unit: str = "mm", return_unit_source: Literal[False] = False) -> float | None: ...


@overload
def parse_length(
    value: Any, target_unit: str = "mm", return_unit_source: Literal[True] = True
) -> ParsedValueWithSource: ...


def parse_length(
    value: Any, target_unit: str = "mm", return_unit_source: bool = False
) -> float | None | ParsedValueWithSource:
    """
    Parse length from various formats and convert to target unit.

    Args:
        value: Length value (number or string like "10 mm", "1.5 cm")
        target_unit: Target unit ("mm", "cm", "m", "um", "nm")
        return_unit_source: If True, return tuple (value, source) where source is
                           "explicit" or "default"

    Returns:
        Length in target unit or None if parsing fails.
        If return_unit_source=True, returns (value, source) tuple.

    WARNING: Numeric values without units are assumed to be in target_unit.
    This can cause significant errors if the assumption is wrong (e.g., µm vs mm).
    """
    if value is None:
        return (None, None) if return_unit_source else None

    import logging

    logger = logging.getLogger(__name__)

    if isinstance(value, (int, float)):
        # Assume target unit - log at debug level as this is common
        logger.debug(
            f"Length value {value} has no unit specified. "
            f"Assuming {target_unit}. If incorrect, use explicit units like '{value} um'."
        )
        return (float(value), "default") if return_unit_source else float(value)

    match = LENGTH_PATTERN.search(str(value))
    if not match:
        return (None, None) if return_unit_source else None

    try:
        num_value = float(match.group("value"))
        raw_unit = match.group("unit")
        if raw_unit:
            unit_str = raw_unit.lower()
            unit_source = "explicit"
        else:
            unit_str = target_unit.lower()
            unit_source = "default"

        # Normalize µm
        if unit_str in ["um", "µm"]:
            unit_str = "um"

        result = _convert_length(num_value, unit_str, target_unit)
        return (result, unit_source) if return_unit_source else result  # type: ignore[return-value]

    except (ValueError, TypeError):
        return (None, None) if return_unit_source else None


def _convert_length(value: float, from_unit: str, to_unit: str) -> float:
    """Convert length between units."""
    # Conversion factors to mm
    to_mm = {
        "mm": 1.0,
        "cm": 10.0,
        "m": 1000.0,
        "um": 0.001,
        "nm": 0.000001,
        "in": 25.4,
        "inch": 25.4,
    }

    from_unit = from_unit.lower()
    to_unit = to_unit.lower()

    mm_value = value * to_mm.get(from_unit, 1.0)
    return mm_value / to_mm.get(to_unit, 1.0)


# Resolution / wavenumber patterns
WAVENUMBER_PATTERN = re.compile(
    r"(?P<value>[-+]?\d+\.?\d*(?:[eE][-+]?\d+)?)\s*" r"(?P<unit>cm-1|cm\^-1|cm⁻¹|1/cm|wavenumber|per cm)?",
    re.IGNORECASE,
)


def parse_wavenumber(value: Any) -> Optional[float]:
    """
    Parse wavenumber value, stripping units.

    Args:
        value: Wavenumber (number or string like "4.0 cm-1")

    Returns:
        Wavenumber as float or None if parsing fails
    """
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    match = WAVENUMBER_PATTERN.search(str(value))
    if not match:
        # Try simple float extraction
        try:
            return float(str(value).split()[0])
        except (ValueError, IndexError):
            return None

    try:
        return float(match.group("value"))
    except (ValueError, TypeError):
        return None


# =============================================================================
# DATE/TIME PARSING
# =============================================================================

# Common date formats from various instruments
DATE_FORMATS = [
    # ISO formats
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%d",
    # European formats (common in Bruker, etc.)
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y",
    # US formats (common in Thermo/Nicolet)
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
    "%m-%d-%Y %H:%M:%S",
    "%m-%d-%Y",
    # Other common formats
    "%Y%m%d%H%M%S",
    "%Y%m%d",
    "%d-%b-%Y %H:%M:%S",  # 15-Jan-2024 10:30:00
    "%d-%b-%Y",
    "%B %d, %Y",  # January 15, 2024
    "%b %d, %Y",  # Jan 15, 2024
]


def parse_datetime(value: Any) -> Optional[str]:
    """
    Parse date/time string from various formats and return ISO format.

    Args:
        value: Date/time value (string or datetime object)

    Returns:
        ISO 8601 formatted datetime string or None if parsing fails

    Examples:
        >>> parse_datetime("15/01/2024 10:30:00")
        "2024-01-15T10:30:00"
        >>> parse_datetime("01-15-2024")
        "2024-01-15T00:00:00"
    """
    if value is None:
        return None

    # Already a datetime object
    if isinstance(value, datetime):
        return value.isoformat()

    # Convert to string
    date_str = str(value).strip()
    if not date_str:
        return None

    # Try each format
    for fmt in DATE_FORMATS:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.isoformat()
        except ValueError:
            continue

    # Try to extract just a date from complex strings
    # E.g., "Collected on 15 Jan 2024 at 10:30"
    date_match = re.search(r"(\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}|\d{4}[-/\.]\d{1,2}[-/\.]\d{1,2})", date_str)
    if date_match:
        extracted = date_match.group(1)
        for fmt in DATE_FORMATS:
            try:
                dt = datetime.strptime(extracted, fmt)
                return dt.isoformat()
            except ValueError:
                continue

    return None


def combine_date_time(date_value: Any, time_value: Any) -> Optional[str]:
    """
    Combine separate date and time values into ISO datetime.

    Args:
        date_value: Date component
        time_value: Time component

    Returns:
        Combined ISO datetime or None if parsing fails
    """
    date_str = str(date_value).strip() if date_value else ""
    time_str = str(time_value).strip() if time_value else ""

    if not date_str:
        return None

    combined = f"{date_str} {time_str}".strip()
    return parse_datetime(combined)


# =============================================================================
# ENUMERATION MAPPING
# =============================================================================


def map_detector_type(raw_value: Any) -> Optional[str]:
    """
    Map raw detector string to DetectorType enum value.

    Args:
        raw_value: Raw detector description from instrument

    Returns:
        Normalized detector type or None
    """
    if raw_value is None:
        return None

    value_lower = str(raw_value).lower()

    # MCT variants
    if "mct" in value_lower:
        if "narrow" in value_lower or "-a" in value_lower or "_a" in value_lower:
            return "mct_a"
        elif "broad" in value_lower or "-b" in value_lower or "_b" in value_lower:
            return "mct_b"
        return "mct"

    # DTGS variants
    if "dtgs" in value_lower or "dlatgs" in value_lower:
        if "kbr" in value_lower:
            return "dtgs_kbr"
        elif "pe" in value_lower or "polyethylene" in value_lower:
            return "dtgs_pe"
        return "dtgs"

    # Other detectors
    detector_map = {
        "ingaas": "ingaas",
        "insb": "insb",
        "pbse": "pbse",
        "silicon": "si",
        "germanium": "ge",
        "bolometer": "bolometer",
    }

    for pattern, detector_type in detector_map.items():
        if pattern in value_lower:
            return detector_type

    return None


def map_sampling_technique(raw_value: Any) -> Optional[str]:
    """
    Map raw technique string to SamplingTechnique enum value.

    Args:
        raw_value: Raw technique description

    Returns:
        Normalized sampling technique or None
    """
    if raw_value is None:
        return None

    value_lower = str(raw_value).lower()

    technique_map = {
        "transmission": "transmission",
        "trans": "transmission",
        "atr": "atr",
        "attenuated": "atr",
        "reflection": "reflection",
        "specular": "reflection",
        "drifts": "drifts",
        "diffuse": "drifts",
        "transflection": "transflection",
        "microscop": "microscopy",
        "emission": "emission",
        "photoacoustic": "pas",
        "pas": "pas",
        "rairs": "rairs",
        "grazing": "rairs",
        "gc-ir": "gc_ir",
        "gc ir": "gc_ir",
        "tga-ir": "tga_ir",
        "tga ir": "tga_ir",
    }

    for pattern, technique in technique_map.items():
        if pattern in value_lower:
            return technique

    return None


def map_window_material(raw_value: Any) -> Optional[str]:
    """
    Map raw window/crystal material to WindowMaterial enum value.

    Args:
        raw_value: Raw material description

    Returns:
        Normalized window material or None
    """
    if raw_value is None:
        return None

    value_lower = str(raw_value).lower()

    material_map = {
        "kbr": "kbr",
        "nacl": "nacl",
        "caf2": "caf2",
        "calcium fluoride": "caf2",
        "baf2": "baf2",
        "barium fluoride": "baf2",
        "znse": "znse",
        "zinc selenide": "znse",
        "zns": "zns",
        "zinc sulfide": "zns",
        "diamond": "diamond",
        "type ii": "diamond",
        "germanium": "ge",
        "silicon": "si",
        "sapphire": "sapphire",
        "krs-5": "krs5",
        "krs5": "krs5",
        "agcl": "agcl",
        "silver chloride": "agcl",
        "polyethylene": "pe",
    }

    for pattern, material in material_map.items():
        if pattern in value_lower:
            return material

    return None


def map_apodization(raw_value: Any) -> Optional[str]:
    """
    Map raw apodization function to normalized name.

    Args:
        raw_value: Raw apodization description

    Returns:
        Normalized apodization function or original value
    """
    if raw_value is None:
        return None

    value_lower = str(raw_value).lower()

    apod_map = {
        "happ": "Happ-Genzel",
        "genzel": "Happ-Genzel",
        "boxcar": "Boxcar",
        "rectangular": "Boxcar",
        "blackman": "Blackman-Harris",
        "harris": "Blackman-Harris",
        "norton": "Norton-Beer",
        "beer": "Norton-Beer",
        "triangular": "Triangular",
        "triangle": "Triangular",
        "cosine": "Cosine",
        "gaussian": "Gaussian",
    }

    for pattern, apod in apod_map.items():
        if pattern in value_lower:
            return apod

    # Return original if no match
    return str(raw_value)
