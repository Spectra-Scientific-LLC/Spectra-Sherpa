"""
Structured metadata models for chemometrics.

Provides Pydantic models that enforce unit consistency and
track measurement conditions required for accurate quantitative analysis.

Key principle: Beer-Lambert law (A = εlc) requires consistent units.
Mixing units silently causes 10-1000× errors in predictions.
"""

from __future__ import annotations

import warnings
from enum import Enum
from typing import Optional, List, Dict, Any, Literal, TYPE_CHECKING
from pydantic import BaseModel, Field, field_validator, model_validator

if TYPE_CHECKING:
    from app.lib.scp_compat import NDDataset


# ═══════════════════════════════════════════════════════════════════════════════
# UNIT ENUMERATIONS
# ═══════════════════════════════════════════════════════════════════════════════


class ConcentrationUnit(str, Enum):
    """Concentration units with conversion factors to mol/L."""

    PPM = "ppm"  # parts per million (volume or mass basis - context dependent)
    PPB = "ppb"  # parts per billion
    PPM_V = "ppmv"  # parts per million by volume (gas phase)
    PPM_M = "ppmm"  # parts per million by mass
    MOL_PER_L = "mol/L"  # molar concentration
    MMOL_PER_L = "mmol/L"  # millimolar
    UMOL_PER_L = "µmol/L"  # micromolar
    MG_PER_L = "mg/L"  # mass concentration
    UG_PER_L = "µg/L"  # microgram per liter
    PERCENT_W = "wt%"  # weight percent
    PERCENT_V = "vol%"  # volume percent
    DIMENSIONLESS = "dimensionless"  # normalized or relative


class PathlengthUnit(str, Enum):
    """Pathlength units with conversion factors to meters."""

    METER = "m"
    CENTIMETER = "cm"
    MILLIMETER = "mm"
    MICROMETER = "µm"


class TemperatureUnit(str, Enum):
    """Temperature units."""

    KELVIN = "K"
    CELSIUS = "°C"
    FAHRENHEIT = "°F"


class PressureUnit(str, Enum):
    """Pressure units with conversion factors to Pa."""

    PASCAL = "Pa"
    KILOPASCAL = "kPa"
    BAR = "bar"
    MILLIBAR = "mbar"
    ATM = "atm"
    TORR = "torr"
    PSI = "psi"


class WavenumberUnit(str, Enum):
    """Spectral axis units."""

    CM_INV = "cm^-1"  # wavenumber (IR, Raman)
    NM = "nm"  # wavelength (UV-Vis, NIR)
    UM = "µm"  # wavelength (mid-IR)
    RAMAN_SHIFT = "Δcm^-1"  # Raman shift relative to excitation


# ═══════════════════════════════════════════════════════════════════════════════
# FRONTEND DROPDOWN CHOICES (Most Prevalent Units)
# ═══════════════════════════════════════════════════════════════════════════════

# These are the most commonly used units - limit dropdowns to these
FRONTEND_CONCENTRATION_UNITS = [
    {"value": "ppm", "label": "ppm (parts per million)"},
    {"value": "ppmv", "label": "ppmv (by volume, gas)"},
    {"value": "mol/L", "label": "mol/L (molar)"},
    {"value": "mg/L", "label": "mg/L"},
    {"value": "wt%", "label": "wt% (weight percent)"},
    {"value": "vol%", "label": "vol% (volume percent)"},
]

FRONTEND_PATHLENGTH_UNITS = [
    {"value": "cm", "label": "cm (centimeters)"},
    {"value": "m", "label": "m (meters)"},
    {"value": "mm", "label": "mm (millimeters)"},
]

FRONTEND_TEMPERATURE_UNITS = [
    {"value": "°C", "label": "°C (Celsius)"},
    {"value": "K", "label": "K (Kelvin)"},
]

FRONTEND_PRESSURE_UNITS = [
    {"value": "atm", "label": "atm (atmospheres)"},
    {"value": "bar", "label": "bar"},
    {"value": "kPa", "label": "kPa (kilopascals)"},
    {"value": "torr", "label": "torr (mmHg)"},
]

