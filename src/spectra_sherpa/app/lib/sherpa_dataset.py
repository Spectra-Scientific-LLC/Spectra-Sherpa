"""
SherpaDataset — AI-native spectral dataset.

Replaces AnalysisDataset with:
- Pydantic-validated typed fields (no untyped meta bag)
- First-class Provenance (no fragile identity sync)
- Domain-aware axes (SpectralAxis, SampleAxis)
- Quality metrics scoped per evaluation
- Artifact handles for MCP (dataset_id + manifest)
- Equality modes + fingerprinting for testing

Core module is dependency-neutral: no imports from scp_compat, sklearn,
or any external spectral library. All conversions live in adapters/.
"""

from __future__ import annotations

import copy
import hashlib
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any

from typing import Annotated

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator
from pydantic import GetCoreSchemaHandler as _GetCoreSchemaHandler
from pydantic import GetJsonSchemaHandler as _GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue as _JsonSchemaValue
from pydantic_core import core_schema as _cs

# ---------------------------------------------------------------------------
# Pydantic-compatible numpy array type for JSON schema generation
# ---------------------------------------------------------------------------


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


class FrozenDict(dict):
    """Dict variant that forbids in-place mutation."""

    def _readonly(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("FrozenDict is immutable")

    __setitem__ = _readonly  # type: ignore[assignment]
    __delitem__ = _readonly  # type: ignore[assignment]
    clear = _readonly  # type: ignore[assignment]
    pop = _readonly  # type: ignore[assignment]
    popitem = _readonly  # type: ignore[assignment]
    setdefault = _readonly  # type: ignore[assignment]
    update = _readonly  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# JSON safety helper
# ---------------------------------------------------------------------------


def _json_safe(obj: Any) -> Any:
    """Recursively convert values to JSON-serializable types."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (frozenset, set)):
        return sorted(obj)
    if isinstance(obj, Mapping):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return str(obj)


# ═══════════════════════════════════════════════════════════════════════════
# Axis Types
# ═══════════════════════════════════════════════════════════════════════════


class AxisInfo(BaseModel):
    """Base axis metadata (Pydantic-validated)."""

    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    values: NpArray | None = None
    labels: list[str] | None = None
    units: str | None = None
    title: str | None = None
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


# Wavenumber / wavelength unit sets for axis_type detection
_WAVENUMBER_UNITS = frozenset({"cm-1", "cm⁻¹", "1/cm", "cm^-1"})
_WAVELENGTH_NM_UNITS = frozenset({"nm", "nanometer", "nanometers"})
_WAVELENGTH_UM_UNITS = frozenset({"um", "µm", "\u03bcm", "micron", "microns", "micrometer", "micrometers"})


class SpectralAxis(AxisInfo):
    """Feature/spectral axis with domain awareness."""

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

    @property
    def range(self) -> tuple[float, float] | None:
        """(min, max) of axis values."""
        if self.values is None or len(self.values) == 0:
            return None
        return (float(np.min(self.values)), float(np.max(self.values)))

    def select_region(self, start: float, end: float) -> np.ndarray:
        """Boolean mask for values within [start, end] (inclusive, order-independent)."""
        if self.values is None:
            raise ValueError("Cannot select region on axis with no values")
        lo, hi = min(start, end), max(start, end)
        return (self.values >= lo) & (self.values <= hi)

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


class SampleAxis(AxisInfo):
    """Sample axis with per-sample metadata."""

    classes: NpArray | None = None
    include_mask: NpArray | None = None
    exclusion_reasons: list[str | None] | None = None
    sample_table: dict[str, list[Any]] | None = None

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


# ═══════════════════════════════════════════════════════════════════════════
# Domain Context
# ═══════════════════════════════════════════════════════════════════════════


class InferredDomain(BaseModel):
    """Heuristic domain guess — NOT authoritative."""

    technique: str | None = None
    confidence: float = 0.0
    source: str = "axis_range"
    reasoning: str = ""


class DomainContext(BaseModel):
    """Authoritative domain — set by user, catalog, or explicit assertion."""

    technique: str | None = None
    sample_type: str | None = None
    measurement_mode: str | None = None
    expected_units: str | None = None
    data_quantity: str | None = None
    instrument: str | None = None
    inferred: InferredDomain | None = None


class TargetContext(BaseModel):
    """Semantics of the target variable."""

    target_type: str | None = None  # "continuous", "categorical", "ordinal"
    target_name: str | None = None
    target_units: str | None = None
    n_classes: int | None = None
    class_names: list[str] | None = None


# ═══════════════════════════════════════════════════════════════════════════
# Provenance
# ═══════════════════════════════════════════════════════════════════════════

# Standard state effect tags (extensible by plugins)
EFFECT_BASELINE_CORRECTED = "baseline_corrected"
EFFECT_NORMALIZED = "normalized"
EFFECT_MEAN_CENTERED = "mean_centered"
EFFECT_SCALED = "scaled"
EFFECT_OUTLIERS_REMOVED = "outliers_removed"
EFFECT_DERIVATIVE = "derivative"
EFFECT_SMOOTHED = "smoothed"
EFFECT_SCATTER_CORRECTED = "scatter_corrected"


class ProvenanceEntry(BaseModel):
    """Single processing step — immutable.

    Although ``frozen=True`` prevents field reassignment, mutable containers
    (dict, list) must be deep-copied at construction to guarantee true
    immutability.  The validators below ensure each entry owns its own copies.
    """

    model_config = ConfigDict(frozen=True)

    op_id: str
    op_version: str = "1.0"
    parameters: Mapping[str, Any] = Field(default_factory=dict)
    timestamp: str = ""
    node_id: str | None = None
    input_shape: tuple[int, ...] | None = None
    output_shape: tuple[int, ...] | None = None
    state_effects: tuple[str, ...] = ()

    @field_validator("parameters", mode="before")
    @classmethod
    def _freeze_parameters(cls, v: Any) -> Mapping[str, Any]:
        """Deep-freeze parameters so entries are immutable in practice."""
        if v is None:
            return MappingProxyType({})
        if isinstance(v, Mapping):
            return cls._freeze_mapping(v)
        raise ValueError("parameters must be a mapping")

    @field_validator("state_effects", mode="before")
    @classmethod
    def _coerce_state_effects(cls, v: Any) -> tuple[str, ...]:
        """Coerce list → tuple for true immutability."""
        if isinstance(v, (list, tuple, frozenset, set)):
            return tuple(v)
        return v

    @classmethod
    def _freeze_mapping(cls, data: Mapping[str, Any]) -> Mapping[str, Any]:
        frozen: dict[str, Any] = {}
        for key, value in data.items():
            frozen[str(key)] = cls._freeze_value(value)
        return MappingProxyType(frozen)

    @classmethod
    def _freeze_value(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return cls._freeze_mapping(value)
        if isinstance(value, np.ndarray):
            return tuple(cls._freeze_value(v) for v in value.tolist())
        if isinstance(value, (list, tuple, set, frozenset)):
            return tuple(cls._freeze_value(v) for v in value)
        try:
            return copy.deepcopy(value)
        except Exception:
            return value


class Provenance:
    """Append-only processing log. THE single source of truth."""

    def __init__(self, entries: list[ProvenanceEntry] | None = None):
        self._entries: list[ProvenanceEntry] = list(entries) if entries else []

    def append(
        self,
        op_id: str,
        parameters: dict[str, Any] | None = None,
        *,
        op_version: str = "1.0",
        node_id: str | None = None,
        input_shape: tuple[int, ...] | None = None,
        output_shape: tuple[int, ...] | None = None,
        state_effects: list[str] | None = None,
    ) -> None:
        self._entries.append(
            ProvenanceEntry(
                op_id=op_id,
                op_version=op_version,
                parameters=parameters or {},
                timestamp=datetime.now(timezone.utc).isoformat(),
                node_id=node_id,
                input_shape=input_shape,
                output_shape=output_shape,
                state_effects=state_effects or [],
            )
        )

    def __iter__(self):
        return iter(self._entries)

    def __len__(self):
        return len(self._entries)

    def __bool__(self):
        return bool(self._entries)

    def __getitem__(self, index: int) -> ProvenanceEntry:
        return self._entries[index]

    @property
    def operations(self) -> list[str]:
        """Ordered list of op_id values."""
        return [e.op_id for e in self._entries]

    @property
    def all_effects(self) -> frozenset[str]:
        """Union of all state_effects across entries."""
        result: set[str] = set()
        for entry in self._entries:
            result.update(entry.state_effects)
        return frozenset(result)

    def has_effect(self, effect: str) -> bool:
        return effect in self.all_effects

    def has_operation(self, prefix: str) -> bool:
        return any(e.op_id.startswith(prefix) for e in self._entries)

    def to_list(self) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for entry in self._entries:
            dumped = entry.model_dump(exclude_none=True)
            dumped["parameters"] = _json_safe(dict(entry.parameters))
            dumped["state_effects"] = list(entry.state_effects)
            entries.append(dumped)
        return entries

    @classmethod
    def from_list(cls, data: list[dict[str, Any]]) -> Provenance:
        entries = []
        for d in data:
            # Handle legacy format: "operation" key → "op_id"
            if "operation" in d and "op_id" not in d:
                d = dict(d)
                d["op_id"] = d.pop("operation")
            entries.append(ProvenanceEntry.model_validate(d))
        return cls(entries)

    def copy(self) -> Provenance:
        # Deep-clone via wire-safe form to isolate nested parameter payloads.
        return Provenance.from_list(self.to_list())


# ═══════════════════════════════════════════════════════════════════════════
# Dataset State (Derived)
# ═══════════════════════════════════════════════════════════════════════════


def _infer_stage(effects: frozenset[str], n_steps: int) -> str:
    """Infer processing stage from accumulated effects."""
    if n_steps == 0:
        return "raw"
    # Check for modeling-related effects
    modeling_keywords = {"modeled", "fitted", "predicted", "calibrated"}
    if effects & modeling_keywords:
        return "modeled"
    # Any preprocessing effects → preprocessed
    preprocessing_effects = {
        EFFECT_BASELINE_CORRECTED,
        EFFECT_NORMALIZED,
        EFFECT_MEAN_CENTERED,
        EFFECT_SCALED,
        EFFECT_DERIVATIVE,
        EFFECT_SMOOTHED,
        EFFECT_SCATTER_CORRECTED,
        EFFECT_OUTLIERS_REMOVED,
    }
    if effects & preprocessing_effects:
        return "preprocessed"
    return "preprocessed"  # has steps but no recognized effects


class DatasetState(BaseModel):
    """Processing state derived from provenance — always computed, never stale."""

    model_config = ConfigDict(frozen=True)

    processing_stage: str
    effects: frozenset[str]
    n_steps: int

    @classmethod
    def from_provenance(cls, prov: Provenance) -> DatasetState:
        effects = prov.all_effects
        return cls(
            processing_stage=_infer_stage(effects, len(prov)),
            effects=effects,
            n_steps=len(prov),
        )

    @property
    def is_baseline_corrected(self) -> bool:
        return EFFECT_BASELINE_CORRECTED in self.effects

    @property
    def is_normalized(self) -> bool:
        return EFFECT_NORMALIZED in self.effects

    @property
    def is_mean_centered(self) -> bool:
        return EFFECT_MEAN_CENTERED in self.effects

    @property
    def is_scaled(self) -> bool:
        return EFFECT_SCALED in self.effects

    @property
    def is_smoothed(self) -> bool:
        return EFFECT_SMOOTHED in self.effects


# ═══════════════════════════════════════════════════════════════════════════
# Quality Metrics
# ═══════════════════════════════════════════════════════════════════════════


class EvaluationResult(BaseModel):
    """Quality metrics scoped to one evaluation run.

    Array fields use list[list[float]] / list[float] for JSON schema
    compatibility (MCP tool discovery). Conversion from np.ndarray is
    handled via Pydantic validators.
    """

    model_config = ConfigDict(frozen=True)

    evaluation_id: str
    model_type: str | None = None
    model_id: str | None = None
    fold: int | None = None
    n_components: int | None = None

    # Regression
    r2: float | None = None
    rmse: float | None = None
    mae: float | None = None

    # Classification
    accuracy: float | None = None
    confusion_matrix: list[list[float]] | None = None

    # Outlier
    outlier_indices: list[int] | None = None
    outlier_percentage: float | None = None
    hotelling_t2: list[float] | None = None
    q_residuals: list[float] | None = None
    t2_limit: float | None = None
    q_limit: float | None = None


class QualityMetrics(BaseModel):
    """Aggregated quality — references scoped evaluations."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    snr: float | None = None
    evaluations: list[EvaluationResult] = Field(default_factory=list)

    @property
    def latest(self) -> EvaluationResult | None:
        return self.evaluations[-1] if self.evaluations else None

    def add_evaluation(self, result: EvaluationResult) -> None:
        self.evaluations.append(result)


# ═══════════════════════════════════════════════════════════════════════════
# Branch Info
# ═══════════════════════════════════════════════════════════════════════════


class BranchInfo(BaseModel):
    """Immutable snapshot identity for pipeline comparison."""

    model_config = ConfigDict(frozen=True)

    label: str
    parent_dataset_id: str
    parent_provenance_index: int
    content_hash: str


# ═══════════════════════════════════════════════════════════════════════════
# Dataset Manifest (Artifact Handle)
# ═══════════════════════════════════════════════════════════════════════════


class DatasetManifest(BaseModel):
    """Lightweight handle for referencing a dataset without carrying data."""

    dataset_id: str
    shape: tuple[int, ...]
    title: str | None = None
    technique: str | None = None
    backend: str = "numpy"
    n_provenance_steps: int = 0
    state_effects: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# SherpaDataset
# ═══════════════════════════════════════════════════════════════════════════


class SherpaDataset:
    """AI-native spectral dataset.

    No untyped meta dict. No provenance sync hacks. No wire format lies.
    Every field is typed. Provenance is a single source of truth.
    Core is dependency-neutral — all external conversions in adapters/.
    """

    _SPECTRAL_DIM = -1  # last dimension (features)
    _SAMPLE_DIM = 0  # first dimension (samples)

    RESERVED_PREFIXES = frozenset({"sherpa.", "system."})

    def __init__(
        self,
        X: Any,
        *,
        spectral_axis: SpectralAxis | None = None,
        sample_axis: SampleAxis | None = None,
        target: np.ndarray | list | None = None,
        target_context: TargetContext | None = None,
        domain: DomainContext | None = None,
        provenance: Provenance | None = None,
        quality: QualityMetrics | None = None,
        backend: str = "numpy",
        title: str | None = None,
        units: str | None = None,
        extra: dict[str, Any] | None = None,
        dataset_id: str | None = None,
    ) -> None:
        # Core data
        self._X = np.atleast_2d(np.asarray(X, dtype=np.float64))
        n_samples, n_features = self._X.shape

        # Validate and store axes in dict for n-dimensional extensibility
        self._axes: dict[int, AxisInfo] = {}

        if spectral_axis is not None:
            if spectral_axis.length > 0 and spectral_axis.length != n_features:
                raise ValueError(f"spectral_axis length ({spectral_axis.length}) != n_features ({n_features})")
            spectral_copy = spectral_axis.copy()
            spectral_copy.bind_expected_length(n_features)
            self._axes[self._SPECTRAL_DIM] = spectral_copy

        if sample_axis is not None:
            if sample_axis.length > 0 and sample_axis.length != n_samples:
                raise ValueError(f"sample_axis length ({sample_axis.length}) != n_samples ({n_samples})")
            if sample_axis.classes is not None and len(sample_axis.classes) != n_samples:
                raise ValueError(f"sample_axis.classes length ({len(sample_axis.classes)}) != n_samples ({n_samples})")
            if sample_axis.include_mask is not None and len(sample_axis.include_mask) != n_samples:
                raise ValueError(
                    f"sample_axis.include_mask length ({len(sample_axis.include_mask)}) != n_samples ({n_samples})"
                )
            sample_copy = sample_axis.copy()
            sample_copy.bind_expected_length(n_samples)
            self._axes[self._SAMPLE_DIM] = sample_copy

        # Validate target
        if target is not None:
            t = np.asarray(target)
            if t.shape[0] != n_samples:
                raise ValueError(f"target length ({t.shape[0]}) != n_samples ({n_samples})")
            self._target: np.ndarray | None = t
        else:
            self._target = None

        # Typed fields
        self._target_context = target_context or TargetContext()
        self._domain = domain or DomainContext()
        self._provenance = provenance or Provenance()
        self._quality = quality or QualityMetrics()

        # Identity
        self.backend = backend
        self.title = title
        self.units = units
        self._dataset_id = dataset_id or str(uuid.uuid4())

        # Extra metadata (namespaced) — deep-copy to isolate from caller
        self._extra: dict[str, Any] = copy.deepcopy(extra) if extra is not None else {}

        # Branching
        self._branch: BranchInfo | None = None

    # ── Core Properties ────────────────────────────────────────────

    @property
    def X(self) -> np.ndarray:
        return self._X

    @property
    def data(self) -> np.ndarray:
        """Alias for X."""
        return self._X

    @property
    def shape(self) -> tuple:
        return self._X.shape

    @property
    def ndim(self) -> int:
        return self._X.ndim

    @property
    def target(self) -> np.ndarray | None:
        return self._target

    @target.setter
    def target(self, value: np.ndarray | list | None) -> None:
        if value is not None:
            t = np.asarray(value)
            if t.shape[0] != self._X.shape[0]:
                raise ValueError(f"target length ({t.shape[0]}) != n_samples ({self._X.shape[0]})")
            self._target = t
        else:
            self._target = None

    @property
    def dataset_id(self) -> str:
        return self._dataset_id

    # ── Axis Access ────────────────────────────────────────────────

    @property
    def spectral_axis(self) -> SpectralAxis | None:
        ax = self._axes.get(self._SPECTRAL_DIM)
        return ax.copy() if isinstance(ax, SpectralAxis) else None

    @spectral_axis.setter
    def spectral_axis(self, value: SpectralAxis) -> None:
        if value.length > 0 and value.length != self._X.shape[1]:
            raise ValueError(f"spectral_axis length ({value.length}) != n_features ({self._X.shape[1]})")
        copied = value.copy()
        copied.bind_expected_length(self._X.shape[1])
        self._axes[self._SPECTRAL_DIM] = copied

    @property
    def sample_axis(self) -> SampleAxis | None:
        ax = self._axes.get(self._SAMPLE_DIM)
        return ax.copy() if isinstance(ax, SampleAxis) else None

    @sample_axis.setter
    def sample_axis(self, value: SampleAxis) -> None:
        if value.length > 0 and value.length != self._X.shape[0]:
            raise ValueError(f"sample_axis length ({value.length}) != n_samples ({self._X.shape[0]})")
        if value.classes is not None and len(value.classes) != self._X.shape[0]:
            raise ValueError(f"sample_axis.classes length ({len(value.classes)}) != n_samples ({self._X.shape[0]})")
        if value.include_mask is not None and len(value.include_mask) != self._X.shape[0]:
            raise ValueError(
                f"sample_axis.include_mask length ({len(value.include_mask)}) != n_samples ({self._X.shape[0]})"
            )
        copied = value.copy()
        copied.bind_expected_length(self._X.shape[0])
        self._axes[self._SAMPLE_DIM] = copied

    def axis(self, dim: int) -> AxisInfo | None:
        """Access axis by dimension index — for n-dimensional extensibility."""
        ax = self._axes.get(dim)
        return ax.copy() if ax is not None else None

    # ── Domain, Provenance, Quality, State ─────────────────────────

    @property
    def domain(self) -> DomainContext:
        return self._domain

    @domain.setter
    def domain(self, value: DomainContext) -> None:
        self._domain = value

    @property
    def target_context(self) -> TargetContext:
        return self._target_context

    @target_context.setter
    def target_context(self, value: TargetContext) -> None:
        self._target_context = value

    @property
    def provenance(self) -> Provenance:
        """First-class provenance. No sync — this IS the source of truth."""
        return self._provenance

    @provenance.setter
    def provenance(self, value: Provenance) -> None:
        self._provenance = value

    @property
    def quality(self) -> QualityMetrics:
        return self._quality

    @quality.setter
    def quality(self, value: QualityMetrics) -> None:
        self._quality = value

    @property
    def state(self) -> DatasetState:
        """Processing state derived from provenance — always computed, never stale."""
        return DatasetState.from_provenance(self._provenance)

    # ── Extra Metadata (namespaced) ────────────────────────────────

    @property
    def extra(self) -> dict[str, Any]:
        return self._extra

    @property
    def meta(self) -> dict[str, Any]:
        """Backward-compatible alias for extra — used by modeling nodes to
        store scientific metadata (pc_labels, n_components, etc.)."""
        return self._extra

    def set_extra(self, key: str, value: Any) -> None:
        """Set extra metadata. Keys must be namespaced (e.g., 'mypackage.key')."""
        if "." not in key:
            raise ValueError(f"Extra keys must be namespaced (e.g., 'mypackage.mykey'), got '{key}'")
        for prefix in self.RESERVED_PREFIXES:
            if key.startswith(prefix):
                raise ValueError(f"Prefix '{prefix}' is reserved for internal use")
        self._extra[key] = value

    def get_extra(self, key: str, default: Any = None) -> Any:
        return self._extra.get(key, default)

    # ── Manifest ───────────────────────────────────────────────────

    @property
    def manifest(self) -> DatasetManifest:
        return DatasetManifest(
            dataset_id=self._dataset_id,
            shape=self.shape,
            title=self.title,
            technique=self._domain.technique,
            backend=self.backend,
            n_provenance_steps=len(self._provenance),
            state_effects=sorted(self.state.effects),
        )

    # ── Branch Info ────────────────────────────────────────────────

    @property
    def branch_info(self) -> BranchInfo | None:
        return self._branch

    # ── Equality ───────────────────────────────────────────────────

    def equals(
        self,
        other: SherpaDataset,
        mode: str = "data",
        atol: float = 1e-8,
        rtol: float = 1e-5,
    ) -> bool:
        """Explicit equality comparison.

        mode='data':     compare X array only
        mode='metadata': compare domain, title, units only
        mode='full':     compare both
        """
        if not isinstance(other, SherpaDataset):
            return False
        if mode in ("data", "full"):
            if self.shape != other.shape:
                return False
            if not np.allclose(self._X, other._X, atol=atol, rtol=rtol, equal_nan=True):
                return False
        if mode in ("metadata", "full"):
            if self._domain != other._domain:
                return False
            if self.title != other.title:
                return False
            if self.units != other.units:
                return False
            if self.backend != other.backend:
                return False
        return True

    @property
    def fingerprint(self) -> str:
        """Fast content hash for comparison without full array equality."""
        return hashlib.sha256(self._X.tobytes()).hexdigest()[:16]

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SherpaDataset):
            return NotImplemented
        return self.equals(other, mode="data")

    # ── Copy ───────────────────────────────────────────────────────

    def copy(self) -> SherpaDataset:
        """Deep copy with new dataset_id."""
        axes_copy: dict[int, AxisInfo] = {}
        for dim, ax in self._axes.items():
            axes_copy[dim] = ax.copy()

        ds = SherpaDataset(
            X=self._X.copy(),
            spectral_axis=axes_copy.get(self._SPECTRAL_DIM),
            sample_axis=axes_copy.get(self._SAMPLE_DIM),
            target=self._target.copy() if self._target is not None else None,
            target_context=self._target_context.model_copy(),
            domain=self._domain.model_copy(deep=True),
            provenance=self._provenance.copy(),
            quality=self._quality.model_copy(deep=True),
            backend=self.backend,
            title=self.title,
            units=self.units,
            extra=copy.deepcopy(self._extra),
        )
        # Copy additional axes beyond sample/spectral
        for dim, ax in axes_copy.items():
            if dim not in (self._SPECTRAL_DIM, self._SAMPLE_DIM):
                ds._axes[dim] = ax
        return ds

    # ── Slicing ────────────────────────────────────────────────────

    def __getitem__(self, key: Any) -> SherpaDataset:
        """Slice the dataset. Preserves domain, provenance, quality.

        ds[bool_mask]      — row selection
        ds[i]              — single row (stays 2D)
        ds[1:3]            — row slice
        ds[:, a:b]         — column slice
        ds[row, col]       — combined
        """
        spectral = self.spectral_axis
        sample = self.sample_axis

        if isinstance(key, np.ndarray) and key.dtype == bool:
            new_X = self._X[key]
            new_sample = _slice_sample_axis(sample, key) if sample else None
            new_target = self._target[key] if self._target is not None else None
            return self._sliced_copy(new_X, spectral_axis=spectral, sample_axis=new_sample, target=new_target)

        if isinstance(key, (int, np.integer)):
            new_X = self._X[key : key + 1]
            new_sample = _slice_sample_axis(sample, slice(key, key + 1)) if sample else None
            new_target = self._target[key : key + 1] if self._target is not None else None
            return self._sliced_copy(new_X, spectral_axis=spectral, sample_axis=new_sample, target=new_target)

        if isinstance(key, slice):
            new_X = self._X[key]
            new_sample = _slice_sample_axis(sample, key) if sample else None
            new_target = self._target[key] if self._target is not None else None
            return self._sliced_copy(new_X, spectral_axis=spectral, sample_axis=new_sample, target=new_target)

        if isinstance(key, tuple) and len(key) == 2:
            row_key, col_key = key
            # Convert scalar int keys to length-1 slices to preserve dimensions
            x_row = row_key
            x_col = col_key
            if isinstance(row_key, (int, np.integer)):
                x_row = slice(row_key, row_key + 1)
            if isinstance(col_key, (int, np.integer)):
                x_col = slice(col_key, col_key + 1)
            new_X = self._X[x_row, x_col]
            new_sample = _slice_sample_axis(sample, row_key) if sample else None
            new_spectral = _slice_spectral_axis(spectral, col_key) if spectral else None
            new_target = None
            if self._target is not None and not isinstance(row_key, type(None)):
                try:
                    new_target = np.atleast_1d(self._target[row_key])
                except (IndexError, TypeError):
                    new_target = None
            return self._sliced_copy(new_X, spectral_axis=new_spectral, sample_axis=new_sample, target=new_target)

        # Fallback — slice X and try to slice sample axis
        new_X = np.atleast_2d(self._X[key])
        new_sample = None
        new_target = None
        try:
            if sample is not None:
                new_sample = _slice_sample_axis(sample, key)
        except Exception:
            pass
        try:
            if self._target is not None:
                new_target = self._target[key]
        except Exception:
            pass
        return self._sliced_copy(new_X, spectral_axis=spectral, sample_axis=new_sample, target=new_target)

    def _sliced_copy(
        self,
        X: np.ndarray,
        spectral_axis: SpectralAxis | None,
        sample_axis: SampleAxis | None,
        target: np.ndarray | None,
    ) -> SherpaDataset:
        """Create a new SherpaDataset from sliced data, preserving metadata."""
        return SherpaDataset(
            X=X,
            spectral_axis=spectral_axis.copy() if spectral_axis else None,
            sample_axis=sample_axis,  # already sliced/copied
            target=target,
            target_context=self._target_context.model_copy(),
            domain=self._domain.model_copy(deep=True),
            provenance=self._provenance.copy(),
            quality=self._quality.model_copy(deep=True),
            backend=self.backend,
            title=self.title,
            units=self.units,
            extra=copy.deepcopy(self._extra),
        )

    # ── Branching ──────────────────────────────────────────────────

    def branch(self, label: str) -> SherpaDataset:
        """Create an immutable-identity branch for pipeline comparison."""
        branched = self.copy()
        branched._branch = BranchInfo(
            label=label,
            parent_dataset_id=self._dataset_id,
            parent_provenance_index=len(self._provenance),
            content_hash=hashlib.sha256(self._X.tobytes()).hexdigest(),
        )
        return branched

    @staticmethod
    def compare_branches(a: SherpaDataset, b: SherpaDataset) -> dict[str, Any]:
        """Compare two branches: provenance, state, and quality diffs."""
        a_state = a.state
        b_state = b.state
        return {
            "a_label": a._branch.label if a._branch else "A",
            "b_label": b._branch.label if b._branch else "B",
            "a_dataset_id": a.dataset_id,
            "b_dataset_id": b.dataset_id,
            "a_steps": len(a._provenance),
            "b_steps": len(b._provenance),
            "a_effects": sorted(a_state.effects),
            "b_effects": sorted(b_state.effects),
            "effects_only_in_a": sorted(a_state.effects - b_state.effects),
            "effects_only_in_b": sorted(b_state.effects - a_state.effects),
            "a_quality_latest": a._quality.latest.model_dump(exclude_none=True) if a._quality.latest else None,
            "b_quality_latest": b._quality.latest.model_dump(exclude_none=True) if b._quality.latest else None,
        }

    # ── Serialization ──────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict. Wire format: type='SherpaDataset', version='1.0'."""
        safe_data = np.where(np.isfinite(self._X), self._X, None).tolist()

        result: dict[str, Any] = {
            "type": "SherpaDataset",
            "version": "1.0",
            "dataset_id": self._dataset_id,
            "shape": list(self.shape),
            "data": safe_data,
            "n_samples": self.shape[0],
            "n_features": self.shape[-1],
            "title": self.title,
            "units": self.units,
            "backend": self.backend,
        }

        if self.spectral_axis:
            result["spectral_axis"] = _serialize_axis(self.spectral_axis)
        if self.sample_axis:
            result["sample_axis"] = _serialize_axis(self.sample_axis)
        if self._target is not None:
            result["target"] = self._target.tolist()

        result["domain"] = self._domain.model_dump(exclude_none=True)
        result["target_context"] = self._target_context.model_dump(exclude_none=True)
        result["provenance"] = self._provenance.to_list()
        result["quality"] = _json_safe(self._quality.model_dump(exclude_none=True))
        result["state"] = self.state.model_dump()

        if self._extra:
            result["extra"] = _json_safe(self._extra)

        if self._branch:
            result["branch"] = self._branch.model_dump()

        # Frontend compatibility: metadata block
        result["metadata"] = {
            "processing_history": self._provenance.to_list(),
            "data_type": self._domain.technique or "generic",
            "is_spectra": self._domain.technique not in (None, "generic"),
        }

        return result

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SherpaDataset:
        """Deserialize from SherpaDataset wire format only."""
        dtype = d.get("type")
        if dtype != "SherpaDataset":
            raise ValueError(f"Expected type='SherpaDataset', got '{dtype}'")

        spectral_axis = _deserialize_spectral_axis(d.get("spectral_axis")) if d.get("spectral_axis") else None
        sample_axis = _deserialize_sample_axis(d.get("sample_axis")) if d.get("sample_axis") else None
        target = np.asarray(d["target"]) if d.get("target") is not None else None

        domain = DomainContext.model_validate(d.get("domain", {}))
        target_context = TargetContext.model_validate(d.get("target_context", {}))
        provenance = Provenance.from_list(d.get("provenance", []))

        quality_data = d.get("quality", {})
        quality = QualityMetrics.model_validate(quality_data) if quality_data else QualityMetrics()

        ds = cls(
            X=np.asarray(d["data"]),
            spectral_axis=spectral_axis,
            sample_axis=sample_axis,
            target=target,
            target_context=target_context,
            domain=domain,
            provenance=provenance,
            quality=quality,
            backend=d.get("backend", "numpy"),
            title=d.get("title"),
            units=d.get("units"),
            extra=d.get("extra", {}),
            dataset_id=d.get("dataset_id"),
        )

        if d.get("branch"):
            ds._branch = BranchInfo.model_validate(d["branch"])

        return ds

    def __repr__(self) -> str:
        tech = self._domain.technique or "unspecified"
        return f"SherpaDataset(shape={self.shape}, technique={tech!r}, backend={self.backend!r}, title={self.title!r})"


