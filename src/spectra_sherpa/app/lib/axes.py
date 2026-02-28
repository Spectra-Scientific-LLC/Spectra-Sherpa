"""
Axis classes for SherpaDataset — generalized for all analytical chemistry domains.

This module provides a hierarchy of axis types:
- AxisInfo: Base class for all axes
- FeatureAxis: Base for feature-type axes (spectral, time, m/z, potential, etc.)
  - SpectralAxis: Wavelength/wavenumber (spectroscopy)
  - TimeAxis: Retention/elution time (chromatography, kinetics)
  - MZAxis: Mass-to-charge ratio (mass spectrometry)
  - PotentialAxis: Voltage (electrochemistry)
  - FrequencyAxis: Frequency (NMR, dielectric spectroscopy)
  - SpatialAxis: Spatial coordinates (imaging, hyperspectral)
- SampleAxis: Sample/observation axis with metadata
"""

from __future__ import annotations

import copy
from typing import Annotated, Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator
from pydantic import GetCoreSchemaHandler as _GetCoreSchemaHandler
from pydantic import GetJsonSchemaHandler as _GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue as _JsonSchemaValue
from pydantic_core import core_schema as _cs

# ═══════════════════════════════════════════════════════════════════════════
# Pydantic-compatible numpy array type
# ═══════════════════════════════════════════════════════════════════════════


class _NpArrayPydanticAnnotation:
    """Pydantic annotation for np.ndarray that provides JSON schema.

    At runtime: accepts np.ndarray as-is.
    For JSON schema: emits ``{"type": "array", "items": {"type": "number"}}``.
    """

    @classmethod
    def __get_pydantic_core_schema__(cls, _source_type: Any, _handler: _GetCoreSchemaHandler) -> _cs.CoreSchema:
        return _cs.no_info_plain_validator_function(
            cls._validate,
            serialization=_cs.plain_serializer_function_ser_schema(cls._serialize, info_arg=False),
        )

    @classmethod
    def __get_pydantic_json_schema__(cls, _schema: _cs.CoreSchema, handler: _GetJsonSchemaHandler) -> _JsonSchemaValue:
        return {"type": "array", "items": {"type": "number"}}

    @staticmethod
    def _validate(v: Any) -> np.ndarray:
        if isinstance(v, np.ndarray):
            return v
        if isinstance(v, (str, bytes)):
            raise ValueError(f"Expected array-like, got {type(v).__name__}")
        try:
            return np.asarray(v)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Cannot convert {type(v).__name__} to numpy array: {e}") from e

    @staticmethod
    def _serialize(v: Any) -> Any:
        if isinstance(v, np.ndarray):
            return v.tolist()
        return v


NpArray = Annotated[np.ndarray, _NpArrayPydanticAnnotation]
"""Numpy array type that is JSON-schema compatible for Pydantic models."""


# ═══════════════════════════════════════════════════════════════════════════
# Base Axis Class
# ═══════════════════════════════════════════════════════════════════════════