FRONTEND_WAVENUMBER_UNITS = [
    {"value": "cm^-1", "label": "cm⁻¹ (wavenumber)"},
    {"value": "nm", "label": "nm (wavelength)"},
]

FRONTEND_MEASUREMENT_TYPES = [
    {"value": "transmission", "label": "Transmission"},
    {"value": "ATR", "label": "ATR (Attenuated Total Reflectance)"},
    {"value": "DRIFTS", "label": "DRIFTS (Diffuse Reflectance)"},
]

FRONTEND_REFERENCE_TYPES = [
    {"value": "background", "label": "Background (empty cell)"},
    {"value": "blank", "label": "Blank (solvent only)"},
    {"value": "air", "label": "Air"},
    {"value": "nitrogen", "label": "Nitrogen (N₂)"},
]


# ═══════════════════════════════════════════════════════════════════════════════
# CONVERSION FACTORS
# ═══════════════════════════════════════════════════════════════════════════════

PATHLENGTH_TO_METERS = {
    PathlengthUnit.METER: 1.0,
    PathlengthUnit.CENTIMETER: 0.01,
    PathlengthUnit.MILLIMETER: 0.001,
    PathlengthUnit.MICROMETER: 1e-6,
}

PRESSURE_TO_PASCAL = {
    PressureUnit.PASCAL: 1.0,
    PressureUnit.KILOPASCAL: 1000.0,
    PressureUnit.BAR: 100000.0,
    PressureUnit.MILLIBAR: 100.0,
    PressureUnit.ATM: 101325.0,
    PressureUnit.TORR: 133.322,
    PressureUnit.PSI: 6894.76,
}


def convert_temperature_to_kelvin(value: float, unit: TemperatureUnit) -> float:
    """Convert temperature to Kelvin."""
    if unit == TemperatureUnit.KELVIN:
        return value
    elif unit == TemperatureUnit.CELSIUS:
        return value + 273.15
    elif unit == TemperatureUnit.FAHRENHEIT:
        return (value - 32) * 5 / 9 + 273.15
    raise ValueError(f"Unknown temperature unit: {unit}")


# ═══════════════════════════════════════════════════════════════════════════════
# METADATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════


class ConcentrationSpec(BaseModel):
    """
    Concentration value with explicit units.

    Essential for Beer-Lambert: A = ε × l × c
    Units of ε, l, and c must be consistent.
    """

    value: float = Field(..., description="Concentration value")
    unit: ConcentrationUnit = Field(..., description="Concentration unit")
    species: Optional[str] = Field(None, description="Chemical species name or CAS number")
    is_reference: bool = Field(False, description="True if this is the reference concentration for calibration")

    def to_ppm(self, molecular_weight: Optional[float] = None) -> float:
        """
        Convert to ppm (requires molecular weight for mol/L conversions).

        Note: ppm is ambiguous - this returns ppmv for gases, ppmm for liquids.
        """
        if self.unit in (ConcentrationUnit.PPM, ConcentrationUnit.PPM_V, ConcentrationUnit.PPM_M):
            return self.value
        elif self.unit == ConcentrationUnit.PPB:
            return self.value / 1000.0
        elif self.unit == ConcentrationUnit.PERCENT_V:
            return self.value * 10000.0
        elif self.unit == ConcentrationUnit.PERCENT_W:
            return self.value * 10000.0
        elif self.unit == ConcentrationUnit.MOL_PER_L and molecular_weight:
            # Approximate: 1 mol/L ≈ MW g/L ≈ MW * 1000 ppm for dilute aqueous
            return self.value * molecular_weight * 1000.0
        else:
            raise ValueError(f"Cannot convert {self.unit} to ppm without additional info")


class PathlengthSpec(BaseModel):
    """
    Pathlength value with explicit units.

    Critical for Beer-Lambert: A = ε × l × c
    Common error: calibration in cm, prediction in m → 100× error.
    """

    value: float = Field(..., ge=0, description="Pathlength value")
    unit: PathlengthUnit = Field(..., description="Pathlength unit")

    def to_meters(self) -> float:
        """Convert to meters (SI base unit)."""
        return self.value * PATHLENGTH_TO_METERS[self.unit]

    def to_centimeters(self) -> float:
        """Convert to centimeters (common in spectroscopy)."""
        return self.to_meters() * 100.0