# ═══════════════════════════════════════════════════════════════════════════
# Internal Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _serialize_axis(axis: AxisInfo) -> dict[str, Any]:
    """Serialize an axis to JSON-safe dict."""
    result: dict[str, Any] = {}
    if axis.values is not None:
        result["data"] = axis.values.tolist()
    if axis.labels is not None:
        result["labels"] = _json_safe(axis.labels)
    if axis.units is not None:
        result["units"] = axis.units
    if axis.title is not None:
        result["title"] = axis.title

    # SampleAxis-specific fields
    if isinstance(axis, SampleAxis):
        if axis.classes is not None:
            result["classes"] = axis.classes.tolist()
        if axis.include_mask is not None:
            result["include_mask"] = axis.include_mask.tolist()
        if axis.sample_table is not None:
            result["sample_table"] = _json_safe(axis.sample_table)

    return result


def _deserialize_spectral_axis(d: dict[str, Any]) -> SpectralAxis:
    return SpectralAxis(
        values=np.asarray(d["data"]) if d.get("data") is not None else None,
        labels=d.get("labels"),
        units=d.get("units"),
        title=d.get("title"),
    )


def _deserialize_sample_axis(d: dict[str, Any]) -> SampleAxis:
    return SampleAxis(
        values=np.asarray(d["data"]) if d.get("data") is not None else None,
        labels=d.get("labels"),
        units=d.get("units"),
        title=d.get("title"),
        classes=np.asarray(d["classes"], dtype=object) if d.get("classes") is not None else None,
        include_mask=np.asarray(d["include_mask"], dtype=bool) if d.get("include_mask") is not None else None,
        sample_table=d.get("sample_table"),
    )


