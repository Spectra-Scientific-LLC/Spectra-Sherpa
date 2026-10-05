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
from collections.abc import Iterator
from typing import Annotated, Any, TypeVar, cast

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator
from pydantic import GetCoreSchemaHandler as _GetCoreSchemaHandler
from pydantic import GetJsonSchemaHandler as _GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue as _JsonSchemaValue
from pydantic_core import core_schema as _cs

from spectra_sherpa.app.lib.scientific_values import (
    LosslessScalar,
    lossless_json_scalar,
    lossless_scalar_identity,
)
from spectra_sherpa.core.axis_semantics import (
    AxisQuantity,
    axis_semantics,
)

MAX_AXIS_SETS_PER_KIND = 64
MAX_AXIS_SET_NAME_CHARS = 256
MAX_AXIS_TEXT_CHARS = 4096
MAX_AXIS_SET_LENGTH = 10_000_000
MAX_AXIS_TOTAL_ALIGNED_VALUES = 10_000_000
MAX_AXIS_TOTAL_TEXT_BYTES = 16 * 1024 * 1024

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


def _closed_text(value: object, *, field_name: str, max_chars: int = MAX_AXIS_TEXT_CHARS) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > max_chars:
        raise ValueError(f"{field_name} must be bounded, non-empty, and whitespace-canonical")
    return value


def _aligned_numeric_values(value: object, *, field_name: str) -> np.ndarray:
    if isinstance(value, (str, bytes)):
        raise ValueError(f"{field_name} must be a one-dimensional numeric array")
    array = np.asarray(value)
    if array.ndim != 1 or array.size > MAX_AXIS_SET_LENGTH:
        raise ValueError(f"{field_name} must be a bounded one-dimensional numeric array")
    if array.dtype.kind not in "iuf":
        raise ValueError(f"{field_name} must contain real numeric values")
    normalized = np.asarray(array, dtype=np.float64).copy()
    if not np.all(np.isfinite(normalized)):
        raise ValueError(f"{field_name} contains non-finite values")
    normalized.setflags(write=False)
    return normalized


class AxisScaleSet(BaseModel):
    """One named alternate numeric coordinate scale aligned to an axis."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    name: str
    values: NpArray
    title: str | None = None
    units: str | None = None
    axis_type: str | None = None
    source_set_index: int = Field(ge=0, strict=True)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: object) -> str:
        return _closed_text(value, field_name="axis scale-set name", max_chars=MAX_AXIS_SET_NAME_CHARS)

    @field_validator("title", "units", "axis_type")
    @classmethod
    def _validate_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        return _closed_text(value, field_name="axis scale-set text")

    @field_validator("values", mode="before")
    @classmethod
    def _validate_values(cls, value: object) -> np.ndarray:
        return _aligned_numeric_values(value, field_name="axis scale set")


class AxisLabelSet(BaseModel):
    """One named alternate text-label set aligned to an axis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    values: tuple[str, ...]
    source_set_index: int = Field(ge=0, strict=True)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: object) -> str:
        return _closed_text(value, field_name="axis label-set name", max_chars=MAX_AXIS_SET_NAME_CHARS)

    @field_validator("values", mode="before")
    @classmethod
    def _validate_values(cls, value: object) -> tuple[str, ...]:
        if isinstance(value, (str, bytes)):
            raise ValueError("axis label set must be an aligned sequence")
        try:
            values: tuple[Any, ...] = tuple(value)  # type: ignore[arg-type]
        except TypeError as exc:
            raise ValueError("axis label set must be an aligned sequence") from exc
        if len(values) > MAX_AXIS_SET_LENGTH:
            raise ValueError("axis label set exceeds the aligned-value limit")
        return tuple(_closed_text(item, field_name="axis label") for item in values)