class AxisInfo(BaseModel):
    """Base axis metadata (Pydantic-validated)."""

    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    values: NpArray | None = Field(
        None, description="Axis coordinate values (e.g., wavelengths, retention times, m/z values)"
    )
    labels: list[str] | None = Field(None, description="Optional text labels for axis points")
    units: str | None = Field(None, description="Physical units (e.g., 'cm-1', 'nm', 'min', 'm/z', 'V')")
    title: str | None = Field(None, description="Human-readable axis title")
    _expected_length: int | None = PrivateAttr(default=None)

    @property
    def data(self) -> np.ndarray | None:
        """Alias for values — Coord compatibility."""
        return self.values

    @property
    def length(self) -> int:
        if self.values is not None:
            return len(self.values)
        if self.labels is not None:
            return len(self.labels)
        return 0

    @property
    def shape(self) -> tuple:
        return self.values.shape if self.values is not None else ()

    def __len__(self) -> int:
        return self.length

    def copy(self) -> AxisInfo:
        cp = AxisInfo(
            values=self.values.copy() if self.values is not None else None,
            labels=list(self.labels) if self.labels is not None else None,
            units=self.units,
            title=self.title,
        )
        if self._expected_length is not None:
            cp.bind_expected_length(self._expected_length)
        return cp

    def bind_expected_length(self, expected: int) -> None:
        """Attach axis length constraint used for runtime assignment checks."""
        self._expected_length = int(expected)
        # Re-run validation now so existing inconsistent axes fail fast.
        self._validate_axis_lengths()

    @model_validator(mode="after")
    def _validate_axis_lengths(self) -> AxisInfo:
        value_len = len(self.values) if self.values is not None else None
        label_len = len(self.labels) if self.labels is not None else None
        if value_len is not None and label_len is not None and value_len != label_len:
            raise ValueError(f"Axis values length ({value_len}) != labels length ({label_len})")
        if self._expected_length is not None:
            if value_len is not None and value_len != self._expected_length:
                raise ValueError(f"Axis values length ({value_len}) != expected length ({self._expected_length})")
            if label_len is not None and label_len != self._expected_length:
                raise ValueError(f"Axis labels length ({label_len}) != expected length ({self._expected_length})")
        return self

    # ═══════════════════════════════════════════════════════════════════════════
    # Convenience Methods (reduce boilerplate in node code)
    # ═══════════════════════════════════════════════════════════════════════════

    def is_empty(self) -> bool:
        """True if axis has no values and no labels.

        Example:
            >>> axis = AxisInfo()
            >>> axis.is_empty()  # True
            >>> axis = AxisInfo(values=np.array([1, 2, 3]))
            >>> axis.is_empty()  # False
        """
        return self.values is None and self.labels is None

    def n_points(self) -> int:
        """Number of axis points (0 if empty).

        This is a convenience alias for `length` property, but as a method
        it's more discoverable and matches common usage patterns.

        Example:
            >>> axis = AxisInfo(values=np.linspace(400, 4000, 1000))
            >>> axis.n_points()  # 1000
            >>> empty_axis = AxisInfo()
            >>> empty_axis.n_points()  # 0
        """
        return self.length

    def has_units(self) -> bool:
        """True if units are defined and non-empty.

        Example:
            >>> axis = AxisInfo(values=np.array([1, 2, 3]), units="cm-1")
            >>> axis.has_units()  # True
            >>> axis = AxisInfo(values=np.array([1, 2, 3]))
            >>> axis.has_units()  # False
        """
        return self.units is not None and self.units != ""


# ═══════════════════════════════════════════════════════════════════════════
# Feature Axis Base Class (for all feature-type axes)
# ═══════════════════════════════════════════════════════════════════════════


class FeatureAxis(AxisInfo):
    """Base class for feature-type axes (spectral, time, m/z, potential, etc.).

    All feature axes share common functionality:
    - Unit detection and type inference
    - Range queries
    - Region selection
    """

    @property
    def axis_type(self) -> str | None:
        """Detect axis type from units. Override in subclasses."""
        return None

    @property
    def range(self) -> tuple[float, float] | None:
        """(min, max) of axis values."""
        if self.values is None or len(self.values) == 0:
            return None
        return (float(np.min(self.values)), float(np.max(self.values)))

    def copy(self) -> FeatureAxis:
        cp = FeatureAxis(
            values=self.values.copy() if self.values is not None else None,
            labels=list(self.labels) if self.labels is not None else None,
            units=self.units,
            title=self.title,
        )
        if self._expected_length is not None:
            cp.bind_expected_length(self._expected_length)
        return cp

    def select_region(self, start: float, end: float) -> np.ndarray:
        """Boolean mask for values within [start, end] (inclusive, order-independent)."""
        if self.values is None:
            raise ValueError("Cannot select region on axis with no values")
        lo, hi = min(start, end), max(start, end)
        return (self.values >= lo) & (self.values <= hi)

    # ═══════════════════════════════════════════════════════════════════════════
    # Additional Convenience Methods for FeatureAxis
    # ═══════════════════════════════════════════════════════════════════════════

    def is_monotonic(self, increasing: bool = True) -> bool:
        """Check if axis values are monotonically increasing or decreasing.

        Args:
            increasing: If True, check for monotonic increase. If False, check for decrease.

        Returns:
            True if values are monotonic in the specified direction, False otherwise.

        Example:
            >>> axis = FeatureAxis(values=np.array([1, 2, 3, 4, 5]))
            >>> axis.is_monotonic(increasing=True)  # True
            >>> axis.is_monotonic(increasing=False)  # False
            >>> axis = FeatureAxis(values=np.array([5, 4, 3, 2, 1]))
            >>> axis.is_monotonic(increasing=False)  # True
        """
        if self.values is None or len(self.values) < 2:
            return True  # Empty or single-value axis is trivially monotonic

        diffs = np.diff(self.values)
        if increasing:
            return bool(np.all(diffs > 0))
        else:
            return bool(np.all(diffs < 0))

    def get_region_indices(self, start: float, end: float) -> np.ndarray:
        """Get indices (not boolean mask) for values in region [start, end].

        This is a convenience wrapper around select_region() that returns indices
        instead of a boolean mask, reducing boilerplate like `np.where(mask)[0]`.

        Args:
            start: Start of region (inclusive)
            end: End of region (inclusive)

        Returns:
            Array of integer indices where values fall within [start, end]

        Example:
            >>> axis = FeatureAxis(values=np.linspace(400, 4000, 1000))
            >>> indices = axis.get_region_indices(2800, 3000)  # C-H stretch region
            >>> len(indices)  # ~56 indices in that range
            >>> # OLD WAY (boilerplate):
            >>> mask = axis.select_region(2800, 3000)
            >>> indices = np.where(mask)[0]
            >>> # NEW WAY (one line):
            >>> indices = axis.get_region_indices(2800, 3000)
        """
        mask = self.select_region(start, end)
        return np.where(mask)[0]