def _slice_sample_axis(axis: SampleAxis | None, key: Any) -> SampleAxis | None:
    """Slice a SampleAxis along the sample dimension."""
    if axis is None:
        return None

    new_values = None
    if axis.values is not None:
        sliced = axis.values[key]
        new_values = np.atleast_1d(sliced)
    new_labels = None
    if axis.labels is not None:
        if isinstance(key, np.ndarray) and key.dtype == bool:
            new_labels = [l for l, m in zip(axis.labels, key) if m]
        elif isinstance(key, slice):
            new_labels = axis.labels[key]
        elif isinstance(key, (int, np.integer)):
            new_labels = [axis.labels[key]]

    new_classes = np.atleast_1d(axis.classes[key]) if axis.classes is not None else None
    new_mask = np.atleast_1d(axis.include_mask[key]) if axis.include_mask is not None else None

    new_reasons = None
    if axis.exclusion_reasons is not None:
        if isinstance(key, np.ndarray) and key.dtype == bool:
            new_reasons = [r for r, m in zip(axis.exclusion_reasons, key) if m]
        elif isinstance(key, slice):
            new_reasons = axis.exclusion_reasons[key]
        elif isinstance(key, (int, np.integer)):
            new_reasons = [axis.exclusion_reasons[key]]

    return SampleAxis(
        values=new_values,
        labels=new_labels,
        units=axis.units,
        title=axis.title,
        classes=new_classes,
        include_mask=new_mask,
        exclusion_reasons=new_reasons,
        sample_table=None,  # tabular metadata not sliced automatically
    )


def _slice_spectral_axis(axis: SpectralAxis | None, key: Any) -> SpectralAxis | None:
    """Slice a SpectralAxis along the feature dimension."""
    if axis is None:
        return None

    new_values = None
    if axis.values is not None:
        sliced = axis.values[key]
        # Ensure at least 1-d (scalar indexing produces 0-d)
        new_values = np.atleast_1d(sliced)

    new_labels = None
    if axis.labels is not None:
        if isinstance(key, np.ndarray) and key.dtype == bool:
            new_labels = [l for l, m in zip(axis.labels, key) if m]
        elif isinstance(key, slice):
            new_labels = axis.labels[key]
        elif isinstance(key, (int, np.integer)):
            new_labels = [axis.labels[key]]

    return SpectralAxis(
        values=new_values,
        labels=new_labels,
        units=axis.units,
        title=axis.title,
    )