class MeasurementConditions(BaseModel):
    """
    Physical conditions during spectrum acquisition.

    Temperature and pressure affect:
    - Gas-phase line positions and intensities
    - Solvent absorption bands
    - Refractive index (affects ATR penetration depth)
    """

    temperature: Optional[float] = Field(None, description="Temperature value")
    temperature_unit: TemperatureUnit = Field(TemperatureUnit.CELSIUS, description="Temperature unit")
    pressure: Optional[float] = Field(None, description="Pressure value")
    pressure_unit: PressureUnit = Field(PressureUnit.ATM, description="Pressure unit")
    humidity_percent: Optional[float] = Field(None, ge=0, le=100, description="Relative humidity %")

    def temperature_kelvin(self) -> Optional[float]:
        """Get temperature in Kelvin."""
        if self.temperature is None:
            return None
        return convert_temperature_to_kelvin(self.temperature, self.temperature_unit)

    def pressure_pascal(self) -> Optional[float]:
        """Get pressure in Pascal."""
        if self.pressure is None:
            return None
        return self.pressure * PRESSURE_TO_PASCAL[self.pressure_unit]


class ReferenceSpectrum(BaseModel):
    """
    Reference spectrum information for absorbance calculations.

    Absorbance = log₁₀(I₀/I) requires knowing I₀.
    Without this, transmittance→absorbance conversion is unreliable.
    """

    applied: bool = Field(False, description="True if reference has been applied")
    reference_type: Optional[Literal["background", "blank", "solvent", "air", "nitrogen"]] = Field(
        None, description="Type of reference spectrum"
    )
    reference_id: Optional[str] = Field(None, description="ID or path of reference spectrum")
    acquisition_time: Optional[str] = Field(None, description="When reference was acquired (ISO format)")
    conditions: Optional[MeasurementConditions] = Field(
        None, description="Conditions when reference was acquired"
    )


class SpectralResolution(BaseModel):
    """
    Spectral resolution and grid information.

    Interpolation accuracy depends on:
    - Original resolution vs target grid spacing
    - Peak width relative to grid spacing
    """

    original_spacing: Optional[float] = Field(None, description="Original wavenumber spacing (cm^-1)")
    current_spacing: Optional[float] = Field(None, description="Current grid spacing after interpolation")
    resolution_cm_inv: Optional[float] = Field(
        None, description="Instrument resolution (FWHM of narrowest resolvable feature)"
    )
    interpolated: bool = Field(False, description="True if data has been interpolated")
    interpolation_method: Optional[str] = Field(None, description="Interpolation method used")

    @property
    def interpolation_ratio(self) -> Optional[float]:
        """Ratio of current to original spacing. >1 means upsampling, <1 means downsampling."""
        if self.original_spacing and self.current_spacing:
            return self.current_spacing / self.original_spacing
        return None

    def warn_if_undersampled(self, peak_width_cm_inv: float = 1.0) -> None:
        """
        Warn if grid is too coarse for sharp peaks.

        Nyquist: need at least 2 points per peak width.
        """
        if self.current_spacing and self.current_spacing > peak_width_cm_inv / 2:
            warnings.warn(
                f"Grid spacing ({self.current_spacing:.2f} cm^-1) is too coarse "
                f"for peaks with FWHM < {peak_width_cm_inv:.2f} cm^-1. "
                f"Peak heights may be underestimated by 10-30%.",
                UserWarning,
            )