class AxisTitleSet(BaseModel):
    """One named alternate mode title."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    title: str
    source_set_index: int = Field(ge=0, strict=True)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: object) -> str:
        return _closed_text(value, field_name="axis title-set name", max_chars=MAX_AXIS_SET_NAME_CHARS)

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: object) -> str:
        return _closed_text(value, field_name="axis title")


class AxisClassLevel(BaseModel):
    """One type-preserving class code and its display label."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: LosslessScalar
    label: str

    @field_validator("code", mode="before")
    @classmethod
    def _validate_code(cls, value: object) -> LosslessScalar:
        return lossless_json_scalar(value, max_text_chars=MAX_AXIS_TEXT_CHARS, field_name="axis class level")

    @field_validator("label")
    @classmethod
    def _validate_label(cls, value: object) -> str:
        return _closed_text(value, field_name="axis class display label")


class AxisClassSet(BaseModel):
    """One named, aligned classification scheme for an axis."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    values: tuple[LosslessScalar, ...]
    levels: tuple[AxisClassLevel, ...] = ()
    source_set_index: int = Field(ge=0, strict=True)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: object) -> str:
        return _closed_text(value, field_name="axis class-set name", max_chars=MAX_AXIS_SET_NAME_CHARS)

    @field_validator("values", mode="before")
    @classmethod
    def _validate_values(cls, value: object) -> tuple[LosslessScalar, ...]:
        if isinstance(value, (str, bytes)):
            raise ValueError("axis class set must be an aligned sequence")
        try:
            values: tuple[Any, ...] = tuple(value)  # type: ignore[arg-type]
        except TypeError as exc:
            raise ValueError("axis class set must be an aligned sequence") from exc
        if len(values) > MAX_AXIS_SET_LENGTH:
            raise ValueError("axis class set exceeds the aligned-value limit")
        return tuple(
            lossless_json_scalar(item, max_text_chars=MAX_AXIS_TEXT_CHARS, field_name="axis class set")
            for item in values
        )

    @model_validator(mode="after")
    def _validate_levels(self) -> AxisClassSet:
        level_identities = [lossless_scalar_identity(level.code) for level in self.levels]
        if len(level_identities) != len(set(level_identities)):
            raise ValueError("axis class set contains duplicate typed class levels")
        if self.levels:
            admitted = set(level_identities)
            missing = {lossless_scalar_identity(value) for value in self.values if value is not None} - admitted
            if missing:
                raise ValueError("axis class set values are absent from its class-level lookup")
        return self


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
    display_units: str | None = Field(
        None,
        description="Original source spelling retained for display when units were canonicalized",
    )
    quantity: AxisQuantity | None = Field(
        None,
        description="Canonical physical meaning of the coordinate axis; distinct from its units",
    )
    title: str | None = Field(None, description="Human-readable axis title")
    include_mask: NpArray | None = Field(
        None, description="Boolean mask indicating which positions on this dimension are included"
    )
    primary_scale_name: str | None = Field(None, description="Name of the primary values/units coordinate scale")
    alternate_scales: tuple[AxisScaleSet, ...] = Field(default_factory=tuple)
    primary_label_name: str | None = Field(None, description="Name of the primary labels projection")
    alternate_label_sets: tuple[AxisLabelSet, ...] = Field(default_factory=tuple)
    primary_title_name: str | None = Field(None, description="Name of the primary mode-title projection")
    alternate_title_sets: tuple[AxisTitleSet, ...] = Field(default_factory=tuple)
    class_sets: tuple[AxisClassSet, ...] = Field(default_factory=tuple)
    primary_class_set_name: str | None = Field(None, description="Selected compatibility class-set name")
    _expected_length: int | None = PrivateAttr(default=None)

    @field_validator(
        "primary_scale_name",
        "primary_label_name",
        "primary_title_name",
        "primary_class_set_name",
    )
    @classmethod
    def _validate_primary_name(cls, value: object) -> str | None:
        if value is None:
            return None
        return _closed_text(value, field_name="primary axis-set name", max_chars=MAX_AXIS_SET_NAME_CHARS)

    @field_validator("units", "display_units", "title")
    @classmethod
    def _validate_axis_text(cls, value: object) -> str | None:
        if value is None:
            return None
        return _closed_text(value, field_name="axis text")

    @field_validator("include_mask", mode="before")
    @classmethod
    def _validate_include_mask_type(cls, value: object) -> np.ndarray | None:
        if value is None:
            return None
        array = np.asarray(value)
        if array.ndim != 1 or array.size > MAX_AXIS_SET_LENGTH or array.dtype.kind != "b":
            raise ValueError("axis include_mask must be a bounded one-dimensional boolean array")
        return array.astype(bool, copy=True)

    @property
    def data(self) -> np.ndarray | None:
        """Alias for values — Coord compatibility."""
        return self.values

    @property
    def length(self) -> int:
        if self._expected_length is not None:
            return self._expected_length
        if self.values is not None:
            return len(self.values)
        if self.labels is not None:
            return len(self.labels)
        if self.include_mask is not None:
            return len(self.include_mask)
        if self.alternate_scales:
            return len(self.alternate_scales[0].values)
        if self.alternate_label_sets:
            return len(self.alternate_label_sets[0].values)
        if self.class_sets:
            return len(self.class_sets[0].values)
        return 0

    @property
    def shape(self) -> tuple:
        return self.values.shape if self.values is not None else ()

    def __len__(self) -> int:
        return self.length

    def copy(self) -> AxisInfo:
        return copy.deepcopy(self)

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
        expected = self._expected_length
        if expected is None:
            expected = value_len if value_len is not None else label_len
        aligned_lengths: list[tuple[str, int]] = []
        if self.include_mask is not None:
            aligned_lengths.append(("include_mask", len(self.include_mask)))
        aligned_lengths.extend((f"alternate_scales[{item.name}]", len(item.values)) for item in self.alternate_scales)
        aligned_lengths.extend(
            (f"alternate_label_sets[{item.name}]", len(item.values)) for item in self.alternate_label_sets
        )
        aligned_lengths.extend((f"class_sets[{item.name}]", len(item.values)) for item in self.class_sets)
        if expected is None and aligned_lengths:
            expected = aligned_lengths[0][1]
        if expected is not None:
            for field_name, actual in aligned_lengths:
                if actual != expected:
                    raise ValueError(f"{field_name} length ({actual}) != expected length ({expected})")

        collections: tuple[tuple[str, tuple[Any, ...], str | None], ...] = (
            ("alternate scale", self.alternate_scales, self.primary_scale_name),
            ("alternate label", self.alternate_label_sets, self.primary_label_name),
            ("alternate title", self.alternate_title_sets, self.primary_title_name),
            ("class", self.class_sets, None),
        )
        for kind, items, primary_name in collections:
            if len(items) > MAX_AXIS_SETS_PER_KIND:
                raise ValueError(f"axis exceeds the {MAX_AXIS_SETS_PER_KIND} {kind}-set limit")
            names = [item.name for item in items]
            indices = [item.source_set_index for item in items]
            if len(names) != len(set(names)) or len(indices) != len(set(indices)):
                raise ValueError(f"axis contains duplicate {kind}-set identities")
            if primary_name is not None and primary_name in names:
                raise ValueError(f"axis {kind} sets duplicate the primary projection")
        if self.primary_class_set_name is not None and self.primary_class_set_name not in {
            item.name for item in self.class_sets
        }:
            raise ValueError("primary_class_set_name does not identify an admitted class set")
        aligned_values = sum(
            len(values)
            for values in (
                self.values if self.values is not None else (),
                self.labels or (),
                self.include_mask if self.include_mask is not None else (),
                *(item.values for item in self.alternate_scales),
                *(item.values for item in self.alternate_label_sets),
                *(item.values for item in self.class_sets),
            )
        )
        if aligned_values > MAX_AXIS_TOTAL_ALIGNED_VALUES:
            raise ValueError("axis aligned metadata exceeds the aggregate value limit")

        def text_values() -> Iterator[str | None]:
            yield self.units
            yield self.display_units
            yield self.title
            yield self.primary_scale_name
            yield self.primary_label_name
            yield self.primary_title_name
            yield self.primary_class_set_name
            for scale in self.alternate_scales:
                yield scale.name
                yield scale.title
                yield scale.units
                yield scale.axis_type
            for label_set in self.alternate_label_sets:
                yield label_set.name
                yield from label_set.values
            for title_set in self.alternate_title_sets:
                yield title_set.name
                yield title_set.title
            for class_set in self.class_sets:
                yield class_set.name
                yield from (level.label for level in class_set.levels)
                yield from (value for value in class_set.values if isinstance(value, str))

        text_bytes = sum(len(value.encode("utf-8")) for value in text_values() if isinstance(value, str))
        if text_bytes > MAX_AXIS_TOTAL_TEXT_BYTES:
            raise ValueError("axis aligned metadata exceeds the aggregate text limit")
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
    - Feature selection state (include_mask, scores, method provenance)
    """

    # --- Feature selection contract ---
    # Mirrors SampleAxis.include_mask for the feature dimension.
    selection_scores: NpArray | None = Field(
        None, description="Importance scores from variable selection (e.g. VIP, selectivity ratio)"
    )
    selection_method: str | None = Field(
        None, description="Provenance: method that produced the mask (e.g. 'vip', 'ipls', 'manual')"
    )

    @model_validator(mode="after")
    def _validate_feature_selection_fields(self) -> FeatureAxis:
        n = self._expected_length if self._expected_length is not None else self.length
        if self.include_mask is not None and n > 0 and len(self.include_mask) != n:
            raise ValueError(f"include_mask length ({len(self.include_mask)}) != expected length ({n})")
        if self.selection_scores is not None and n > 0 and len(self.selection_scores) != n:
            raise ValueError(f"selection_scores length ({len(self.selection_scores)}) != expected length ({n})")
        return self

    @property
    def n_selected(self) -> int:
        """Number of features currently selected (all if no mask)."""
        if self.include_mask is None:
            return self.length
        return int(np.sum(self.include_mask))

    def exclude_feature(self, i: int) -> None:
        """Mark feature *i* as excluded."""
        n = self._expected_length if self._expected_length is not None else self.length
        if self.include_mask is None:
            self.include_mask = np.ones(n, dtype=bool)
        self.include_mask[i] = False

    def include_feature(self, i: int) -> None:
        """Mark feature *i* as included."""
        if self.include_mask is None:
            return  # all already included
        self.include_mask[i] = True

    def apply_mask(self, mask: np.ndarray, method: str | None = None, scores: np.ndarray | None = None) -> None:
        """Set the feature selection mask with provenance.

        Args:
            mask: Boolean array (True = keep). Must match axis length.
            method: Name of the selection algorithm (e.g. 'vip', 'interval').
            scores: Optional importance scores aligned with the axis.
        """
        self.include_mask = np.asarray(mask, dtype=bool)
        if method is not None:
            self.selection_method = method
        if scores is not None:
            self.selection_scores = np.asarray(scores, dtype=np.float64)

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
        return copy.deepcopy(self)

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