# ═══════════════════════════════════════════════════════════════════════════
# Specialized Feature Axis Classes
# ═══════════════════════════════════════════════════════════════════════════


# Spectroscopy unit sets for axis_type detection
_WAVENUMBER_UNITS = frozenset({"cm-1", "cm⁻¹", "1/cm", "cm^-1"})
_WAVELENGTH_NM_UNITS = frozenset({"nm", "nanometer", "nanometers"})
_WAVELENGTH_UM_UNITS = frozenset({"um", "µm", "\u03bcm", "micron", "microns", "micrometer", "micrometers"})


class SpectralAxis(FeatureAxis):
    """Spectral axis for spectroscopy (wavelength/wavenumber).

    Supports:
    - Wavenumber (cm⁻¹) for IR, NIR, Raman
    - Wavelength (nm) for UV-Vis, fluorescence
    - Wavelength (µm) for mid-IR
    """

    @property
    def axis_type(self) -> str | None:
        """Detect: 'wavenumber', 'wavelength_nm', 'wavelength_um', or None."""
        if self.units is None:
            return None
        u = self.units.lower().strip()
        if u in _WAVENUMBER_UNITS:
            return "wavenumber"
        if u in _WAVELENGTH_NM_UNITS:
            return "wavelength_nm"
        if u in _WAVELENGTH_UM_UNITS:
            return "wavelength_um"
        return None

    def copy(self) -> SpectralAxis:
        cp = SpectralAxis(
            values=self.values.copy() if self.values is not None else None,
            labels=list(self.labels) if self.labels is not None else None,
            units=self.units,
            title=self.title,
        )
        if self._expected_length is not None:
            cp.bind_expected_length(self._expected_length)
        return cp


# Chromatography unit sets
_TIME_MINUTES_UNITS = frozenset({"min", "minute", "minutes"})
_TIME_SECONDS_UNITS = frozenset({"s", "sec", "second", "seconds"})
_TIME_MILLISECONDS_UNITS = frozenset({"ms", "millisecond", "milliseconds"})
_TIME_HOURS_UNITS = frozenset({"h", "hr", "hour", "hours"})


class TimeAxis(FeatureAxis):
    """Time axis for chromatography and kinetics.

    Supports:
    - Retention time (HPLC, GC, IC, CE)
    - Elution time
    - Process time (reaction kinetics, online monitoring)
    """

    @property
    def axis_type(self) -> str | None:
        """Detect: 'retention_time', 'elution_time', 'process_time', or None."""
        if self.units is None:
            return None
        u = self.units.lower().strip()
        # All time units map to generic "time" type
        # Specific technique inference happens at domain level
        if u in _TIME_MINUTES_UNITS:
            return "time_minutes"
        if u in _TIME_SECONDS_UNITS:
            return "time_seconds"
        if u in _TIME_MILLISECONDS_UNITS:
            return "time_milliseconds"
        if u in _TIME_HOURS_UNITS:
            return "time_hours"
        return None

    def copy(self) -> TimeAxis:
        cp = TimeAxis(
            values=self.values.copy() if self.values is not None else None,
            labels=list(self.labels) if self.labels is not None else None,
            units=self.units,
            title=self.title,
        )
        if self._expected_length is not None:
            cp.bind_expected_length(self._expected_length)
        return cp


# Mass spectrometry unit sets
_MZ_UNITS = frozenset({"m/z", "mz", "da", "amu", "dalton", "daltons"})