class CalibrationRange(BaseModel):
    """
    Valid range for a calibration model.

    Extrapolation beyond calibration range is a major source of error.
    Linear models extrapolate poorly; saturation models may diverge.
    """

    min_concentration: float = Field(..., description="Minimum calibration concentration")
    max_concentration: float = Field(..., description="Maximum calibration concentration")
    concentration_unit: ConcentrationUnit = Field(..., description="Concentration unit for range")
    wavenumber_min: float = Field(..., description="Minimum wavenumber (cm^-1)")
    wavenumber_max: float = Field(..., description="Maximum wavenumber (cm^-1)")
    n_calibration_points: Optional[int] = Field(None, ge=2, description="Number of calibration standards")
    calibration_conditions: Optional[MeasurementConditions] = Field(
        None, description="Conditions during calibration"
    )
    model_type: Optional[str] = Field(None, description="Calibration model type (linear, saturation, hybrid)")

    def check_concentration(self, concentration: float, warn: bool = True) -> bool:
        """
        Check if concentration is within calibration range.

        Returns True if within range, False if extrapolating.
        """
        in_range = self.min_concentration <= concentration <= self.max_concentration
        if not in_range and warn:
            if concentration < self.min_concentration:
                pct_below = (self.min_concentration - concentration) / self.min_concentration * 100
                warnings.warn(
                    f"Concentration {concentration} is {pct_below:.1f}% below calibration minimum "
                    f"({self.min_concentration}). Extrapolation may be inaccurate.",
                    UserWarning,
                )
            else:
                pct_above = (concentration - self.max_concentration) / self.max_concentration * 100
                warnings.warn(
                    f"Concentration {concentration} is {pct_above:.1f}% above calibration maximum "
                    f"({self.max_concentration}). Extrapolation may be inaccurate, especially for "
                    f"saturation models.",
                    UserWarning,
                )
        return in_range

    def check_wavenumber_range(self, wn_min: float, wn_max: float, warn: bool = True) -> bool:
        """Check if wavenumber range is within calibration range."""
        in_range = wn_min >= self.wavenumber_min and wn_max <= self.wavenumber_max
        if not in_range and warn:
            warnings.warn(
                f"Data wavenumber range [{wn_min:.1f}, {wn_max:.1f}] extends beyond "
                f"calibration range [{self.wavenumber_min:.1f}, {self.wavenumber_max:.1f}]. "
                f"Predictions outside calibration range may be unreliable.",
                UserWarning,
            )
        return in_range


class ChemometricsMeta(BaseModel):
    """
    Complete metadata for a spectral dataset in chemometrics workflows.

    This is the structured replacement for the unstructured NDDataset.meta dict.
    All fields that affect quantitative accuracy are explicitly typed.
    """

    # Sample identification
    sample_id: Optional[str] = Field(None, description="Unique sample identifier")
    sample_name: Optional[str] = Field(None, description="Human-readable sample name")
    species: Optional[List[str]] = Field(None, description="Chemical species present")

    # Concentration (if known)
    concentrations: Optional[Dict[str, ConcentrationSpec]] = Field(
        None, description="Concentration by species name"
    )

    # Measurement geometry
    pathlength: Optional[PathlengthSpec] = Field(None, description="Optical pathlength")
    measurement_type: Optional[Literal["transmission", "ATR", "DRIFTS", "specular_reflection", "emission"]] = Field(
        None, description="Measurement geometry"
    )

    # Conditions
    conditions: Optional[MeasurementConditions] = Field(None, description="Measurement conditions")

    # Reference
    reference: Optional[ReferenceSpectrum] = Field(None, description="Reference spectrum info")

    # Resolution
    resolution: Optional[SpectralResolution] = Field(None, description="Spectral resolution info")

    # Calibration
    calibration_range: Optional[CalibrationRange] = Field(
        None, description="Valid range for calibration model"
    )

    # Provenance
    source_file: Optional[str] = Field(None, description="Original source file path")
    source_type: Optional[str] = Field(None, description="Source type (NIST, HITRAN, measured, etc.)")
    acquisition_time: Optional[str] = Field(None, description="Acquisition timestamp (ISO format)")
    instrument: Optional[str] = Field(None, description="Instrument identifier")
    processing_history: List[str] = Field(default_factory=list, description="Processing steps applied")

    # Uncertainty
    snr: Optional[float] = Field(None, ge=0, description="Signal-to-noise ratio")
    uncertainty_percent: Optional[float] = Field(None, ge=0, description="Relative uncertainty %")

    def add_processing_step(self, step: str) -> None:
        """Add a processing step to the history."""
        self.processing_history.append(step)

    def validate_for_blending(self) -> List[str]:
        """
        Validate that metadata is complete for blending operations.

        Returns list of warnings/errors.
        """
        issues = []

        if not self.reference or not self.reference.applied:
            issues.append("Reference spectrum not applied - absorbance values may be incorrect")

        if not self.pathlength:
            issues.append("Pathlength not specified - cannot normalize for different cell lengths")

        if not self.conditions:
            issues.append("Measurement conditions not specified - cannot check for T/P compatibility")

        if self.calibration_range:
            if not self.resolution:
                issues.append("Resolution info missing - cannot validate interpolation quality")

        return issues


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════