class SpectralAxis(FeatureAxis):
    """Spectral axis for spectroscopy (wavelength/wavenumber).

    Supports:
    - Wavenumber (cm⁻¹) for IR, NIR, Raman
    - Wavelength (nm) for UV-Vis, fluorescence
    - Wavelength (µm) for mid-IR
    """

    @property
    def axis_type(self) -> str | None:
        """Return quantity-aware spectral type; Raman shift is not wavenumber."""
        semantics = axis_semantics(
            axis_class=type(self).__name__,
            title=self.title,
            units=self.units,
            quantity=self.quantity,
        )
        if semantics.quantity is AxisQuantity.RAMAN_SHIFT:
            return "raman_shift"
        if semantics.quantity is AxisQuantity.WAVENUMBER:
            return "wavenumber"
        if semantics.quantity is AxisQuantity.WAVELENGTH and semantics.units == "nm":
            return "wavelength_nm"
        if semantics.quantity is AxisQuantity.WAVELENGTH and semantics.units == "µm":
            return "wavelength_um"
        return None

    def copy(self) -> SpectralAxis:
        return copy.deepcopy(self)


def canonicalize_feature_axis(axis: FeatureAxis) -> FeatureAxis:
    """Return a reader-boundary axis with canonical units and quantity.

    The source spelling remains in ``display_units`` whenever normalization
    changes it.  This makes scientific comparisons use one vocabulary without
    erasing what the instrument or interchange file actually said.
    """

    semantics = axis_semantics(
        axis_class=type(axis).__name__,
        title=axis.title,
        units=axis.units,
        quantity=axis.quantity,
    )
    display_units = axis.display_units
    if display_units is None and axis.units is not None and axis.units != semantics.units:
        display_units = axis.units
    payload = axis.model_dump(mode="python")
    payload.update(
        {
            "units": semantics.units,
            "display_units": display_units,
            "quantity": semantics.quantity,
        }
    )
    return type(axis).model_validate(payload)


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
        return copy.deepcopy(self)


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
        return copy.deepcopy(self)


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
        return copy.deepcopy(self)


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
        return copy.deepcopy(self)


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
        return copy.deepcopy(self)


