"""
Unified metadata schema for spectral data.

This module defines Pydantic models for comprehensive spectral metadata,
designed to be stored in NDDataset.meta["spectra"] as JSON.

Key Design Principles:
- All fields optional - use what you have
- GxP-ready (21 CFR Part 11, GLP/GMP compliant structure)
- Extensible for future data sources
- Compatible with JCAMP-DX, HITRAN, NIST, and instrument formats

Usage:
    from spectrochempy import NDDataset
    from spectra_sherpa.app.models.spectra_meta import SpectraMeta, get_spectra_meta, set_spectra_meta

    # Read metadata
    meta = get_spectra_meta(dataset)
    print(meta.species[0].name)

    # Write metadata
    meta = SpectraMeta(provenance=DataProvenance(source_type=SourceType.EXPERIMENT))
    set_spectra_meta(dataset, meta)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# =============================================================================
# ENUMERATIONS
# =============================================================================

class PhysicalState(str, Enum):
    """Physical state of matter for spectroscopic samples."""
    GAS = "gas"
    LIQUID = "liquid"
    SOLID = "solid"
    PLASMA = "plasma"
    SOLUTION = "solution"          # Dissolved in solvent
    FILM = "film"                  # Thin film / coating
    POWDER = "powder"              # Powder sample
    KBR_PELLET = "kbr_pellet"      # KBr pellet (common for solids)
    MULL = "mull"                  # Nujol mull
    GEL = "gel"
    SUSPENSION = "suspension"
    UNKNOWN = "unknown"


class ConcentrationUnit(str, Enum):
    """Units for concentration values."""
    PPM = "ppm"                    # Parts per million (v/v or m/m)
    PPMV = "ppmv"                  # Parts per million by volume
    PPMM = "ppmm"                  # Parts per million by mass
    PPM_M = "ppm·m"                # ppm × pathlength (product mode)
    PPB = "ppb"                    # Parts per billion
    MOL_L = "mol/L"                # Molarity
    MMOL_L = "mmol/L"              # Millimolar
    UMOL_L = "µmol/L"              # Micromolar
    MG_ML = "mg/mL"                # Mass concentration
    UG_ML = "µg/mL"                # Microgram per mL
    MG_L = "mg/L"                  # Milligram per liter
    PERCENT_V = "%v/v"             # Volume percent
    PERCENT_M = "%m/m"             # Mass percent
    PERCENT = "%"                  # Generic percent
    FRACTION = "fraction"          # Mole/mass fraction (0-1)
    MOLALITY = "mol/kg"            # Molality


class SourceType(str, Enum):
    """Origin of spectral data."""
    EXPERIMENT = "experiment"      # From experimental measurement
    NIST = "nist"                  # NIST Chemistry WebBook
    HITRAN = "hitran"              # HITRAN database
    EPA = "epa"                    # EPA spectral library
    PNNL = "pnnl"                  # PNNL gas-phase library
    SDBS = "sdbs"                  # SDBS (AIST Japan)
    SYNTHETIC = "synthetic"        # Generated from curve designer
    BLEND = "blend"                # Synthetic mixture
    CALIBRATION = "calibration"    # From calibration model
    SIMULATION = "simulation"      # Computational / DFT
    EIGENVECTOR = "eigenvector"    # Eigenvector Research public dataset
    UNKNOWN = "unknown"


class ModelType(str, Enum):
    """Spectral response model type for quantitation."""
    LINEAR = "linear"              # Beer-Lambert law (A = εlc)
    SATURATION = "saturation"      # Saturation model
    HYBRID = "hybrid"              # Mixed linear/saturation per wavenumber
    POLYNOMIAL = "polynomial"      # Polynomial calibration
    PLS = "pls"                    # PLS regression
    PCR = "pcr"                    # Principal Component Regression
    NONE = "none"                  # No model


class SamplingTechnique(str, Enum):
    """Spectroscopic sampling/measurement technique."""
    TRANSMISSION = "transmission"
    ATR = "atr"                    # Attenuated Total Reflectance
    REFLECTION = "reflection"      # Specular reflection
    DRIFTS = "drifts"              # Diffuse Reflectance
    TRANSFLECTION = "transflection"
    MICROSCOPY = "microscopy"      # IR/Raman microscopy
    EMISSION = "emission"
    PAS = "pas"                    # Photoacoustic
    RAIRS = "rairs"                # Reflection-Absorption
    GC_IR = "gc_ir"                # GC-IR hyphenated
    TGA_IR = "tga_ir"              # TGA-IR hyphenated
    UNKNOWN = "unknown"


class DetectorType(str, Enum):
    """Infrared detector types."""
    MCT = "mct"                    # Mercury Cadmium Telluride (cooled)
    MCT_A = "mct_a"                # MCT-A (narrow band)
    MCT_B = "mct_b"                # MCT-B (broad band)
    DTGS = "dtgs"                  # Deuterated Triglycine Sulfate
    DTGS_KBR = "dtgs_kbr"          # DTGS with KBr window
    DTGS_PE = "dtgs_pe"            # DTGS with polyethylene window
    InGaAs = "ingaas"              # Indium Gallium Arsenide (NIR)
    InSb = "insb"                  # Indium Antimonide
    PbSe = "pbse"                  # Lead Selenide
    Si = "si"                      # Silicon (NIR)
    Ge = "ge"                      # Germanium
    BOLOMETER = "bolometer"        # Far-IR
    UNKNOWN = "unknown"


class WindowMaterial(str, Enum):
    """Optical window and ATR crystal materials."""
    KBr = "kbr"                    # 40000-400 cm⁻¹
    NaCl = "nacl"                  # 40000-625 cm⁻¹
    CaF2 = "caf2"                  # 50000-1100 cm⁻¹
    BaF2 = "baf2"                  # 50000-870 cm⁻¹
    ZnSe = "znse"                  # 20000-500 cm⁻¹
    ZnS = "zns"                    # 17000-830 cm⁻¹
    DIAMOND = "diamond"            # Type IIa: 40000-10 cm⁻¹
    Ge = "ge"                      # 5500-600 cm⁻¹ (ATR)
    Si = "si"                      # 8300-660 cm⁻¹
    SAPPHIRE = "sapphire"          # 50000-1780 cm⁻¹
    KRS5 = "krs5"                  # 20000-250 cm⁻¹ (TlBr/TlI)
    AgCl = "agcl"                  # 25000-400 cm⁻¹
    POLYETHYLENE = "pe"            # Far-IR window
    UNKNOWN = "unknown"


class QualityFlag(str, Enum):
    """Data quality status flags."""
    PASS = "pass"                  # Data meets all quality criteria
    WARN = "warn"                  # Minor issues, usable with caution
    FAIL = "fail"                  # Data does not meet quality criteria
    UNCHECKED = "unchecked"        # Quality not yet assessed
    REVIEW = "review"              # Requires manual review


# =============================================================================
# CHEMICAL SPECIES INFORMATION
# =============================================================================

class SpeciesInfo(BaseModel):
    """Chemical species metadata."""
    name: str = Field(..., description="Species name (e.g., 'Carbon Dioxide')")

    # Chemical identifiers
    cas_number: Optional[str] = Field(None, description="CAS Registry Number")
    inchi: Optional[str] = Field(None, description="InChI string")
    inchi_key: Optional[str] = Field(None, description="InChI Key")
    smiles: Optional[str] = Field(None, description="SMILES notation")
    molecular_formula: Optional[str] = Field(None, description="e.g., 'CO2', 'H2O'")

    # Physical properties
    molecular_weight: Optional[float] = Field(None, description="Molecular weight (g/mol)")
    state: PhysicalState = Field(PhysicalState.UNKNOWN, description="Physical state")

    # Spectroscopic properties
    molar_absorptivity: Optional[float] = Field(
        None, description="Molar absorptivity ε at reference wavelength (L·mol⁻¹·cm⁻¹)"
    )
    molar_absorptivity_wavelength: Optional[float] = Field(
        None, description="Wavelength/wavenumber for molar absorptivity (cm⁻¹)"
    )

    # Source reference
    nist_id: Optional[str] = Field(None, description="NIST WebBook ID (e.g., 'C124389')")
    hitran_molecule_id: Optional[int] = Field(None, description="HITRAN molecule number")

    class Config:
        use_enum_values = True


# =============================================================================
# CONCENTRATION PROFILES (for blending/mixtures)
# =============================================================================

class ConcentrationProfile(BaseModel):
    """Concentration timeseries for a species in a blend."""
    species_index: int = Field(..., description="Index into species list (0-based)")
    species_name: Optional[str] = Field(None, description="Species name (for readability)")

    # Curve parameters
    curve_type: str = Field("constant", description="sigmoid, gaussian, linear, step, constant, exponential")
    values: list[float] = Field(..., description="Actual concentration values at each timepoint")

    # Curve shape parameters
    max_concentration: float = Field(..., description="Maximum concentration value")
    min_concentration: float = Field(0.0, description="Minimum concentration value")
    center: Optional[float] = Field(0.5, description="Center position (0-1) for sigmoid/gaussian")
    width: Optional[float] = Field(0.1, description="Width parameter for sigmoid/gaussian")

    # Units
    unit: ConcentrationUnit = Field(ConcentrationUnit.MOL_L, description="Concentration unit")

    class Config:
        use_enum_values = True


# =============================================================================
# INSTRUMENT INFORMATION
# =============================================================================

class InstrumentInfo(BaseModel):
    """Spectrometer hardware details for reproducibility."""

    # Instrument identity
    manufacturer: Optional[str] = Field(None, description="e.g., Bruker, Thermo, Agilent, PerkinElmer, JASCO")
    model: Optional[str] = Field(None, description="e.g., Vertex 70, Nicolet iS50, Cary 630")
    serial_number: Optional[str] = Field(None, description="Instrument serial number")
    firmware_version: Optional[str] = Field(None, description="Firmware/software version")

    # Optical components
    detector_type: Optional[DetectorType] = Field(None, description="Detector type")
    detector_cooling: Optional[str] = Field(None, description="LN2, Stirling, TEC, none")
    source_type: Optional[str] = Field(None, description="Globar, QCL, tungsten, synchrotron")
    beamsplitter: Optional[str] = Field(None, description="KBr, CaF2, Ge/KBr, Mylar")

    # Calibration
    last_calibration_date: Optional[str] = Field(None, description="ISO date of last calibration")
    calibration_certificate: Optional[str] = Field(None, description="Calibration certificate ID")

    class Config:
        use_enum_values = True


# =============================================================================
# MEASUREMENT GEOMETRY
# =============================================================================

class MeasurementGeometry(BaseModel):
    """Optical configuration and sampling geometry."""

    sampling_technique: SamplingTechnique = Field(
        SamplingTechnique.TRANSMISSION, description="Sampling technique"
    )

    # ATR-specific parameters
    atr_crystal: Optional[WindowMaterial] = Field(None, description="ATR crystal material")
    atr_angle_deg: Optional[float] = Field(None, description="Angle of incidence (degrees)")
    atr_n_bounces: Optional[int] = Field(None, description="Number of internal reflections")
    atr_dp_um: Optional[float] = Field(None, description="Penetration depth (µm) at reference wavelength")

    # Microscopy-specific
    working_distance_mm: Optional[float] = Field(None, description="Working distance (mm)")
    aperture_um: Optional[float] = Field(None, description="Aperture size (µm)")
    objective_magnification: Optional[str] = Field(None, description="e.g., '15x', '36x'")
    objective_na: Optional[float] = Field(None, description="Numerical aperture")

    # Gas cell / multipass
    optical_path_type: Optional[str] = Field(
        None, description="single_pass, White_cell, Herriott_cell, multipass"
    )
    n_passes: Optional[int] = Field(None, description="Number of passes (for multipass cells)")

    class Config:
        use_enum_values = True


# =============================================================================
# ACQUISITION PARAMETERS
# =============================================================================

class AcquisitionParams(BaseModel):
    """Data collection parameters affecting spectral quality."""

    # Scan parameters
    n_scans: Optional[int] = Field(None, description="Number of co-added scans")
    n_background_scans: Optional[int] = Field(None, description="Scans in background measurement")
    resolution_cm: Optional[float] = Field(None, description="Spectral resolution (cm⁻¹)")

    # Interferometer settings (FTIR)
    scan_velocity_khz: Optional[float] = Field(None, description="Mirror velocity (kHz)")
    apodization: Optional[str] = Field(
        None, description="Happ-Genzel, Boxcar, Blackman-Harris, Norton-Beer, triangular"
    )
    zero_fill_factor: Optional[int] = Field(None, description="Zero-fill factor (0, 1, 2, 4)")
    phase_correction: Optional[str] = Field(None, description="Mertz, Forman, stored_phase")
    phase_resolution: Optional[float] = Field(None, description="Phase resolution (cm⁻¹)")

    # Detector settings
    gain: Optional[str] = Field(None, description="Detector gain setting")
    aperture_mm: Optional[float] = Field(None, description="Aperture diameter (mm)")

    # Timing
    acquisition_datetime: Optional[str] = Field(None, description="ISO 8601 datetime")
    acquisition_duration_s: Optional[float] = Field(None, description="Total measurement time (s)")

    # Spectral range
    wavenumber_min: Optional[float] = Field(None, description="Minimum wavenumber (cm⁻¹)")
    wavenumber_max: Optional[float] = Field(None, description="Maximum wavenumber (cm⁻¹)")
    n_points: Optional[int] = Field(None, description="Number of data points")


# =============================================================================
# SAMPLE CELL / HOLDER
# =============================================================================

class SampleCell(BaseModel):
    """Sample holder/cell information."""

    cell_type: Optional[str] = Field(
        None, description="gas_cell, liquid_cell, demountable, flow_cell, cuvette, ATR"
    )
    cell_manufacturer: Optional[str] = Field(None, description="Pike, Specac, Harrick, etc.")
    cell_model: Optional[str] = Field(None, description="Cell model/part number")

    # Windows
    window_material: Optional[WindowMaterial] = Field(None, description="Window material")
    window_thickness_mm: Optional[float] = Field(None, description="Window thickness (mm)")

    # Pathlength
    pathlength_mm: Optional[float] = Field(None, description="Nominal pathlength (mm)")
    pathlength_measured_mm: Optional[float] = Field(None, description="Measured pathlength (mm)")
    spacer_thickness_um: Optional[float] = Field(None, description="Spacer thickness for liquid cells (µm)")

    # Volume
    cell_volume_ml: Optional[float] = Field(None, description="Cell volume (mL)")

    # Temperature control
    temperature_controlled: bool = Field(False, description="Has temperature control")
    temperature_range_c: Optional[tuple[float, float]] = Field(None, description="Temperature range (°C)")

    class Config:
        use_enum_values = True


# =============================================================================
# SAMPLE PREPARATION
# =============================================================================

class SamplePreparation(BaseModel):
    """How sample was prepared for measurement."""

    method: Optional[str] = Field(
        None,
        description="neat, KBr_pellet, Nujol_mull, solution, cast_film, spin_coat, ATR_contact"
    )

    # Dilution
    dilution_factor: Optional[float] = Field(None, description="Dilution factor (e.g., 10 for 1:10)")
    solvent: Optional[str] = Field(None, description="Solvent used (CCl4, CS2, CHCl3, D2O, etc.)")
    solvent_subtracted: bool = Field(False, description="Solvent spectrum subtracted")

    # Film preparation
    film_thickness_um: Optional[float] = Field(None, description="Film thickness (µm)")
    substrate: Optional[str] = Field(None, description="Substrate material")

    # Pellet preparation
    pellet_sample_mg: Optional[float] = Field(None, description="Sample amount in pellet (mg)")
    pellet_matrix_mg: Optional[float] = Field(None, description="Matrix amount (KBr, etc.) in pellet (mg)")
    pellet_diameter_mm: Optional[float] = Field(None, description="Pellet diameter (mm)")
    pellet_pressure_ton: Optional[float] = Field(None, description="Press pressure (ton)")

    # Mull preparation
    mull_agent: Optional[str] = Field(None, description="Mulling agent (Nujol, Fluorolube)")

    # Drying / conditioning
    dried: bool = Field(False, description="Sample was dried before measurement")
    drying_method: Optional[str] = Field(None, description="vacuum, N2_purge, desiccator, heat")
    conditioning_time_min: Optional[float] = Field(None, description="Conditioning time (min)")


# =============================================================================
# EXPERIMENTAL CONDITIONS
# =============================================================================

class ExperimentalConditions(BaseModel):
    """Environmental and experimental conditions during measurement."""

    # Sample conditions
    temperature_c: Optional[float] = Field(None, description="Sample temperature (°C)")
    pressure_atm: Optional[float] = Field(None, description="Sample pressure (atm)")
    pressure_mbar: Optional[float] = Field(None, description="Sample pressure (mbar)")

    # Environment
    ambient_temperature_c: Optional[float] = Field(None, description="Lab temperature (°C)")
    ambient_humidity_percent: Optional[float] = Field(None, description="Lab humidity (%RH)")

    # Purge
    purge_gas: Optional[str] = Field(None, description="N2, dry_air, Ar, none")
    purge_flow_lpm: Optional[float] = Field(None, description="Purge flow rate (L/min)")
    purge_time_min: Optional[float] = Field(None, description="Purge time before measurement (min)")

    # Atmosphere (for gas-phase)
    background_co2_ppm: Optional[float] = Field(None, description="Background CO2 level (ppm)")
    background_h2o_ppm: Optional[float] = Field(None, description="Background H2O level (ppm)")


# =============================================================================
# CALIBRATION MODEL (for quantitative analysis)
# =============================================================================

class CalibrationModel(BaseModel):
    """Calibrated model parameters for quantitative analysis."""

    model_type: ModelType = Field(ModelType.NONE, description="Calibration model type")
    concentration_mode: str = Field(
        "concentration", description="'concentration' (ppm) or 'product' (ppm·m)"
    )

    # Reference point
    reference_concentration: Optional[float] = Field(
        None, description="Reference concentration for display"
    )
    reference_pathlength_m: Optional[float] = Field(
        None, description="Reference pathlength (m)"
    )

    # Calibration range
    calibration_range_min: Optional[float] = Field(None, description="Minimum valid concentration")
    calibration_range_max: Optional[float] = Field(None, description="Maximum valid concentration")

    # Per-wavenumber model (for hybrid models)
    model_at_wavenumber: Optional[list[str]] = Field(
        None, description="Model type per wavenumber: 'linear' or 'saturation'"
    )

    # Linear model parameters (Beer-Lambert)
    slope: Optional[list[float]] = Field(None, description="Slope per wavenumber")
    intercept: Optional[list[float]] = Field(None, description="Intercept per wavenumber")

    # Saturation model parameters
    s: Optional[list[float]] = Field(None, description="Plateau level per wavenumber")
    p: Optional[list[float]] = Field(None, description="Shape exponent per wavenumber")
    c: Optional[list[float]] = Field(None, description="Sensitivity per wavenumber")

    # Calibration quality
    r_squared: Optional[float] = Field(None, description="Calibration R²")
    rmse: Optional[float] = Field(None, description="Root mean square error")
    lod: Optional[float] = Field(None, description="Limit of detection")
    loq: Optional[float] = Field(None, description="Limit of quantitation")

    # Calibration metadata
    calibration_date: Optional[str] = Field(None, description="ISO date of calibration")
    calibration_standards: Optional[list[str]] = Field(None, description="Standards used")
    n_calibration_points: Optional[int] = Field(None, description="Number of calibration points")

    class Config:
        use_enum_values = True


# =============================================================================
# QUALITY METRICS
# =============================================================================

class QualityMetrics(BaseModel):
    """Data quality indicators and flags."""

    # Signal quality
    snr: Optional[float] = Field(None, description="Signal-to-noise ratio")
    snr_method: Optional[str] = Field(None, description="Method used to calculate S/N")
    baseline_rms: Optional[float] = Field(None, description="Baseline RMS noise")
    peak_absorbance_max: Optional[float] = Field(None, description="Maximum absorbance value")

    # Interference assessment
    water_vapor_index: Optional[float] = Field(None, description="Water vapor interference level")
    co2_index: Optional[float] = Field(None, description="CO2 interference level")

    # Overall quality
    quality_flag: QualityFlag = Field(QualityFlag.UNCHECKED, description="Quality status")
    quality_notes: Optional[str] = Field(None, description="Quality assessment notes")

    # Validation
    validated: bool = Field(False, description="Data has been validated")
    validated_by: Optional[str] = Field(None, description="Validator name/ID")
    validated_datetime: Optional[str] = Field(None, description="Validation datetime")

    class Config:
        use_enum_values = True


# =============================================================================
# DATA PROVENANCE
# =============================================================================

class DataProvenance(BaseModel):
    """Track where data came from - essential for traceability."""

    source_type: SourceType = Field(..., description="Origin of spectral data")

    # Internal references
    experiment_id: Optional[int] = Field(None, description="Experiment database ID")
    file_id: Optional[int] = Field(None, description="File database ID")
    workflow_id: Optional[int] = Field(None, description="Workflow that generated this data")
    node_id: Optional[str] = Field(None, description="Node ID that generated this data")

    # File information
    original_file_path: Optional[str] = Field(None, description="Original file path")
    original_file_format: Optional[str] = Field(None, description="csv, jdx, spc, spa, opus, mat")
    original_file_hash: Optional[str] = Field(None, description="SHA-256 hash of original file")

    # External database references
    nist_id: Optional[str] = Field(None, description="NIST WebBook ID")
    hitran_molecule_id: Optional[int] = Field(None, description="HITRAN molecule number")
    epa_id: Optional[str] = Field(None, description="EPA library ID")

    # Timestamps
    created_datetime: Optional[str] = Field(None, description="When data was created/imported")
    modified_datetime: Optional[str] = Field(None, description="Last modification")

    class Config:
        use_enum_values = True


# =============================================================================
# AUDIT TRAIL (GxP Compliance)
# =============================================================================

class AuditInfo(BaseModel):
    """
    Audit trail information for GxP (GLP/GMP/GCP) compliance.

    Supports 21 CFR Part 11 requirements:
    - Attributable: Who performed the action
    - Legible: Clear documentation
    - Contemporaneous: Timestamped
    - Original: Traceable to source
    - Accurate: Verified data
    """

    # Personnel
    operator: Optional[str] = Field(None, description="Person who performed measurement")
    operator_id: Optional[str] = Field(None, description="Operator employee/user ID")
    reviewer: Optional[str] = Field(None, description="Person who reviewed data")
    reviewer_id: Optional[str] = Field(None, description="Reviewer employee/user ID")
    approver: Optional[str] = Field(None, description="Person who approved data")
    approver_id: Optional[str] = Field(None, description="Approver employee/user ID")

    # Organization
    lab_id: Optional[str] = Field(None, description="Laboratory identifier")
    lab_name: Optional[str] = Field(None, description="Laboratory name")
    department: Optional[str] = Field(None, description="Department")
    organization: Optional[str] = Field(None, description="Organization/company")

    # Project/Study
    project_id: Optional[str] = Field(None, description="Project identifier")
    project_name: Optional[str] = Field(None, description="Project name")
    study_id: Optional[str] = Field(None, description="Study identifier (for GLP)")
    study_director: Optional[str] = Field(None, description="Study director name")

    # Method reference
    sop_id: Optional[str] = Field(None, description="Standard Operating Procedure ID")
    sop_version: Optional[str] = Field(None, description="SOP version number")
    method_id: Optional[str] = Field(None, description="Analytical method ID")
    method_version: Optional[str] = Field(None, description="Method version")

    # Sample tracking
    sample_id: Optional[str] = Field(None, description="Sample identifier/barcode")
    batch_id: Optional[str] = Field(None, description="Batch/lot number")
    sequence_number: Optional[int] = Field(None, description="Position in measurement sequence")

    # Timestamps
    measurement_datetime: Optional[str] = Field(None, description="When measurement was taken")
    review_datetime: Optional[str] = Field(None, description="When data was reviewed")
    approval_datetime: Optional[str] = Field(None, description="When data was approved")

    # Electronic signatures (21 CFR Part 11)
    operator_signature: Optional[str] = Field(None, description="Electronic signature (operator)")
    reviewer_signature: Optional[str] = Field(None, description="Electronic signature (reviewer)")
    approver_signature: Optional[str] = Field(None, description="Electronic signature (approver)")

    # Comments
    measurement_notes: Optional[str] = Field(None, description="Notes from measurement")
    review_notes: Optional[str] = Field(None, description="Notes from review")
    deviations: Optional[str] = Field(None, description="Any deviations from SOP")


# =============================================================================
# MAIN SCHEMA
# =============================================================================

class SpectraMeta(BaseModel):
    """
    Comprehensive metadata schema for spectral data.

    Designed to be stored in NDDataset.meta["spectra"] as JSON.
    All fields are optional - use what you have.

    GxP-ready structure supports:
    - 21 CFR Part 11 (electronic records)
    - GLP (Good Laboratory Practice)
    - GMP (Good Manufacturing Practice)
    - ISO 17025 (laboratory accreditation)

    Example:
        >>> from spectrochempy import NDDataset
        >>> from spectra_sherpa.app.models.spectra_meta import SpectraMeta, SourceType, DataProvenance
        >>>
        >>> # Create metadata
        >>> meta = SpectraMeta(
        ...     species=[SpeciesInfo(name="CO2", cas_number="124-38-9")],
        ...     provenance=DataProvenance(source_type=SourceType.NIST)
        ... )
        >>>
        >>> # Store in NDDataset
        >>> dataset.meta["spectra"] = meta.model_dump(exclude_none=True)
    """

    # ─────────────────────────────────────────────────────────────────────────
    # Chemical Identity
    # ─────────────────────────────────────────────────────────────────────────
    species: list[SpeciesInfo] = Field(
        default_factory=list,
        description="Chemical species in the sample"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Concentration & Mixture Data (for blends / ground truth)
    # ─────────────────────────────────────────────────────────────────────────
    concentrations: Optional[list[ConcentrationProfile]] = Field(
        None, description="Concentration profiles for each species (time-resolved)"
    )
    concentration_matrix: Optional[list[list[float]]] = Field(
        None, description="C matrix (n_timepoints × n_species) - for ground truth"
    )
    pure_spectra_matrix: Optional[list[list[float]]] = Field(
        None, description="S matrix (n_wavenumbers × n_species) - for ground truth"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Instrument & Measurement
    # ─────────────────────────────────────────────────────────────────────────
    instrument: Optional[InstrumentInfo] = Field(None, description="Spectrometer details")
    geometry: Optional[MeasurementGeometry] = Field(None, description="Optical geometry")
    acquisition: Optional[AcquisitionParams] = Field(None, description="Acquisition parameters")
    cell: Optional[SampleCell] = Field(None, description="Sample cell/holder")

    # ─────────────────────────────────────────────────────────────────────────
    # Sample Details
    # ─────────────────────────────────────────────────────────────────────────
    preparation: Optional[SamplePreparation] = Field(None, description="Sample preparation")
    conditions: Optional[ExperimentalConditions] = Field(None, description="Experimental conditions")

    # ─────────────────────────────────────────────────────────────────────────
    # Quantitative Analysis
    # ─────────────────────────────────────────────────────────────────────────
    calibration: Optional[CalibrationModel] = Field(None, description="Calibration model")

    # ─────────────────────────────────────────────────────────────────────────
    # Quality & Traceability
    # ─────────────────────────────────────────────────────────────────────────
    quality: Optional[QualityMetrics] = Field(None, description="Quality metrics")
    provenance: DataProvenance = Field(..., description="Data origin and traceability")
    audit: Optional[AuditInfo] = Field(None, description="Audit trail (GxP)")

    # ─────────────────────────────────────────────────────────────────────────
    # Processing & Flags
    # ─────────────────────────────────────────────────────────────────────────
    is_ground_truth: bool = Field(
        False, description="True if concentrations/spectra are known (not recovered)"
    )
    processing_steps: list[str] = Field(
        default_factory=list,
        description="Ordered list of processing steps applied"
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Extensibility
    # ─────────────────────────────────────────────────────────────────────────
    custom: Optional[dict[str, Any]] = Field(
        None, description="Custom fields for application-specific metadata"
    )

    class Config:
        use_enum_values = True
        extra = "allow"  # Allow additional fields for forward compatibility


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_spectra_meta(dataset: Any) -> Optional[SpectraMeta]:
    """
    Extract and validate SpectraMeta from an NDDataset.

    Args:
        dataset: SpectroChemPy NDDataset with meta attribute

    Returns:
        SpectraMeta if present and valid, None otherwise
    """
    if not hasattr(dataset, "meta"):
        return None

    meta_dict = dataset.meta.get("spectra")
    if not meta_dict:
        return None

    try:
        return SpectraMeta.model_validate(meta_dict)
    except Exception:
        return None


def set_spectra_meta(dataset: Any, meta: SpectraMeta, exclude_none: bool = True) -> None:
    """
    Store SpectraMeta in an NDDataset.

    Args:
        dataset: SpectroChemPy NDDataset with meta attribute
        meta: SpectraMeta to store
        exclude_none: If True, don't store None values (saves space)
    """
    if not hasattr(dataset, "meta"):
        raise ValueError("Dataset does not have a meta attribute")

    dataset.meta["spectra"] = meta.model_dump(exclude_none=exclude_none)


def create_minimal_meta(source_type: SourceType, **kwargs) -> SpectraMeta:
    """
    Create a minimal SpectraMeta with just provenance.

    Args:
        source_type: Origin of the data
        **kwargs: Additional fields to set

    Returns:
        SpectraMeta with minimal required fields
    """
    provenance = DataProvenance(
        source_type=source_type,
        created_datetime=datetime.utcnow().isoformat()
    )
    return SpectraMeta(provenance=provenance, **kwargs)


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    "PhysicalState",
    "ConcentrationUnit",
    "SourceType",
    "ModelType",
    "SamplingTechnique",
    "DetectorType",
    "WindowMaterial",
    "QualityFlag",
    # Models
    "SpeciesInfo",
    "ConcentrationProfile",
    "InstrumentInfo",
    "MeasurementGeometry",
    "AcquisitionParams",
    "SampleCell",
    "SamplePreparation",
    "ExperimentalConditions",
    "CalibrationModel",
    "QualityMetrics",
    "DataProvenance",
    "AuditInfo",
    "SpectraMeta",
    # Functions
    "get_spectra_meta",
    "set_spectra_meta",
    "create_minimal_meta",
]