class MZAxis(FeatureAxis):
    """Mass-to-charge ratio axis for mass spectrometry.

    Supports:
    - LC-MS, GC-MS
    - MALDI-TOF
    - ICP-MS
    - ESI-MS
    """

    @property
    def axis_type(self) -> str | None:
        """Detect: 'mass_to_charge' or None."""
        if self.units is None:
            return None
        u = self.units.lower().strip().replace(" ", "")
        if u in _MZ_UNITS:
            return "mass_to_charge"
        return None

    def copy(self) -> MZAxis:
        cp = MZAxis(
            values=self.values.copy() if self.values is not None else None,
            labels=list(self.labels) if self.labels is not None else None,
            units=self.units,
            title=self.title,
        )
        if self._expected_length is not None:
            cp.bind_expected_length(self._expected_length)
        return cp


# Electrochemistry unit sets
_VOLTAGE_VOLTS_UNITS = frozenset({"v", "volt", "volts"})
_VOLTAGE_MILLIVOLTS_UNITS = frozenset({"mv", "millivolt", "millivolts"})


class PotentialAxis(FeatureAxis):
    """Voltage/potential axis for electrochemistry.

    Supports:
    - Cyclic voltammetry (CV)
    - Differential pulse voltammetry (DPV)
    - Square wave voltammetry (SWV)
    - Linear sweep voltammetry (LSV)
    - Chronoamperometry (CA)
    """

    @property
    def axis_type(self) -> str | None:
        """Detect: 'voltage_volts', 'voltage_millivolts', or None."""
        if self.units is None:
            return None
        u = self.units.lower().strip()
        if u in _VOLTAGE_VOLTS_UNITS:
            return "voltage_volts"
        if u in _VOLTAGE_MILLIVOLTS_UNITS:
            return "voltage_millivolts"
        return None

    def copy(self) -> PotentialAxis:
        cp = PotentialAxis(
            values=self.values.copy() if self.values is not None else None,
            labels=list(self.labels) if self.labels is not None else None,
            units=self.units,
            title=self.title,
        )
        if self._expected_length is not None:
            cp.bind_expected_length(self._expected_length)
        return cp


# NMR / dielectric spectroscopy unit sets
_FREQUENCY_HZ_UNITS = frozenset({"hz", "hertz"})
_FREQUENCY_MHZ_UNITS = frozenset({"mhz", "megahertz"})
_FREQUENCY_GHZ_UNITS = frozenset({"ghz", "gigahertz"})


class FrequencyAxis(FeatureAxis):
    """Frequency axis for NMR and dielectric spectroscopy.

    Supports:
    - NMR spectroscopy
    - Dielectric spectroscopy
    - Impedance spectroscopy (EIS)
    """

    @property
    def axis_type(self) -> str | None:
        """Detect: 'frequency_hz', 'frequency_mhz', 'frequency_ghz', or None."""
        if self.units is None:
            return None
        u = self.units.lower().strip()
        if u in _FREQUENCY_HZ_UNITS:
            return "frequency_hz"
        if u in _FREQUENCY_MHZ_UNITS:
            return "frequency_mhz"
        if u in _FREQUENCY_GHZ_UNITS:
            return "frequency_ghz"
        return None

    def copy(self) -> FrequencyAxis:
        cp = FrequencyAxis(
            values=self.values.copy() if self.values is not None else None,
            labels=list(self.labels) if self.labels is not None else None,
            units=self.units,
            title=self.title,
        )
        if self._expected_length is not None:
            cp.bind_expected_length(self._expected_length)
        return cp


# ═══════════════════════════════════════════════════════════════════════════
# Spatial Axis (inner dimensions for imaging data)
# ═══════════════════════════════════════════════════════════════════════════

# Spatial unit sets
_SPATIAL_UM_UNITS = frozenset({"um", "µm", "\u03bcm", "micron", "microns", "micrometer"})
_SPATIAL_MM_UNITS = frozenset({"mm", "millimeter", "millimeters"})
_SPATIAL_CM_UNITS = frozenset({"cm", "centimeter", "centimeters"})
_SPATIAL_PIXEL_UNITS = frozenset({"px", "pixel", "pixels"})


class SpatialAxis(FeatureAxis):
    """Spatial coordinate axis for imaging data.

    Used for inner dimensions of hyperspectral images and spatial maps:
    - X/Y pixel coordinates in imaging spectroscopy
    - Physical spatial coordinates in microscopy (µm, mm)

    This axis type is intended for inner dimensions (not feature or sample).
    The feature dimension still uses SpectralAxis, MZAxis, etc.

    Supported units:
    - Micrometers: um, µm, micron, microns, micrometer
    - Millimeters: mm, millimeter, millimeters
    - Centimeters: cm, centimeter, centimeters
    - Pixels: px, pixel, pixels
    """

    @property
    def axis_type(self) -> str | None:
        """Detect: 'spatial_um', 'spatial_mm', 'spatial_cm', 'spatial_pixel', or None."""
        if self.units is None:
            return None
        u = self.units.lower().strip()
        if u in _SPATIAL_UM_UNITS:
            return "spatial_um"
        if u in _SPATIAL_MM_UNITS:
            return "spatial_mm"
        if u in _SPATIAL_CM_UNITS:
            return "spatial_cm"
        if u in _SPATIAL_PIXEL_UNITS:
            return "spatial_pixel"
        return None

    def copy(self) -> SpatialAxis:
        cp = SpatialAxis(
            values=self.values.copy() if self.values is not None else None,
            labels=list(self.labels) if self.labels is not None else None,
            units=self.units,
            title=self.title,
        )
        if self._expected_length is not None:
            cp.bind_expected_length(self._expected_length)
        return cp