def extract_chemometrics_meta(dataset: "NDDataset") -> ChemometricsMeta:
    """
    Extract ChemometricsMeta from NDDataset.meta dict.

    Attempts to parse structured fields from the unstructured meta dict.
    """
    meta = dataset.meta if hasattr(dataset, "meta") and dataset.meta else {}

    # Try to extract known fields
    kwargs: Dict[str, Any] = {}

    # Sample info
    if "sample_id" in meta:
        kwargs["sample_id"] = meta["sample_id"]
    if "sample_name" in meta or "title" in meta:
        kwargs["sample_name"] = meta.get("sample_name", meta.get("title"))
    if "species" in meta:
        kwargs["species"] = meta["species"] if isinstance(meta["species"], list) else [meta["species"]]

    # Pathlength
    if "pathlength_m" in meta:
        kwargs["pathlength"] = PathlengthSpec(value=meta["pathlength_m"], unit=PathlengthUnit.METER)
    elif "pathlength" in meta and "pathlength_unit" in meta:
        unit = PathlengthUnit(meta["pathlength_unit"]) if meta["pathlength_unit"] else PathlengthUnit.METER
        kwargs["pathlength"] = PathlengthSpec(value=meta["pathlength"], unit=unit)

    # Conditions
    if "temperature" in meta or "pressure" in meta:
        kwargs["conditions"] = MeasurementConditions(
            temperature=meta.get("temperature"),
            pressure=meta.get("pressure"),
        )

    # Source
    if "source_file" in meta:
        kwargs["source_file"] = meta["source_file"]
    if "source_type" in meta:
        kwargs["source_type"] = meta["source_type"]

    # Processing history
    if "provenance" in meta and isinstance(meta["provenance"], list):
        kwargs["processing_history"] = [str(p) for p in meta["provenance"]]

    return ChemometricsMeta(**kwargs)


def apply_chemometrics_meta(dataset: "NDDataset", chem_meta: ChemometricsMeta) -> None:
    """
    Apply ChemometricsMeta to NDDataset.meta dict.

    Stores structured data in a way that can be recovered later.
    """
    if not hasattr(dataset, "meta"):
        return

    # Store the full model as JSON-compatible dict
    dataset.meta["chemometrics"] = chem_meta.model_dump(exclude_none=True)

    # Also store commonly-accessed fields at top level for convenience
    if chem_meta.sample_id:
        dataset.meta["sample_id"] = chem_meta.sample_id
    if chem_meta.pathlength:
        dataset.meta["pathlength_m"] = chem_meta.pathlength.to_meters()
    if chem_meta.source_type:
        dataset.meta["source_type"] = chem_meta.source_type


__all__ = [
    # Units
    "ConcentrationUnit",
    "PathlengthUnit",
    "TemperatureUnit",
    "PressureUnit",
    "WavenumberUnit",
    # Models
    "ConcentrationSpec",
    "PathlengthSpec",
    "MeasurementConditions",
    "ReferenceSpectrum",
    "SpectralResolution",
    "CalibrationRange",
    "ChemometricsMeta",
    # Functions
    "extract_chemometrics_meta",
    "apply_chemometrics_meta",
    "convert_temperature_to_kelvin",
]