# ═══════════════════════════════════════════════════════════════════════════
# Sample Axis (observation/row axis)
# ═══════════════════════════════════════════════════════════════════════════


class SampleAxis(AxisInfo):
    """Sample axis with per-sample metadata."""

    classes: NpArray | None = Field(None, description="Class assignments for each sample (classification tasks)")
    exclusion_reasons: list[str | None] | None = Field(
        None, description="Reason for exclusion for each excluded sample"
    )
    sample_table: dict[str, list[Any]] | None = Field(
        None, description="Tabular metadata (arbitrary columns) for samples"
    )

    @model_validator(mode="before")
    @classmethod
    def _project_primary_class_set(cls, value: Any) -> Any:
        if not isinstance(value, dict) or value.get("classes") is not None:
            return value
        primary_name = value.get("primary_class_set_name")
        if primary_name is None:
            return value
        for item in value.get("class_sets") or ():
            if isinstance(item, AxisClassSet):
                name = item.name
                values = item.values
            elif isinstance(item, dict):
                name = item.get("name")
                values = item.get("values")
            else:
                continue
            if name == primary_name:
                if isinstance(values, (str, bytes)) or values is None:
                    return value
                projected = dict(value)
                projected["classes"] = np.asarray(tuple(values), dtype=object)
                return projected
        return value

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
        if self.classes is not None and self.primary_class_set_name is not None:
            primary = next(item for item in self.class_sets if item.name == self.primary_class_set_name)
            compatibility = tuple(
                lossless_json_scalar(item, max_text_chars=MAX_AXIS_TEXT_CHARS, field_name="sample classes")
                for item in self.classes.tolist()
            )
            if tuple(map(lossless_scalar_identity, compatibility)) != tuple(
                map(lossless_scalar_identity, primary.values)
            ):
                raise ValueError("SampleAxis.classes contradicts the selected primary class set")
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
        return copy.deepcopy(self)


AxisT = TypeVar("AxisT", bound=AxisInfo)


def revalidated_axis_copy(axis: AxisT) -> AxisT:
    """Re-admit an axis and every nested set before crossing a data boundary."""

    if not isinstance(axis, AxisInfo):
        raise TypeError("axis must be an AxisInfo instance")
    return cast(AxisT, type(axis).model_validate(axis.model_dump(mode="python")))