# ═══════════════════════════════════════════════════════════════════════════
# Sample Axis (observation/row axis)
# ═══════════════════════════════════════════════════════════════════════════


class SampleAxis(AxisInfo):
    """Sample axis with per-sample metadata."""

    classes: NpArray | None = Field(None, description="Class assignments for each sample (classification tasks)")
    include_mask: NpArray | None = Field(
        None, description="Boolean mask indicating which samples are included (soft delete)"
    )
    exclusion_reasons: list[str | None] | None = Field(
        None, description="Reason for exclusion for each excluded sample"
    )
    sample_table: dict[str, list[Any]] | None = Field(
        None, description="Tabular metadata (arbitrary columns) for samples"
    )

    @model_validator(mode="after")
    def _validate_sample_fields(self) -> SampleAxis:
        # Prefer bound expected length when attached to a dataset.
        n = self._expected_length if self._expected_length is not None else self.length
        if self.classes is not None and n > 0 and len(self.classes) != n:
            raise ValueError(f"classes length ({len(self.classes)}) != expected length ({n})")
        if self.include_mask is not None and n > 0 and len(self.include_mask) != n:
            raise ValueError(f"include_mask length ({len(self.include_mask)}) != expected length ({n})")
        if self.exclusion_reasons is not None and n > 0 and len(self.exclusion_reasons) != n:
            raise ValueError(f"exclusion_reasons length ({len(self.exclusion_reasons)}) != expected length ({n})")
        if self.sample_table is not None and n > 0:
            for key, values in self.sample_table.items():
                if len(values) != n:
                    raise ValueError(f"sample_table[{key!r}] length ({len(values)}) != expected length ({n})")
        return self

    @property
    def n_included(self) -> int:
        if self.include_mask is None:
            return self.length
        return int(np.sum(self.include_mask))

    def exclude(self, indices: list[int], reason: str = "") -> None:
        """Mark samples as excluded (soft delete)."""
        n = self.length
        if n == 0:
            raise ValueError("Cannot exclude from empty axis")
        if self.include_mask is None:
            self.include_mask = np.ones(n, dtype=bool)
        if self.exclusion_reasons is None:
            self.exclusion_reasons = [None] * n
        for i in indices:
            if i < 0 or i >= n:
                raise IndexError(f"Sample index {i} out of range [0, {n})")
            self.include_mask[i] = False
            self.exclusion_reasons[i] = reason

    def include(self, indices: list[int]) -> None:
        """Mark samples as included."""
        if self.include_mask is None:
            return
        n = self.length
        for i in indices:
            if i < 0 or i >= n:
                raise IndexError(f"Sample index {i} out of range [0, {n})")
            self.include_mask[i] = True
            if self.exclusion_reasons:
                self.exclusion_reasons[i] = None

    def get_column(self, name: str) -> list[Any] | None:
        if self.sample_table is None:
            return None
        return self.sample_table.get(name)

    def set_column(self, name: str, values: list[Any]) -> None:
        if self.length > 0 and len(values) != self.length:
            raise ValueError(f"Column '{name}' length ({len(values)}) != sample axis length ({self.length})")
        if self.sample_table is None:
            self.sample_table = {}
        self.sample_table[name] = values

    def copy(self) -> SampleAxis:
        cp = SampleAxis(
            values=self.values.copy() if self.values is not None else None,
            labels=list(self.labels) if self.labels is not None else None,
            units=self.units,
            title=self.title,
            classes=self.classes.copy() if self.classes is not None else None,
            include_mask=self.include_mask.copy() if self.include_mask is not None else None,
            exclusion_reasons=list(self.exclusion_reasons) if self.exclusion_reasons else None,
            sample_table=copy.deepcopy(self.sample_table) if self.sample_table else None,
        )
        if self._expected_length is not None:
            cp.bind_expected_length(self._expected_length)
        return cp
