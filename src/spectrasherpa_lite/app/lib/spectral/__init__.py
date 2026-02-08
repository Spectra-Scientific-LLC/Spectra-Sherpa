"""
Spectral data utilities with SpectroChemPy integration.

Provides:
- SpectralUnit enum for type-safe unit handling
- create_spectral_dataset() factory function
- Unit validation and auto-conversion
- Parquet serialization with metadata sidecar
- Structured chemometrics metadata (ChemometricsMeta)
"""

from .dataset import (
    SpectralUnit,
    SpectralAxisUnit,
    create_spectral_dataset,
    parse_spectral_unit,
    validate_unit_compatibility,
    add_provenance,
)
from .conversions import (
    ensure_absorbance,
    transmittance_to_absorbance,
    absorbance_to_transmittance,
    reflectance_to_kubelka_munk,
    check_reference_applied,
    ReferenceNotAppliedWarning,
)
from .serialization import (
    save_dataset_parquet,
    load_dataset_parquet,
)
from .validators import (
    UnitMismatchWarning,
    assert_compatible_units,
    validate_and_normalize_units,
)
from .metadata import (
    # Unit enums
    ConcentrationUnit,
    PathlengthUnit,
    TemperatureUnit,
    PressureUnit,
    WavenumberUnit,
    # Pydantic models
    ConcentrationSpec,
    PathlengthSpec,
    MeasurementConditions,
    ReferenceSpectrum,
    SpectralResolution,
    CalibrationRange,
    ChemometricsMeta,
    # Helper functions
    extract_chemometrics_meta,
    apply_chemometrics_meta,
    # Frontend dropdown choices
    FRONTEND_CONCENTRATION_UNITS,
    FRONTEND_PATHLENGTH_UNITS,
    FRONTEND_TEMPERATURE_UNITS,
    FRONTEND_PRESSURE_UNITS,
    FRONTEND_WAVENUMBER_UNITS,
    FRONTEND_MEASUREMENT_TYPES,
    FRONTEND_REFERENCE_TYPES,
)

__all__ = [
    # Dataset
    "SpectralUnit",
    "SpectralAxisUnit",
    "create_spectral_dataset",
    "parse_spectral_unit",
    "validate_unit_compatibility",
    "add_provenance",
    # Conversions
    "ensure_absorbance",
    "transmittance_to_absorbance",
    "absorbance_to_transmittance",
    "reflectance_to_kubelka_munk",
    "check_reference_applied",
    "ReferenceNotAppliedWarning",
    # Serialization
    "save_dataset_parquet",
    "load_dataset_parquet",
    # Validators
    "UnitMismatchWarning",
    "assert_compatible_units",
    "validate_and_normalize_units",
    # Metadata - Unit enums
    "ConcentrationUnit",
    "PathlengthUnit",
    "TemperatureUnit",
    "PressureUnit",
    "WavenumberUnit",
    # Metadata - Models
    "ConcentrationSpec",
    "PathlengthSpec",
    "MeasurementConditions",
    "ReferenceSpectrum",
    "SpectralResolution",
    "CalibrationRange",
    "ChemometricsMeta",
    # Metadata - Functions
    "extract_chemometrics_meta",
    "apply_chemometrics_meta",
    # Frontend choices
    "FRONTEND_CONCENTRATION_UNITS",
    "FRONTEND_PATHLENGTH_UNITS",
    "FRONTEND_TEMPERATURE_UNITS",
    "FRONTEND_PRESSURE_UNITS",
    "FRONTEND_WAVENUMBER_UNITS",
    "FRONTEND_MEASUREMENT_TYPES",
    "FRONTEND_REFERENCE_TYPES",
]
