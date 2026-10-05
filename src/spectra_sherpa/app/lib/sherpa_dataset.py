"""
SherpaDataset — AI-native spectral dataset.

Replaces AnalysisDataset with:
- Pydantic-validated typed fields (no untyped meta bag)
- First-class Provenance (no fragile identity sync)
- Domain-aware axes (SpectralAxis, SampleAxis)
- Quality metrics scoped per evaluation
- Artifact handles for MCP (dataset_id + manifest)
- Equality modes + fingerprinting for testing

Core module is dependency-neutral: no imports from sklearn or any external
spectral library. Native conversions live in adapters; the optional three-node
matrix boundary lives in interoperability.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Annotated, Any, cast

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic import GetCoreSchemaHandler as _GetCoreSchemaHandler
from pydantic import GetJsonSchemaHandler as _GetJsonSchemaHandler
from pydantic.json_schema import JsonSchemaValue as _JsonSchemaValue
from pydantic_core import core_schema as _cs

# Import axis classes from dedicated module
from spectra_sherpa.app.lib.axes import (
    AxisInfo,
    FeatureAxis,
    FrequencyAxis,
    MZAxis,
    PotentialAxis,
    SampleAxis,
    SpatialAxis,
    SpectralAxis,
    TimeAxis,
    revalidated_axis_copy,
)
from spectra_sherpa.app.lib.data_roles import DataRole, data_role_to_modality, normalize_data_role
from spectra_sherpa.app.lib.domain_flags import infer_is_spectra
from spectra_sherpa.app.lib.scientific_values import lossless_json_scalar, lossless_json_value
from spectra_sherpa.core.dimension_roles import DimensionRole, canonical_dimension_roles
from spectra_sherpa.core.target_authority import TargetAuthority

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
    __ior__ = _readonly  # type: ignore[assignment]


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
# Axis Types - Now imported from axes.py module
# ═══════════════════════════════════════════════════════════════════════════

# All axis classes (AxisInfo, FeatureAxis, SpectralAxis, TimeAxis, MZAxis,
# PotentialAxis, FrequencyAxis, SampleAxis) are now defined in axes.py and
# imported above. This maintains backward compatibility while enabling
# extensibility to chromatography, mass spectrometry, electrochemistry, etc.


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
    target_names: list[str] | None = None  # column names for multi-target
    target_units: str | None = None
    n_classes: int | None = None
    class_names: list[str] | None = None
    selected_target: str | None = None  # explicit Y column selection for multi-target
    selected_authority: TargetAuthority | None = None

    @model_validator(mode="after")
    def _selected_authority_is_consistent(self) -> "TargetContext":
        authority = self.selected_authority
        if authority is None:
            return self
        if self.selected_target != authority.column:
            raise ValueError("selected target differs from selected_authority.column")
        if self.target_type != authority.target_type:
            raise ValueError("target type differs from selected_authority.target_type")
        if self.target_units != authority.units:
            raise ValueError("target units differ from selected_authority.units")
        if self.target_names is not None and authority.column not in self.target_names:
            raise ValueError("selected target authority is absent from target_names")
        return self


class DatasetDescriptiveContext(BaseModel):
    """Typed descriptive fields supplied by a source scientific object."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    authors: tuple[str, ...] = ()
    description: str | None = None
    created_at: datetime | None = None
    modified_at: datetime | None = None
    raw_date_fields: Mapping[str, str] = Field(default_factory=dict)

    @field_validator("authors", mode="before")
    @classmethod
    def _validate_authors(cls, value: Any) -> tuple[str, ...]:
        values = tuple(value or ())
        for item in values:
            if not isinstance(item, str) or not item or item != item.strip() or len(item) > 4096:
                raise ValueError("dataset authors must be bounded, non-empty, whitespace-canonical text")
        return values

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or value != value.strip() or len(value) > 65_536:
            raise ValueError("dataset description must be bounded, whitespace-canonical text")
        return value

    @field_validator("raw_date_fields", mode="before")
    @classmethod
    def _validate_raw_dates(cls, value: Any) -> Mapping[str, str]:
        if value is None:
            return FrozenDict()
        if not isinstance(value, Mapping) or len(value) > 16:
            raise ValueError("raw_date_fields must be a bounded mapping")
        normalized: dict[str, str] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key or key != key.strip() or len(key) > 256:
                raise ValueError("raw_date_fields contains an invalid key")
            if not isinstance(item, str) or item != item.strip() or len(item) > 4096:
                raise ValueError("raw_date_fields contains invalid text")
            normalized[key] = item
        return FrozenDict(normalized)


class DatasetSourceIdentity(BaseModel):
    """Portable identity declared by an admitted scientific container."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_format: str | None = None
    storage_version: str | None = None
    object_name: str | None = None
    object_unique_id: str | None = None
    dataset_version: str | None = None
    source_variable: str | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _validate_identity_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value or value != value.strip() or len(value) > 4096:
            raise ValueError("dataset source identity must be bounded, non-empty, whitespace-canonical text")
        return value


class DatasetSourceHistory(BaseModel):
    """Ordered source-native history cells without invented operations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: tuple[str, ...] = ()
    source_shape: tuple[int, ...] | None = None
    storage_order: str = "column-major"

    @field_validator("entries", mode="before")
    @classmethod
    def _validate_entries(cls, value: Any) -> tuple[str, ...]:
        values = tuple(value or ())
        if len(values) > 65_536:
            raise ValueError("dataset source history exceeds the entry limit")
        text_bytes = 0
        for item in values:
            if not isinstance(item, str) or item != item.strip() or len(item) > 65_536:
                raise ValueError("dataset source history entries must be bounded exact text")
            text_bytes += len(item.encode("utf-8"))
            if text_bytes > 4 * 1024 * 1024:
                raise ValueError("dataset source history exceeds the text-byte limit")
        return values

    @field_validator("source_shape", mode="before")
    @classmethod
    def _validate_source_shape(cls, value: Any) -> tuple[int, ...] | None:
        if value is None:
            return None
        if isinstance(value, (str, bytes)):
            raise ValueError("dataset source history shape is invalid")
        try:
            result = tuple(value)
        except TypeError as exc:
            raise ValueError("dataset source history shape is invalid") from exc
        if not result or len(result) > 16 or any(type(item) is not int or item <= 0 for item in result):
            raise ValueError("dataset source history shape is invalid")
        return result

    @field_validator("storage_order")
    @classmethod
    def _validate_storage_order(cls, value: str) -> str:
        if value not in {"column-major", "row-major"}:
            raise ValueError("dataset source history storage order is unsupported")
        return value

    @model_validator(mode="after")
    def _validate_shape(self) -> DatasetSourceHistory:
        if self.source_shape is not None:
            cells = 1
            for dimension in self.source_shape:
                cells *= dimension
            if cells != len(self.entries):
                raise ValueError("dataset source history shape does not match its entries")
        return self


class DatasetLayoutContext(BaseModel):
    """Exact source layout facts needed to interpret n-dimensional data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str = "generic"
    source_type: str | None = None
    source_dtype: str | None = None
    source_shape: tuple[int, ...] | None = None
    mode_roles: tuple[DimensionRole, ...] = ()
    image_size: tuple[int, ...] | None = None
    image_mode: int | None = None
    image_include: tuple[bool, ...] | None = None
    original_unfolded_shape: tuple[int, ...] | None = None

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value: str) -> str:
        if value not in {"generic", "image", "batch", "unknown"}:
            raise ValueError("dataset layout kind is unsupported")
        return value

    @field_validator("source_type", "source_dtype")
    @classmethod
    def _validate_optional_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value or value != value.strip() or len(value) > 256:
            raise ValueError("dataset layout text must be bounded and whitespace-canonical")
        return value

    @field_validator("source_shape", "image_size", "original_unfolded_shape", mode="before")
    @classmethod
    def _validate_shape(cls, value: Any) -> tuple[int, ...] | None:
        if value is None:
            return None
        if isinstance(value, (str, bytes)):
            raise ValueError("dataset layout shape must contain bounded positive integer dimensions")
        try:
            result = tuple(value)
        except TypeError as exc:
            raise ValueError("dataset layout shape must contain bounded positive integer dimensions") from exc
        if not result or len(result) > 16 or any(type(item) is not int or item <= 0 for item in result):
            raise ValueError("dataset layout shape must contain bounded positive integer dimensions")
        return result

    @field_validator("image_mode", mode="before")
    @classmethod
    def _validate_image_mode(cls, value: Any) -> int | None:
        if value is None:
            return None
        if type(value) is not int or value < 0 or value > 2**31 - 1:
            raise ValueError("dataset image mode must be a bounded exact non-negative integer")
        return value

    @field_validator("mode_roles", mode="before")
    @classmethod
    def _validate_mode_roles(cls, value: Any) -> tuple[DimensionRole, ...]:
        if isinstance(value, (str, bytes)):
            raise ValueError("dataset layout dimension roles must be a sequence")
        return canonical_dimension_roles(value or ())

    @field_validator("image_include", mode="before")
    @classmethod
    def _validate_image_include(cls, value: Any) -> tuple[bool, ...] | None:
        if value is None:
            return None
        values = tuple(value)
        if len(values) > 10_000_000 or any(type(item) is not bool for item in values):
            raise ValueError("dataset image include state must be bounded exact booleans")
        return values

    @model_validator(mode="after")
    def _validate_dimension_roles(self) -> DatasetLayoutContext:
        if self.source_shape is not None and self.mode_roles and len(self.mode_roles) != len(self.source_shape):
            raise ValueError("dataset mode_roles length does not match source_shape rank")
        return self


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
    impact: Mapping[str, Any] | None = None
    timestamp: str = ""
    node_id: str | None = None
    input_shape: tuple[int, ...] | None = None
    output_shape: tuple[int, ...] | None = None
    state_effects: tuple[str, ...] = ()

    @field_validator("parameters", mode="after")
    @classmethod
    def _freeze_parameters(cls, v: Any) -> Mapping[str, Any]:
        """Deep-freeze parameters so entries are immutable in practice."""
        if v is None:
            return FrozenDict()
        if isinstance(v, Mapping):
            return cls._freeze_mapping(v)
        raise ValueError("parameters must be a mapping")

    @field_validator("impact", mode="after")
    @classmethod
    def _freeze_impact(cls, v: Any) -> Mapping[str, Any] | None:
        """Deep-freeze an optional, versioned observed-effect record."""
        if v is None:
            return None
        if isinstance(v, Mapping):
            schema_version = v.get("schema_version")
            if (
                not isinstance(schema_version, str)
                or schema_version.strip() != schema_version
                or "/" not in schema_version
                or not schema_version.rsplit("/", 1)[-1].isdigit()
            ):
                raise ValueError("impact.schema_version must end in a numeric contract version")
            return cls._freeze_mapping(v)
        raise ValueError("impact must be a mapping")

    @field_validator("state_effects", mode="before")
    @classmethod
    def _coerce_state_effects(cls, v: Any) -> tuple[str, ...]:
        """Coerce list → tuple for true immutability."""
        if isinstance(v, (list, tuple, frozenset, set)):
            return tuple(v)
        return v  # type: ignore[no-any-return]

    @classmethod
    def _freeze_mapping(cls, data: Mapping[str, Any]) -> Mapping[str, Any]:
        frozen: dict[str, Any] = {}
        for key, value in data.items():
            frozen[str(key)] = cls._freeze_value(value)
        return FrozenDict(frozen)

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

    def __getstate__(self) -> dict[str, Any]:
        """Serialize through the wire-safe form used by project evidence.

        ``ProvenanceEntry`` deep-freezes nested parameter mappings so callers
        cannot mutate scientific history. Python's ``mappingproxy`` is not
        pickleable, however, and datasets are deliberately transferred to
        spawned DAG workers. The wire form crosses that process boundary;
        ``__setstate__`` reconstructs the same immutable entries on arrival.
        """

        return {"entries": self.to_list()}

    def __setstate__(self, state: Mapping[str, Any]) -> None:
        if not isinstance(state, Mapping) or set(state) != {"entries"} or not isinstance(state["entries"], list):
            raise ValueError("invalid serialized provenance state")
        self._entries = Provenance.from_list(state["entries"])._entries

    def append(
        self,
        op_id: str,
        parameters: dict[str, Any] | None = None,
        *,
        op_version: str = "1.0",
        impact: dict[str, Any] | None = None,
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
                impact=impact,
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
            if entry.impact is not None:
                dumped["impact"] = _json_safe(dict(entry.impact))
            dumped["state_effects"] = list(entry.state_effects)
            entries.append(dumped)
        return entries

    @classmethod
    def from_list(cls, data: list[dict[str, Any]]) -> Provenance:
        entries = []
        for d in data:
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

    def get_evaluation(self, evaluation_id: str) -> EvaluationResult | None:
        """Get evaluation result by evaluation_id.

        Args:
            evaluation_id: The evaluation identifier to search for (e.g., "pca_scores", "cross_validation")

        Returns:
            The first matching EvaluationResult, or None if not found

        Example:
            >>> pca_eval = dataset.quality.get_evaluation("pca_scores")
            >>> if pca_eval:
            >>>     print(f"R2: {pca_eval.r2}")
            >>>     print(f"Components: {pca_eval.n_components}")
        """
        for result in self.evaluations:
            if result.evaluation_id == evaluation_id:
                return result
        return None


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
    scientific_projection_schema: str = "spectrasherpa-dataset-scientific-projection/1"
    scientific_digest: str | None = None


def _canonical_payload_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def _payload_digest(value: Any) -> str:
    return hashlib.sha256(_canonical_payload_bytes(value)).hexdigest()


def _array_scientific_projection(array: np.ndarray) -> dict[str, Any]:
    values = np.asarray(array)
    projection: dict[str, Any] = {"dtype": values.dtype.str, "shape": list(values.shape)}
    if values.dtype.kind in "biufc":
        contiguous = np.ascontiguousarray(values)
        projection["sha256"] = hashlib.sha256(memoryview(contiguous).cast("B")).hexdigest()
        return projection
    digest = hashlib.sha256()
    for value in values.reshape(-1):
        normalized = lossless_json_scalar(value, max_text_chars=4096, field_name="scientific array")
        encoded = _canonical_payload_bytes(normalized)
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    projection["sha256"] = digest.hexdigest()
    return projection


def _sequence_scientific_projection(values: Any, *, field_name: str) -> dict[str, Any]:
    digest = hashlib.sha256()
    count = 0
    for value in values:
        normalized = lossless_json_scalar(value, max_text_chars=4096, field_name=field_name)
        encoded = _canonical_payload_bytes(normalized)
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        count += 1
    return {"count": count, "sha256": digest.hexdigest()}


def structured_scientific_projection(
    value: Any,
    *,
    field_name: str,
    max_depth: int = 12,
    max_nodes: int = 1_000_000,
    max_text_bytes: int = 4 * 1024 * 1024,
) -> dict[str, Any]:
    """Digest bounded nested scientific metadata without JSON coercion."""

    budget = {"nodes": 0, "text_bytes": 0}

    def project(item: Any, depth: int) -> Any:
        if depth > max_depth:
            raise ValueError(f"{field_name} exceeds the maximum nesting depth")
        budget["nodes"] += 1
        if budget["nodes"] > max_nodes:
            raise ValueError(f"{field_name} exceeds the node limit")
        if isinstance(item, np.ndarray):
            return {"kind": "array", "projection": _array_scientific_projection(item)}
        if isinstance(item, Mapping):
            if not all(isinstance(key, str) for key in item):
                raise ValueError(f"{field_name} requires exact string mapping keys")
            records = []
            for key in sorted(item):
                budget["text_bytes"] += len(key.encode("utf-8"))
                records.append({"key": key, "value": project(item[key], depth + 1)})
            result: Any = {"kind": "mapping", "records": records}
        elif isinstance(item, (list, tuple)):
            result = {"kind": "sequence", "items": [project(nested, depth + 1) for nested in item]}
        else:
            scalar = lossless_json_scalar(item, max_text_chars=65_536, field_name=field_name)
            if isinstance(scalar, str):
                budget["text_bytes"] += len(scalar.encode("utf-8"))
            result = {"kind": "scalar", "value": scalar}
        if budget["text_bytes"] > max_text_bytes:
            raise ValueError(f"{field_name} exceeds the text-byte limit")
        return result

    projection = project(value, 0)
    return {
        "nodes": budget["nodes"],
        "text_bytes": budget["text_bytes"],
        "sha256": _payload_digest(projection),
    }


def _admit_structured_scientific_projection(value: Any, *, field_name: str) -> dict[str, Any]:
    """Admit a previously issued digest-only structured projection."""

    if not isinstance(value, Mapping) or set(value) != {"nodes", "text_bytes", "sha256"}:
        raise ValueError(f"{field_name} projection is malformed")
    nodes = value["nodes"]
    text_bytes = value["text_bytes"]
    digest = value["sha256"]
    if (
        type(nodes) is not int
        or nodes < 1
        or nodes > 1_000_000
        or type(text_bytes) is not int
        or text_bytes < 0
        or text_bytes > 4 * 1024 * 1024
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise ValueError(f"{field_name} projection is malformed")
    return {"nodes": nodes, "text_bytes": text_bytes, "sha256": digest}


def _axis_scientific_projection(axis: AxisInfo, *, include_sample_table: bool = True) -> dict[str, Any]:
    projection: dict[str, Any] = {
        "axis_class": type(axis).__name__,
        "values": _array_scientific_projection(axis.values) if axis.values is not None else None,
        "labels": (
            _sequence_scientific_projection(axis.labels, field_name="axis labels") if axis.labels is not None else None
        ),
        "units": axis.units,
        "title": axis.title,
        "include_mask": _array_scientific_projection(axis.include_mask) if axis.include_mask is not None else None,
        "primary_scale_name": axis.primary_scale_name,
        "alternate_scales": [
            {
                "name": item.name,
                "values": _array_scientific_projection(item.values),
                "title": item.title,
                "units": item.units,
                "axis_type": item.axis_type,
                "source_set_index": item.source_set_index,
            }
            for item in axis.alternate_scales
        ],
        "primary_label_name": axis.primary_label_name,
        "alternate_label_sets": [
            {
                "name": item.name,
                "values": _sequence_scientific_projection(item.values, field_name="axis label set"),
                "source_set_index": item.source_set_index,
            }
            for item in axis.alternate_label_sets
        ],
        "primary_title_name": axis.primary_title_name,
        "alternate_title_sets": [item.model_dump(mode="json") for item in axis.alternate_title_sets],
        "primary_class_set_name": axis.primary_class_set_name,
        "class_sets": [
            {
                "name": item.name,
                "values": _sequence_scientific_projection(item.values, field_name="axis class set"),
                "levels": [level.model_dump(mode="json") for level in item.levels],
                "source_set_index": item.source_set_index,
            }
            for item in axis.class_sets
        ],
    }
    if isinstance(axis, FeatureAxis):
        projection.update(
            {
                "axis_type": axis.axis_type,
                "selection_scores": (
                    _array_scientific_projection(axis.selection_scores) if axis.selection_scores is not None else None
                ),
                "selection_method": axis.selection_method,
            }
        )
    if isinstance(axis, SampleAxis):
        sample_table = None
        if include_sample_table and axis.sample_table is not None:
            sample_table = [
                {
                    "name": name,
                    "values": _sequence_scientific_projection(values, field_name=f"sample table {name}"),
                }
                for name, values in sorted(axis.sample_table.items())
            ]
        projection.update(
            {
                # When a named primary class set exists, ``classes`` is its
                # compatibility projection and not a second scientific
                # authority with a NumPy-storage dtype of its own.
                "classes": (
                    _array_scientific_projection(axis.classes)
                    if axis.classes is not None and axis.primary_class_set_name is None
                    else None
                ),
                "exclusion_reasons": (
                    _sequence_scientific_projection(axis.exclusion_reasons, field_name="sample exclusion reasons")
                    if axis.exclusion_reasons is not None
                    else None
                ),
                "sample_table": sample_table,
            }
        )
    return projection


# ═══════════════════════════════════════════════════════════════════════════
# Helper Functions
# ═══════════════════════════════════════════════════════════════════════════


def _validate_axis_length(
    expected: int,
    actual: int,
    axis_type: str,
    data_shape: tuple[int, ...],
    axis_name: str = "axis",
) -> None:
    """Validate axis length with helpful error messages and fix suggestions.

    Args:
        expected: Expected axis length (from data dimension)
        actual: Actual axis length (from axis object)
        axis_type: Type of axis for context ("feature", "sample", etc.)
        data_shape: Full data shape for transpose suggestions
        axis_name: Name of the axis parameter (for error message)

    Raises:
        ValueError: If lengths don't match, with context-aware suggestions
    """
    if actual == expected:
        return  # Lengths match, all good

    # Build helpful error message with suggestions
    msg_parts = [
        "❌ Axis dimension mismatch:",
        f"   {axis_name} has {actual} points",
        f"   But data expects {expected} {axis_type}s",
        "",
        f"Data shape: {data_shape}",
        f"{axis_name} length: {actual}",
        "",
    ]

    # Suggest transpose if dimensions are reversed (only for 2D data)
    if axis_type == "feature" and len(data_shape) == 2:
        n_samples, n_features = data_shape[0], data_shape[1]
        if actual == n_samples and expected == n_features:
            msg_parts.extend(
                [
                    "💡 Suggestion: Your data may be transposed.",
                    "   Try: X=X.T (transpose your data matrix)",
                    f"   This will change shape {data_shape} → ({n_features}, {n_samples})",
                    "",
                ]
            )

    # Suggest removing index columns for sample axis
    if axis_type == "sample" and actual > 50 and expected < actual / 2:
        msg_parts.extend(
            [
                "💡 Suggestion: Do you have index/metadata columns in your data?",
                "   Remove non-numeric columns before creating dataset",
                f"   Expected {expected} samples but axis has {actual} entries",
                "",
            ]
        )

    # General debugging hints
    msg_parts.extend(
        [
            "📘 Debug checklist:",
            "   1. Check data.shape matches (n_samples, n_features)",
            "   2. Verify axis.length == appropriate dimension",
            "   3. For chromatography: data.shape = (n_samples, n_timepoints)",
            "   4. For spectroscopy: data.shape = (n_samples, n_wavenumbers)",
            "   5. For mass spec: data.shape = (n_samples, n_mz_points)",
        ]
    )

    raise ValueError("\n".join(msg_parts))


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
        feature_axis: FeatureAxis | None = None,
        sample_axis: SampleAxis | None = None,
        axes: dict[int, AxisInfo] | None = None,
        target: np.ndarray | list | None = None,
        target_context: TargetContext | None = None,
        domain: DomainContext | None = None,
        descriptive: DatasetDescriptiveContext | None = None,
        source_identity: DatasetSourceIdentity | None = None,
        source_history: DatasetSourceHistory | None = None,
        layout: DatasetLayoutContext | None = None,
        provenance: Provenance | None = None,
        quality: QualityMetrics | None = None,
        backend: str = "numpy",
        title: str | None = None,
        units: str | None = None,
        extra: dict[str, Any] | None = None,
        dataset_id: str | None = None,
        is_time_series: bool = False,
        data_role: DataRole | str | None = None,
    ) -> None:
        # Core data — accept nD arrays (dim 0 = samples, dim -1 = features)
        arr = np.asarray(X, dtype=np.float64, order="C")
        if arr.ndim == 0:
            raise ValueError("X must be at least 1-dimensional, got scalar")
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        self._X = arr
        n_samples = self._X.shape[0]
        n_features = self._X.shape[-1]

        # Validate and store axes in dict for n-dimensional extensibility
        self._axes: dict[int, AxisInfo] = {}

        if feature_axis is not None:
            if feature_axis.length > 0 and feature_axis.length != n_features:
                _validate_axis_length(
                    expected=n_features,
                    actual=feature_axis.length,
                    axis_type="feature",
                    data_shape=tuple(self._X.shape),
                    axis_name="feature_axis",
                )
            axis_copy = revalidated_axis_copy(feature_axis)
            axis_copy.bind_expected_length(n_features)
            self._axes[self._SPECTRAL_DIM] = axis_copy

        if sample_axis is not None:
            if sample_axis.length > 0 and sample_axis.length != n_samples:
                _validate_axis_length(
                    expected=n_samples,
                    actual=sample_axis.length,
                    axis_type="sample",
                    data_shape=tuple(self._X.shape),
                    axis_name="sample_axis",
                )
            if sample_axis.classes is not None and len(sample_axis.classes) != n_samples:
                raise ValueError(
                    f"sample_axis.classes length ({len(sample_axis.classes)}) != n_samples ({n_samples}). "
                    f"classes must have one entry per sample."
                )
            if sample_axis.include_mask is not None and len(sample_axis.include_mask) != n_samples:
                raise ValueError(
                    f"sample_axis.include_mask length ({len(sample_axis.include_mask)}) != n_samples ({n_samples}). "
                    f"include_mask must have one boolean per sample."
                )
            sample_copy = revalidated_axis_copy(sample_axis)
            sample_copy.bind_expected_length(n_samples)
            self._axes[self._SAMPLE_DIM] = sample_copy

        # Validate and store inner-dimension axes (dims 1..ndim-2)
        if axes is not None:
            ndim = self._X.ndim
            for dim, axis_info in axes.items():
                normalized = dim if dim >= 0 else ndim + dim
                if normalized == 0 or normalized == ndim - 1:
                    raise ValueError(
                        f"axes[{dim}] conflicts with sample (dim 0) or feature (dim -1). "
                        f"Use sample_axis= or feature_axis= instead."
                    )
                if normalized < 1 or normalized >= ndim - 1:
                    raise ValueError(
                        f"Dimension {dim} (normalized: {normalized}) is out of range "
                        f"for data with ndim={ndim}. Inner axes must be in "
                        f"range [1, {ndim - 2}]."
                    )
                expected_size = self._X.shape[normalized]
                if axis_info.length > 0 and axis_info.length != expected_size:
                    _validate_axis_length(
                        expected=expected_size,
                        actual=axis_info.length,
                        axis_type="inner",
                        data_shape=tuple(self._X.shape),
                        axis_name=f"axes[{dim}]",
                    )
                ac = revalidated_axis_copy(axis_info)
                ac.bind_expected_length(expected_size)
                self._axes[normalized] = ac

        # Validate target
        if target is not None:
            t = np.asarray(target, order="C")
            if t.shape[0] != n_samples:
                msg_parts = [
                    "❌ Target length mismatch:",
                    f"   target has {t.shape[0]} values",
                    f"   But data has {n_samples} samples",
                    "",
                    "💡 Each sample needs exactly one target value.",
                    f"   Ensure len(target) == n_samples ({n_samples})",
                ]
                raise ValueError("\n".join(msg_parts))
            self._target: np.ndarray | None = t
        else:
            self._target = None

        # Typed fields
        # Re-admit immutable nested models from their complete Python projection.
        # Pydantic's ``model_copy(update=...)`` intentionally skips validation;
        # accepting such an instance directly here would let callers bypass the
        # scientific bounds enforced by these context models.
        self._target_context = TargetContext.model_validate(
            target_context.model_dump(mode="python") if target_context is not None else {}
        )
        self._domain = DomainContext.model_validate(domain.model_dump(mode="python") if domain is not None else {})
        self._descriptive = DatasetDescriptiveContext.model_validate(
            descriptive.model_dump(mode="python") if descriptive is not None else {}
        )
        self._source_identity = DatasetSourceIdentity.model_validate(
            source_identity.model_dump(mode="python") if source_identity is not None else {}
        )
        self._source_history = DatasetSourceHistory.model_validate(
            source_history.model_dump(mode="python") if source_history is not None else {}
        )
        self._layout = DatasetLayoutContext.model_validate(
            layout.model_dump(mode="python") if layout is not None else {}
        )
        if self._layout.source_shape is not None and self._layout.source_shape != tuple(self._X.shape):
            raise ValueError("dataset layout source_shape does not match admitted data shape")
        if self._layout.mode_roles and len(self._layout.mode_roles) != self._X.ndim:
            raise ValueError("dataset layout mode_roles do not match admitted data rank")
        self._provenance = provenance or Provenance()
        self._quality = quality or QualityMetrics()

        # Identity
        self.backend = backend
        self.title = title
        self.units = units
        self._dataset_id = dataset_id or str(uuid.uuid4())

        # Time-series flag — opt-in marker for kinetic / evolving data
        self.is_time_series: bool = is_time_series

        # Extra metadata (namespaced) — deep-copy to isolate from caller
        self._extra: dict[str, Any] = copy.deepcopy(extra) if extra is not None else {}
        if "dso.userdata" in self._extra:
            self._extra["dso.userdata"] = lossless_json_value(
                self._extra["dso.userdata"],
                field_name="dso.userdata",
            )
        self._data_role: DataRole = normalize_data_role(data_role or self._extra.get("sherpa.data_role"))
        self._extra["sherpa.data_role"] = self._data_role
        self._extra["sherpa.data_modality"] = data_role_to_modality(self._data_role)

        # Branching
        self._branch: BranchInfo | None = None

    # ── Pickle support ──────────────────────────────────────────────

    @staticmethod
    def _plain_metadata_containers(obj: Any) -> Any:
        """Recursively copy mapping/list metadata into built-in containers."""
        if isinstance(obj, dict):
            return {k: SherpaDataset._plain_metadata_containers(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            converted = [SherpaDataset._plain_metadata_containers(v) for v in obj]
            return type(obj)(converted)
        return obj

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        state["_extra"] = self._plain_metadata_containers(state.get("_extra", {}))
        return state

    # ── Core Properties ────────────────────────────────────────────

    @property
    def X(self) -> np.ndarray:
        return self._X

    @property
    def data(self) -> np.ndarray:
        """Alias for X — used by nodes and adapters for array access."""
        return self._X

    @property
    def shape(self) -> tuple:
        return self._X.shape  # type: ignore[no-any-return]

    @property
    def ndim(self) -> int:
        return int(self._X.ndim)

    @property
    def n_samples(self) -> int:
        """Number of samples (first dimension)."""
        return int(self._X.shape[0])

    @property
    def n_features(self) -> int:
        """Number of features (last dimension)."""
        return int(self._X.shape[-1])

    @property
    def inner_shape(self) -> tuple[int, ...]:
        """Shape of inner dimensions (empty tuple for 2D data)."""
        return tuple(int(x) for x in self._X.shape[1:-1])

    @property
    def inner_axes(self) -> dict[int, AxisInfo]:
        """Axes for inner dimensions (not sample or feature)."""
        return {d: a.copy() for d, a in self._axes.items() if d not in (self._SAMPLE_DIM, self._SPECTRAL_DIM)}

    def dim_role(self, dim: int) -> str:
        """Return the semantic role of a dimension: 'sample', 'feature', or 'inner'."""
        normalized = dim if dim >= 0 else self._X.ndim + dim
        if normalized == 0:
            return "sample"
        if normalized == self._X.ndim - 1:
            return "feature"
        return "inner"

    @property
    def target(self) -> np.ndarray | None:
        return self._target

    @target.setter
    def target(self, value: np.ndarray | list | None) -> None:
        if value is not None:
            t = np.asarray(value, order="C")
            if t.shape[0] != self._X.shape[0]:
                msg_parts = [
                    "❌ Target length mismatch:",
                    f"   target has {t.shape[0]} values",
                    f"   But data has {self._X.shape[0]} samples",
                    "",
                    "💡 Each sample needs exactly one target value.",
                    f"   Ensure len(target) == n_samples ({self._X.shape[0]})",
                ]
                raise ValueError("\n".join(msg_parts))
            self._target = t
        else:
            self._target = None

    @property
    def target_names(self) -> list[str] | None:
        """Convenience accessor for target_context.target_names.

        Used by export helpers (wrap_result_lines) and _Result compatibility.
        """
        tc = self._target_context
        return tc.target_names if tc is not None else None

    @property
    def x(self) -> FeatureAxis | None:
        """Convenience alias for feature_axis.

        Provides compatibility with the SCP ``.x`` accessor convention and
        with the ``_Result`` container used in exported Python scripts.
        """
        return self.feature_axis

    @property
    def dataset_id(self) -> str:
        return self._dataset_id

    # ── Axis Access ────────────────────────────────────────────────

    @property
    def feature_axis(self) -> FeatureAxis | None:
        """Generic feature axis accessor (spectral, time, m/z, potential, etc.).

        Returns the appropriate FeatureAxis subclass based on what's stored:
        - SpectralAxis for spectroscopy (wavelength, wavenumber)
        - TimeAxis for chromatography (retention time, elution time)
        - MZAxis for mass spectrometry (m/z)
        - PotentialAxis for electrochemistry (voltage)
        - FrequencyAxis for NMR, dielectric spectroscopy

        This is the recommended way to access and set feature axes.

        Example:
            >>> # Get feature axis (any type)
            >>> axis = dataset.feature_axis
            >>> if isinstance(axis, TimeAxis):
            >>>     print("Chromatography data")
            >>>
            >>> # Set feature axis (any FeatureAxis subclass)
            >>> from spectra_sherpa.app.lib.axes import TimeAxis
            >>> dataset.feature_axis = TimeAxis(values=times, units="min")
        """
        ax = self._axes.get(self._SPECTRAL_DIM)
        if ax is None:
            return None
        # Return copy of the appropriate FeatureAxis subclass
        if isinstance(ax, (SpectralAxis, TimeAxis, MZAxis, PotentialAxis, FrequencyAxis)):
            return ax.copy()
        # Fallback for generic FeatureAxis or AxisInfo
        if isinstance(ax, FeatureAxis):
            return ax.copy()
        return None

    @feature_axis.setter
    def feature_axis(self, value: FeatureAxis) -> None:
        """Set the feature axis (accepts any FeatureAxis subclass)."""
        if value.length > 0 and value.length != self._X.shape[-1]:
            _validate_axis_length(
                expected=self._X.shape[-1],
                actual=value.length,
                axis_type="feature",
                data_shape=tuple(self._X.shape),
                axis_name="feature_axis",
            )
        copied = revalidated_axis_copy(value)
        copied.bind_expected_length(self._X.shape[-1])
        self._axes[self._SPECTRAL_DIM] = copied

    @property
    def sample_axis(self) -> SampleAxis | None:
        ax = self._axes.get(self._SAMPLE_DIM)
        return ax.copy() if isinstance(ax, SampleAxis) else None

    @sample_axis.setter
    def sample_axis(self, value: SampleAxis) -> None:
        if value.length > 0 and value.length != self._X.shape[0]:
            _validate_axis_length(
                expected=self._X.shape[0],
                actual=value.length,
                axis_type="sample",
                data_shape=self._X.shape,
                axis_name="sample_axis",
            )
        if value.classes is not None and len(value.classes) != self._X.shape[0]:
            msg_parts = [
                "❌ Classes length mismatch:",
                f"   sample_axis.classes has {len(value.classes)} entries",
                f"   But data has {self._X.shape[0]} samples",
                "",
                "💡 Each sample must have exactly one class label.",
                f"   Ensure len(classes) == n_samples ({self._X.shape[0]})",
            ]
            raise ValueError("\n".join(msg_parts))
        if value.include_mask is not None and len(value.include_mask) != self._X.shape[0]:
            msg_parts = [
                "❌ Include mask length mismatch:",
                f"   sample_axis.include_mask has {len(value.include_mask)} entries",
                f"   But data has {self._X.shape[0]} samples",
                "",
                "💡 Each sample must have exactly one boolean flag.",
                f"   Ensure len(include_mask) == n_samples ({self._X.shape[0]})",
            ]
            raise ValueError("\n".join(msg_parts))
        copied = revalidated_axis_copy(value)
        copied.bind_expected_length(self._X.shape[0])
        self._axes[self._SAMPLE_DIM] = copied

    def axis(self, dim: int) -> AxisInfo | None:
        """Access axis by dimension index — for n-dimensional extensibility.

        This is the generic axis accessor that returns any axis type.
        Use this for multi-dimensional data like time-resolved spectroscopy.

        Args:
            dim: Dimension index (0 for first dim, -1 for last dim, etc.)

        Returns:
            Copy of the axis at the specified dimension, or None if not set.

        Examples:
            >>> # Time-resolved spectroscopy
            >>> time_axis = dataset.axis(0)  # Returns TimeAxis
            >>> spec_axis = dataset.axis(-1)  # Returns SpectralAxis
        """
        ax = self._axes.get(dim)
        return ax.copy() if ax is not None else None

    def get_feature_axis(self) -> FeatureAxis | None:
        """Get the feature axis from the last dimension (generic accessor).

        Returns any FeatureAxis subclass (SpectralAxis, TimeAxis, MZAxis, etc.)
        This is more permissive than the feature_axis property.

        Useful for code that works with any feature type (preprocessing, plotting).

        Returns:
            Copy of the feature axis, or None if not a FeatureAxis.

        Examples:
            >>> # Works for spectroscopy
            >>> axis = dataset.get_feature_axis()  # Returns SpectralAxis
            >>> # Also works for chromatography
            >>> axis = dataset.get_feature_axis()  # Returns TimeAxis
        """
        ax = self._axes.get(self._SPECTRAL_DIM)
        if ax is not None and isinstance(ax, FeatureAxis):
            return ax.copy()
        return None

    def get_observation_axis(self) -> AxisInfo | None:
        """Get the observation/sample/time axis from the first dimension (generic accessor).

        Returns any axis type (SampleAxis, TimeAxis, BatchAxis, etc.)
        This is more permissive than sample_axis property.

        Useful for time-resolved spectroscopy where dimension 0 is time, not samples.

        Returns:
            Copy of the axis at dimension 0, or None if not set.

        Examples:
            >>> # Regular sample-based data
            >>> axis = dataset.get_observation_axis()  # Returns SampleAxis
            >>> # Time-resolved spectroscopy (MCR-ALS)
            >>> axis = dataset.get_observation_axis()  # Returns TimeAxis
        """
        ax = self._axes.get(self._SAMPLE_DIM)
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
    def descriptive(self) -> DatasetDescriptiveContext:
        return self._descriptive

    @property
    def source_identity(self) -> DatasetSourceIdentity:
        return self._source_identity

    @property
    def source_history(self) -> DatasetSourceHistory:
        return self._source_history

    @property
    def layout(self) -> DatasetLayoutContext:
        return self._layout

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
    def data_role(self) -> DataRole:
        return self._data_role

    @data_role.setter
    def data_role(self, value: DataRole | str) -> None:
        self._data_role = normalize_data_role(value)
        self._extra["sherpa.data_role"] = self._data_role
        self._extra["sherpa.data_modality"] = data_role_to_modality(self._data_role)

    @property
    def data_modality(self) -> str:
        return data_role_to_modality(self._data_role)

    @property
    def meta(self) -> dict[str, Any]:
        """Dict-style access to extra metadata for internal node use.

        Nodes use ``ds.meta["key"] = value`` to store scientific metadata
        (pc_labels, calibration_model, etc.) without the namespacing
        enforcement of ``set_extra()``.
        """
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
            scientific_digest=self.scientific_digest,
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
        mode='metadata': compare the complete canonical scientific metadata
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
            if self.scientific_projection(include_data=False) != other.scientific_projection(include_data=False):
                return False
        return True

    def scientific_projection(
        self,
        *,
        include_data: bool = True,
        include_provenance: bool = True,
        include_sample_table: bool = True,
    ) -> dict[str, Any]:
        """Return the closed, portable scientific identity projection."""

        axes = [
            {
                "dimension": dim if dim >= 0 else self.ndim + dim,
                "projection": _axis_scientific_projection(
                    axis,
                    include_sample_table=include_sample_table,
                ),
            }
            for dim, axis in sorted(
                self._axes.items(),
                key=lambda item: item[0] if item[0] >= 0 else self.ndim + item[0],
            )
        ]
        source_identity_projection = self._source_identity.model_dump(mode="json", exclude_none=True)
        provenance_projection = self._provenance.to_list()
        if self._source_identity.source_format == "eigenvector-dso":
            # MAT storage generation and raw container bytes are custody facts,
            # not DSO science. They remain on the typed dataset/provenance wire,
            # while v5 and v7.3 encodings of the same object reproduce one
            # canonical scientific digest.
            source_identity_projection.pop("storage_version", None)
            provenance_projection = copy.deepcopy(provenance_projection)
            for entry in provenance_projection:
                if entry.get("op_id") != "import.matlab_dso":
                    continue
                parameters = entry.get("parameters")
                if isinstance(parameters, dict):
                    for storage_field in ("source_sha256", "source_size_bytes", "storage_version"):
                        parameters.pop(storage_field, None)
        projection: dict[str, Any] = {
            "schema_version": "spectrasherpa-dataset-scientific-projection/1",
            "shape": list(self.shape),
            "normalized_dtype": self._X.dtype.str,
            "title": self.title,
            "units": self.units,
            "data_role": self._data_role,
            "domain": self._domain.model_dump(mode="json", exclude_none=True),
            "target_context": self._target_context.model_dump(mode="json", exclude_none=True),
            "target": _array_scientific_projection(self._target) if self._target is not None else None,
            "axes": axes,
            "descriptive": self._descriptive.model_dump(mode="json", exclude_none=True),
            "source_identity": source_identity_projection,
            "source_history": self._source_history.model_dump(mode="json", exclude_none=True),
            "layout": self._layout.model_dump(mode="json", exclude_none=True),
            "provenance": (
                {
                    "count": len(self._provenance),
                    "sha256": _payload_digest(provenance_projection),
                }
                if include_provenance
                else None
            ),
            "dso_userdata": copy.deepcopy(self._extra.get("dso.userdata")) if "dso.userdata" in self._extra else None,
            "collection_member_science": (
                structured_scientific_projection(
                    self._extra["source_member_metadata"],
                    field_name="collection member scientific metadata",
                )
                if "source_member_metadata" in self._extra
                else (
                    _admit_structured_scientific_projection(
                        self._extra["sherpa.source_member_scientific_projection"],
                        field_name="collection member scientific metadata",
                    )
                    if "sherpa.source_member_scientific_projection" in self._extra
                    else None
                )
            ),
        }
        if include_data:
            projection["X"] = _array_scientific_projection(self._X)
        return projection

    @property
    def scientific_digest(self) -> str:
        return _payload_digest(self.scientific_projection())

    @property
    def fingerprint(self) -> str:
        """Fast data-only hash; use ``scientific_digest`` for scientific identity."""
        return hashlib.sha256(memoryview(self._X).cast("B")).hexdigest()[:16]

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

        inner = {d: a for d, a in axes_copy.items() if d not in (self._SPECTRAL_DIM, self._SAMPLE_DIM)} or None

        # Determine which FeatureAxis subtype the spectral dim holds
        spectral_dim_ax = axes_copy.get(self._SPECTRAL_DIM)
        feature_ax = spectral_dim_ax if isinstance(spectral_dim_ax, FeatureAxis) else None

        dim0_ax = axes_copy.get(self._SAMPLE_DIM)
        sample_ax = dim0_ax if isinstance(dim0_ax, SampleAxis) else None

        ds = SherpaDataset(
            X=self._X.copy(),
            feature_axis=feature_ax,
            sample_axis=sample_ax,
            axes=inner,
            target=self._target.copy() if self._target is not None else None,
            target_context=self._target_context.model_copy(deep=True),
            domain=self._domain.model_copy(deep=True),
            descriptive=self._descriptive.model_copy(deep=True),
            source_identity=self._source_identity.model_copy(deep=True),
            source_history=self._source_history.model_copy(deep=True),
            layout=self._layout.model_copy(deep=True),
            provenance=self._provenance.copy(),
            quality=self._quality.model_copy(deep=True),
            backend=self.backend,
            title=self.title,
            units=self.units,
            extra=copy.deepcopy(self._extra),
            is_time_series=self.is_time_series,
            data_role=self._data_role,
        )

        if dim0_ax is not None and not isinstance(dim0_ax, SampleAxis):
            ds._axes[self._SAMPLE_DIM] = dim0_ax.copy()

        return ds

    def snapshot(self) -> SherpaDataset:
        """Return a defensive deep copy that preserves dataset identity.

        Process-local handle registries use this instead of a JSON round trip.
        A snapshot must not box scientific arrays into Python lists merely to
        isolate mutable state. One shared deepcopy memo also preserves aliases
        between canonical fields and scientific metadata, so a single ndarray
        authority is not silently duplicated in the retained snapshot.
        """

        return copy.deepcopy(self)

    def with_data(self, new_data: Any) -> SherpaDataset:
        """Create a new SherpaDataset with replaced data, preserving all metadata.

        Copies feature_axis, sample_axis, target, target_context, domain,
        provenance, quality, and extra metadata.  Feature axis is preserved
        only when the feature count matches; target and sample axis are
        preserved only when the sample count matches.

        Example::

            normalized = spectra.with_data((data - mean) / std)
        """
        arr = np.asarray(new_data, dtype=np.float64)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)

        same_samples = arr.shape[0] == self._X.shape[0]
        same_features = arr.shape[-1] == self._X.shape[-1]

        feature_ax = self.feature_axis if same_features else None
        sample_ax = self.sample_axis if same_samples else None
        target = self._target.copy() if (self._target is not None and same_samples) else None

        axes_copy: dict[int, AxisInfo] = {}
        for dim, ax in self._axes.items():
            if dim == self._SPECTRAL_DIM or dim == self._SAMPLE_DIM:
                continue
            # Inner axes: preserve if dimension size matches
            normalized_dim = dim if dim >= 0 else arr.ndim + dim
            if 0 < normalized_dim < arr.ndim and arr.shape[normalized_dim] == self._X.shape[normalized_dim]:
                axes_copy[dim] = ax.copy()
        inner = axes_copy or None
        layout_updates: dict[str, Any] = {}
        if self._layout.source_shape is not None:
            layout_updates["source_shape"] = tuple(arr.shape)
        if self._layout.mode_roles and arr.ndim != self.ndim:
            layout_updates["mode_roles"] = ()
        layout = self._layout.model_copy(deep=True, update=layout_updates)

        ds = SherpaDataset(
            X=arr,
            feature_axis=feature_ax,
            sample_axis=sample_ax,
            axes=inner,
            target=target,
            target_context=self._target_context.model_copy(deep=True),
            domain=self._domain.model_copy(deep=True),
            descriptive=self._descriptive.model_copy(deep=True),
            source_identity=self._source_identity.model_copy(deep=True),
            source_history=self._source_history.model_copy(deep=True),
            layout=layout,
            provenance=self._provenance.copy(),
            quality=self._quality.model_copy(deep=True),
            backend=self.backend,
            title=self.title,
            units=self.units,
            extra=copy.deepcopy(self._extra),
            is_time_series=self.is_time_series,
            data_role=self._data_role,
        )

        # Preserve non-SampleAxis at dim 0 if applicable
        dim0_ax = self._axes.get(self._SAMPLE_DIM)
        if dim0_ax is not None and not isinstance(dim0_ax, SampleAxis) and same_samples:
            ds._axes[self._SAMPLE_DIM] = dim0_ax.copy()

        return ds

    # ── Slicing ────────────────────────────────────────────────────

    def __getitem__(self, key: Any) -> SherpaDataset:
        """Slice the dataset. Preserves domain, provenance, quality.

        For any dimensionality:
        ds[bool_mask]      — sample selection (dim 0)
        ds[i]              — single sample (stays nD, dim 0 kept as length 1)
        ds[1:3]            — sample slice
        ds[:, a:b]         — feature slice (dim -1); for nD, inner dims pass through
        ds[row, col]       — combined sample + feature (2D shorthand on nD)
        ds[s, i1, ..., f]  — full nD indexing (tuple length == ndim)
        """
        feature = self.get_feature_axis()
        observation = self.get_observation_axis()

        # ── Non-tuple keys: apply to dim 0 (samples) ──
        if isinstance(key, np.ndarray) and key.dtype == bool:
            new_X = self._X[key]
            new_sample = _slice_observation_axis(observation, key)
            new_target = self._target[key] if self._target is not None else None
            return self._sliced_copy(new_X, feature_axis=feature, sample_axis=new_sample, target=new_target)

        if isinstance(key, (int, np.integer)):
            new_X = self._X[key : key + 1]
            new_sample = _slice_observation_axis(observation, slice(key, key + 1))
            new_target = self._target[key : key + 1] if self._target is not None else None
            return self._sliced_copy(new_X, feature_axis=feature, sample_axis=new_sample, target=new_target)

        if isinstance(key, slice):
            new_X = self._X[key]
            new_sample = _slice_observation_axis(observation, key)
            new_target = self._target[key] if self._target is not None else None
            return self._sliced_copy(new_X, feature_axis=feature, sample_axis=new_sample, target=new_target)

        # ── Tuple keys ──
        if isinstance(key, tuple):
            if len(key) == 2 and self._X.ndim > 2:
                # 2D shorthand on nD data: (sample_key, feature_key)
                # Insert slice(None) for all inner dims
                row_key, col_key = key
                x_row = slice(row_key, row_key + 1) if isinstance(row_key, (int, np.integer)) else row_key
                x_col = slice(col_key, col_key + 1) if isinstance(col_key, (int, np.integer)) else col_key
                full_key = tuple([x_row] + [slice(None)] * (self._X.ndim - 2) + [x_col])
                new_X = self._X[full_key]
                new_sample = _slice_observation_axis(observation, row_key)
                new_feature = cast(FeatureAxis | None, _slice_axis(feature, col_key)) if feature else None
                new_target = None
                if self._target is not None:
                    try:
                        new_target = np.atleast_1d(self._target[row_key])
                    except (IndexError, TypeError):
                        pass
                return self._sliced_copy(new_X, feature_axis=new_feature, sample_axis=new_sample, target=new_target)

            if len(key) == 2:
                # Standard 2D tuple slicing
                row_key, col_key = key
                x_row = slice(row_key, row_key + 1) if isinstance(row_key, (int, np.integer)) else row_key
                x_col = slice(col_key, col_key + 1) if isinstance(col_key, (int, np.integer)) else col_key
                new_X = self._X[x_row, x_col]
                new_sample = _slice_observation_axis(observation, row_key)
                new_feature = cast(FeatureAxis | None, _slice_axis(feature, col_key)) if feature else None
                new_target = None
                if self._target is not None and not isinstance(row_key, type(None)):
                    try:
                        new_target = np.atleast_1d(self._target[row_key])
                    except (IndexError, TypeError):
                        pass
                return self._sliced_copy(new_X, feature_axis=new_feature, sample_axis=new_sample, target=new_target)

            if len(key) == self._X.ndim:
                # Full nD indexing: (sample, inner1, ..., innerN, feature)
                # Preserve dimensions by converting scalar ints to length-1 slices
                full_key_list = []
                for i, k in enumerate(key):
                    if isinstance(k, (int, np.integer)):
                        full_key_list.append(slice(k, k + 1))
                    else:
                        full_key_list.append(k)
                new_X = self._X[tuple(full_key_list)]
                row_key = key[0]
                col_key = key[-1]
                new_sample = _slice_observation_axis(observation, row_key)
                new_feature = cast(FeatureAxis | None, _slice_axis(feature, col_key)) if feature else None
                # Slice inner axes
                new_inner = {}
                for dim, ax in self._axes.items():
                    if dim in (self._SAMPLE_DIM, self._SPECTRAL_DIM):
                        continue
                    inner_key = key[dim]
                    sliced = _slice_axis(ax, inner_key)
                    if sliced is not None:
                        new_inner[dim] = sliced
                new_target = None
                if self._target is not None:
                    try:
                        new_target = np.atleast_1d(self._target[row_key])
                    except (IndexError, TypeError):
                        pass
                return self._sliced_copy(
                    new_X,
                    feature_axis=new_feature,
                    sample_axis=new_sample,
                    target=new_target,
                    inner_axes=new_inner or None,
                )

        # Fallback — slice X and try to slice sample axis
        new_X = self._X[key]
        if new_X.ndim == 0:
            new_X = new_X.reshape(1, 1)
        elif new_X.ndim == 1:
            new_X = new_X.reshape(1, -1)
        new_sample = None
        new_target = None
        try:
            if observation is not None:
                new_sample = _slice_observation_axis(observation, key)
        except Exception:
            pass
        try:
            if self._target is not None:
                new_target = self._target[key]
        except Exception:
            pass
        return self._sliced_copy(new_X, feature_axis=feature, sample_axis=new_sample, target=new_target)

    def _sliced_copy(
        self,
        X: np.ndarray,
        feature_axis: FeatureAxis | None,
        sample_axis: AxisInfo | None,
        target: np.ndarray | None,
        inner_axes: dict[int, AxisInfo] | None = None,
    ) -> SherpaDataset:
        """Create a new SherpaDataset from sliced data, preserving metadata."""
        # Default: carry forward existing inner axes if not explicitly provided
        if inner_axes is None:
            inner_axes = self.inner_axes or None
        layout_updates: dict[str, Any] = {}
        if self._layout.source_shape is not None:
            layout_updates["source_shape"] = tuple(X.shape)
        if (
            self.ndim == 2
            and self._layout.kind == "image"
            and self._layout.image_mode == 1
            and X.shape[0] != self.shape[0]
        ):
            layout_updates.update(
                {
                    "kind": "generic",
                    "source_type": "image-row-selection",
                    "image_size": None,
                    "image_mode": None,
                    "image_include": None,
                }
            )
        layout = self._layout.model_copy(deep=True, update=layout_updates)
        sliced = SherpaDataset(
            X=X,
            feature_axis=feature_axis.copy() if feature_axis else None,
            sample_axis=sample_axis if isinstance(sample_axis, SampleAxis) else None,
            axes=inner_axes,
            target=target,
            target_context=self._target_context.model_copy(deep=True),
            domain=self._domain.model_copy(deep=True),
            descriptive=self._descriptive.model_copy(deep=True),
            source_identity=self._source_identity.model_copy(deep=True),
            source_history=self._source_history.model_copy(deep=True),
            layout=layout,
            provenance=self._provenance.copy(),
            quality=self._quality.model_copy(deep=True),
            backend=self.backend,
            title=self.title,
            units=self.units,
            extra=copy.deepcopy(self._extra),
            is_time_series=self.is_time_series,
            data_role=self._data_role,
        )
        if sample_axis is not None and not isinstance(sample_axis, SampleAxis):
            sliced._axes[self._SAMPLE_DIM] = sample_axis.copy()
        return sliced

    # ── Branching ──────────────────────────────────────────────────

    def branch(self, label: str) -> SherpaDataset:
        """Create an immutable-identity branch for pipeline comparison."""
        branched = self.copy()
        branched._branch = BranchInfo(
            label=label,
            parent_dataset_id=self._dataset_id,
            parent_provenance_index=len(self._provenance),
            content_hash=hashlib.sha256(memoryview(self._X).cast("B")).hexdigest(),
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

    def to_dict(self, *, include_extra: bool = True) -> dict[str, Any]:
        """Serialize the complete current JSON-safe SherpaDataset wire."""
        safe_data = np.where(np.isfinite(self._X), self._X, None).tolist()

        has_inner = bool(self.inner_axes)

        result: dict[str, Any] = {
            "type": "SherpaDataset",
            "version": _SHERPA_DATASET_WIRE_VERSION,
            "dataset_id": self._dataset_id,
            "shape": list(self.shape),
            "ndim": self._X.ndim,
            "data": safe_data,
            "n_samples": self.shape[0],
            "n_features": self.shape[-1],
            "title": self.title,
            "units": self.units,
            "backend": self.backend,
            "data_role": self._data_role,
            "data_modality": self.data_modality,
        }

        fa = self.get_feature_axis()
        if fa is not None:
            result["feature_axis"] = _serialize_axis_typed(fa)
        if self.sample_axis:
            result["sample_axis"] = _serialize_axis(self.sample_axis)

        # Every declared inner dimension is part of the current n-D wire.
        if has_inner:
            inner_dict: dict[str, Any] = {}
            for dim, ax in self._axes.items():
                if dim not in (self._SAMPLE_DIM, self._SPECTRAL_DIM):
                    inner_dict[str(dim)] = _serialize_axis_typed(ax)
            result["inner_axes"] = inner_dict

        if self._target is not None:
            result["target"] = self._target.tolist()

        result["domain"] = self._domain.model_dump(mode="json", exclude_none=True)
        result["target_context"] = self._target_context.model_dump(mode="json", exclude_none=True)
        result["descriptive"] = self._descriptive.model_dump(mode="json", exclude_none=True)
        result["source_identity"] = self._source_identity.model_dump(mode="json", exclude_none=True)
        result["source_history"] = self._source_history.model_dump(mode="json", exclude_none=True)
        result["layout"] = self._layout.model_dump(mode="json", exclude_none=True)
        result["provenance"] = self._provenance.to_list()
        result["quality"] = _json_safe(self._quality.model_dump(exclude_none=True))
        result["state"] = self.state.model_dump(mode="json")

        if include_extra and self._extra:
            result["extra"] = _json_safe(self._extra)

        if self._branch:
            result["branch"] = self._branch.model_dump(mode="json")

        # Time-series flag
        result["is_time_series"] = self.is_time_series

        # Frontend compatibility: metadata block
        feature_axis = self.get_feature_axis()
        x_title = feature_axis.title if feature_axis is not None else None
        x_units = feature_axis.units if feature_axis is not None else None
        is_spectra = infer_is_spectra(
            technique=self._domain.technique,
            x_title=x_title,
            x_units=x_units,
        )
        result["metadata"] = {
            "processing_history": self._provenance.to_list(),
            "data_type": self._domain.technique or "generic",
            "data_role": self._data_role,
            "data_modality": self.data_modality,
            "is_spectra": is_spectra,
            "is_time_series": self.is_time_series,
        }

        return result

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SherpaDataset:
        """Deserialize the one closed current SherpaDataset wire format."""
        if not isinstance(d, dict):
            raise ValueError("SherpaDataset wire payload must be an object")
        dtype = d.get("type")
        if dtype != "SherpaDataset":
            raise ValueError(f"Expected type='SherpaDataset', got '{dtype}'")

        unknown = set(d) - _SHERPA_DATASET_WIRE_KEYS
        if unknown:
            raise ValueError(f"SherpaDataset wire payload has undeclared field(s): {sorted(unknown)}")

        version = d.get("version")
        if type(version) is not str or version != _SHERPA_DATASET_WIRE_VERSION:
            raise ValueError(f"Unsupported SherpaDataset wire version: {version!r}")
        missing = _SHERPA_DATASET_WIRE_REQUIRED_KEYS - set(d)
        if missing:
            raise ValueError(f"SherpaDataset wire payload is missing required field(s): {sorted(missing)}")

        metadata = d.get("metadata")
        if metadata is not None and not isinstance(metadata, Mapping):
            raise ValueError("SherpaDataset wire metadata must be an object")
        metadata = dict(metadata or {})
        top_role = d.get("data_role")
        metadata_role = metadata.get("data_role")
        if top_role is not None and metadata_role is not None:
            if normalize_data_role(top_role) != normalize_data_role(metadata_role):
                raise ValueError("SherpaDataset wire data_role receipts contradict each other")
        if "is_time_series" in d and "is_time_series" in metadata:
            if type(d["is_time_series"]) is not bool or type(metadata["is_time_series"]) is not bool:
                raise ValueError("SherpaDataset wire is_time_series receipts must be exact booleans")
            if d["is_time_series"] is not metadata["is_time_series"]:
                raise ValueError("SherpaDataset wire is_time_series receipts contradict each other")
        elif "is_time_series" in d and type(d["is_time_series"]) is not bool:
            raise ValueError("SherpaDataset wire is_time_series must be an exact boolean")

        feature_axis: FeatureAxis | None = None
        if d.get("feature_axis") is not None:
            feature_axis = _deserialize_typed_axis(_require_wire_mapping(d["feature_axis"], "feature_axis"))
            if not isinstance(feature_axis, FeatureAxis):
                raise ValueError("SherpaDataset feature_axis must declare a FeatureAxis subclass")

        sample_axis = (
            _deserialize_sample_axis(_require_wire_mapping(d["sample_axis"], "sample_axis"))
            if d.get("sample_axis") is not None
            else None
        )
        target = np.asarray(d["target"]) if d.get("target") is not None else None

        # Inner axes (v2+)
        inner_axes: dict[int, AxisInfo] | None = None
        if d.get("inner_axes") is not None:
            inner_payload = _require_wire_mapping(d["inner_axes"], "inner_axes")
            inner_axes = {}
            for dim_str, ax_dict in inner_payload.items():
                if not isinstance(dim_str, str) or not dim_str.isascii() or not dim_str.isdecimal():
                    raise ValueError("SherpaDataset inner_axes keys must be canonical non-negative integers")
                dim = int(dim_str)
                if dim_str != str(dim) or dim in inner_axes:
                    raise ValueError("SherpaDataset inner_axes contains an aliased or duplicate dimension")
                inner_axes[dim] = _deserialize_typed_axis(_require_wire_mapping(ax_dict, f"inner_axes[{dim_str}]"))

        domain = DomainContext.model_validate(d.get("domain", {}))
        target_context = TargetContext.model_validate(d.get("target_context", {}))
        descriptive = DatasetDescriptiveContext.model_validate(d.get("descriptive", {}))
        source_identity = DatasetSourceIdentity.model_validate(d.get("source_identity", {}))
        source_history = DatasetSourceHistory.model_validate(d.get("source_history", {}))
        layout = DatasetLayoutContext.model_validate(d.get("layout", {}))
        provenance = Provenance.from_list(d.get("provenance", []))

        quality_data = d.get("quality", {})
        quality = QualityMetrics.model_validate(quality_data) if quality_data else QualityMetrics()

        wire_time_series = d.get("is_time_series", metadata.get("is_time_series", False))
        if type(wire_time_series) is not bool:
            raise ValueError("SherpaDataset wire is_time_series must be an exact boolean")

        ds = cls(
            X=np.asarray(d["data"]),
            feature_axis=feature_axis,
            sample_axis=sample_axis,
            axes=inner_axes,
            target=target,
            target_context=target_context,
            domain=domain,
            descriptive=descriptive,
            source_identity=source_identity,
            source_history=source_history,
            layout=layout,
            provenance=provenance,
            quality=quality,
            backend=d.get("backend", "numpy"),
            title=d.get("title"),
            units=d.get("units"),
            extra=d.get("extra", {}),
            dataset_id=d.get("dataset_id"),
            is_time_series=wire_time_series,
            data_role=top_role or metadata_role,
        )

        if d.get("branch"):
            ds._branch = BranchInfo.model_validate(d["branch"])

        _validate_wire_receipts(d, metadata, ds)

        return ds

    def __repr__(self) -> str:
        tech = self._domain.technique or "unspecified"
        return f"SherpaDataset(shape={self.shape}, technique={tech!r}, backend={self.backend!r}, title={self.title!r})"


# ═══════════════════════════════════════════════════════════════════════════
# Internal Helpers
# ═══════════════════════════════════════════════════════════════════════════


_SHERPA_DATASET_WIRE_VERSION = "3.0"
_SHERPA_DATASET_WIRE_REQUIRED_KEYS = frozenset(
    {
        "type",
        "version",
        "dataset_id",
        "shape",
        "ndim",
        "data",
        "n_samples",
        "n_features",
        "title",
        "units",
        "backend",
        "data_role",
        "data_modality",
        "domain",
        "target_context",
        "descriptive",
        "source_identity",
        "source_history",
        "layout",
        "provenance",
        "quality",
        "state",
        "is_time_series",
        "metadata",
    }
)
_SHERPA_DATASET_WIRE_KEYS = frozenset(
    {
        "type",
        "version",
        "dataset_id",
        "shape",
        "ndim",
        "data",
        "n_samples",
        "n_features",
        "title",
        "units",
        "backend",
        "data_role",
        "data_modality",
        "feature_axis",
        "sample_axis",
        "inner_axes",
        "target",
        "domain",
        "target_context",
        "descriptive",
        "source_identity",
        "source_history",
        "layout",
        "provenance",
        "quality",
        "state",
        "extra",
        "branch",
        "is_time_series",
        "metadata",
    }
)


def _require_wire_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"SherpaDataset wire {field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ValueError(f"SherpaDataset wire {field_name} keys must be strings")
    return dict(value)


def _require_wire_shape(value: Any, field_name: str) -> tuple[int, ...]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"SherpaDataset wire {field_name} must be a non-empty dimension list")
    if any(type(dimension) is not int or dimension < 0 for dimension in value):
        raise ValueError(f"SherpaDataset wire {field_name} must contain exact non-negative integers")
    return tuple(value)


def _validate_wire_receipts(
    wire: Mapping[str, Any],
    metadata: Mapping[str, Any],
    dataset: SherpaDataset,
) -> None:
    """Recompute every compatibility receipt carried by the dataset wire."""
    if "shape" in wire and _require_wire_shape(wire["shape"], "shape") != tuple(dataset.shape):
        raise ValueError("SherpaDataset wire shape does not match decoded data")
    exact_integer_receipts = {
        "ndim": dataset.ndim,
        "n_samples": dataset.n_samples,
        "n_features": dataset.n_features,
    }
    for name, expected in exact_integer_receipts.items():
        if name in wire and (type(wire[name]) is not int or wire[name] != expected):
            raise ValueError(f"SherpaDataset wire {name} does not match decoded data")

    if "data_modality" in wire:
        if type(wire["data_modality"]) is not str or wire["data_modality"] != dataset.data_modality:
            raise ValueError("SherpaDataset wire data_modality does not match decoded data_role")
    if "state" in wire:
        try:
            received_state = DatasetState.model_validate(wire["state"])
        except (TypeError, ValueError) as exc:
            raise ValueError("SherpaDataset wire state is malformed") from exc
        if received_state != dataset.state:
            raise ValueError("SherpaDataset wire state does not match decoded provenance")

    processing_history = metadata.get("processing_history")
    if processing_history is not None:
        # JSON encodes provenance shape tuples as arrays; compare wire forms.
        if _json_safe(processing_history) != _json_safe(dataset.provenance.to_list()):
            raise ValueError("SherpaDataset metadata processing_history does not match provenance")
    if "data_role" in metadata:
        if normalize_data_role(metadata["data_role"]) != dataset.data_role:
            raise ValueError("SherpaDataset metadata data_role does not match decoded data_role")
    if "data_modality" in metadata:
        if type(metadata["data_modality"]) is not str or metadata["data_modality"] != dataset.data_modality:
            raise ValueError("SherpaDataset metadata data_modality does not match decoded data_role")
    if "data_type" in metadata:
        expected_data_type = dataset.domain.technique or "generic"
        if type(metadata["data_type"]) is not str or metadata["data_type"] != expected_data_type:
            raise ValueError("SherpaDataset metadata data_type does not match decoded domain")
    if "is_time_series" in metadata:
        if type(metadata["is_time_series"]) is not bool or metadata["is_time_series"] is not dataset.is_time_series:
            raise ValueError("SherpaDataset metadata is_time_series does not match decoded dataset")
    if "is_spectra" in metadata:
        if type(metadata["is_spectra"]) is not bool:
            raise ValueError("SherpaDataset metadata is_spectra must be an exact boolean")
        feature_axis = dataset.get_feature_axis()
        expected_is_spectra = infer_is_spectra(
            technique=dataset.domain.technique,
            x_title=feature_axis.title if feature_axis is not None else None,
            x_units=feature_axis.units if feature_axis is not None else None,
        )
        if metadata["is_spectra"] is not expected_is_spectra:
            raise ValueError("SherpaDataset metadata is_spectra does not match decoded dataset")


_AXIS_CLASS_MAP: dict[str, type[AxisInfo]] = {
    "AxisInfo": AxisInfo,
    "FeatureAxis": FeatureAxis,
    "SpectralAxis": SpectralAxis,
    "TimeAxis": TimeAxis,
    "MZAxis": MZAxis,
    "PotentialAxis": PotentialAxis,
    "FrequencyAxis": FrequencyAxis,
    "SampleAxis": SampleAxis,
    "SpatialAxis": SpatialAxis,
}


def _serialize_axis_typed(axis: AxisInfo) -> dict[str, Any]:
    """Serialize any axis with a type tag for polymorphic deserialization."""
    result = _serialize_axis(axis)
    result["axis_class"] = type(axis).__name__
    return result


def axis_to_wire(axis: AxisInfo, *, include_sample_table: bool = False) -> dict[str, Any]:
    """Return one complete typed axis wire without unrelated dataset arrays."""

    excluded = set() if include_sample_table else {"sample_table"}
    result = axis.model_dump(mode="json", exclude=excluded, exclude_none=True)
    if "values" in result:
        result["data"] = result.pop("values")
    result["axis_class"] = type(axis).__name__
    return _json_safe(result)


def axis_from_wire(value: Mapping[str, Any]) -> AxisInfo:
    """Admit one complete typed axis wire issued by :func:`axis_to_wire`."""

    if not isinstance(value, Mapping):
        raise ValueError("axis wire must be an object")
    return _deserialize_typed_axis(dict(value))


def _deserialize_typed_axis(d: dict[str, Any]) -> AxisInfo:
    """Deserialize an axis from a dict with an ``axis_class`` type tag."""
    class_name = d.get("axis_class", "AxisInfo")
    if type(class_name) is not str or class_name not in _AXIS_CLASS_MAP:
        raise ValueError(f"SherpaDataset wire declares unsupported axis class: {class_name!r}")
    cls = _AXIS_CLASS_MAP[class_name]
    allowed = set(cls.model_fields) - {"values"}
    allowed.update({"data", "axis_class"})
    unknown = set(d) - allowed
    if unknown:
        raise ValueError(f"SherpaDataset wire axis has undeclared field(s): {sorted(unknown)}")
    payload = {key: value for key, value in d.items() if key != "axis_class"}
    if "data" in payload:
        payload["values"] = payload.pop("data")
    return cls.model_validate(payload)


def _serialize_axis(axis: AxisInfo) -> dict[str, Any]:
    """Serialize an axis to JSON-safe dict."""
    result = axis.model_dump(mode="json", exclude_none=True)
    if "values" in result:
        result["data"] = result.pop("values")
    return _json_safe(result)


def _deserialize_sample_axis(d: dict[str, Any]) -> SampleAxis:
    allowed = set(SampleAxis.model_fields) - {"values"}
    allowed.add("data")
    unknown = set(d) - allowed
    if unknown:
        raise ValueError(f"SherpaDataset wire sample_axis has undeclared field(s): {sorted(unknown)}")
    payload = dict(d)
    if "data" in payload:
        payload["values"] = payload.pop("data")
    if payload.get("classes") is not None:
        payload["classes"] = np.asarray(payload["classes"], dtype=object)
    return SampleAxis.model_validate(payload)


def _slice_sample_axis(axis: SampleAxis | None, key: Any) -> SampleAxis | None:
    """Slice a SampleAxis along the sample dimension."""
    sliced = _slice_axis(axis, key)
    return cast(SampleAxis | None, sliced)


def _slice_observation_axis(axis: AxisInfo | None, key: Any) -> AxisInfo | None:
    """Slice dim-0 metadata without narrowing it to ``SampleAxis``."""
    if axis is None:
        return None
    if isinstance(axis, SampleAxis):
        return _slice_sample_axis(axis, key)
    if isinstance(key, slice) and key == slice(None):
        return axis.copy()
    return _slice_axis(axis, key)


def _slice_axis(axis: AxisInfo | None, key: Any) -> AxisInfo | None:
    """Slice any axis along its dimension, preserving the concrete axis type."""
    if axis is None:
        return None

    def slice_array(values: np.ndarray | None) -> np.ndarray | None:
        if values is None:
            return None
        return np.atleast_1d(values[key]).copy()

    def slice_sequence(values: Any) -> list[Any]:
        return np.atleast_1d(np.asarray(list(values), dtype=object)[key]).tolist()

    payload = axis.model_dump()
    payload["values"] = slice_array(axis.values)
    payload["labels"] = slice_sequence(axis.labels) if axis.labels is not None else None
    payload["include_mask"] = slice_array(axis.include_mask)
    payload["alternate_scales"] = tuple(
        item.model_copy(update={"values": slice_array(item.values)}) for item in axis.alternate_scales
    )
    payload["alternate_label_sets"] = tuple(
        item.model_copy(update={"values": tuple(slice_sequence(item.values))}) for item in axis.alternate_label_sets
    )
    payload["class_sets"] = tuple(
        item.model_copy(update={"values": tuple(slice_sequence(item.values))}) for item in axis.class_sets
    )
    if isinstance(axis, FeatureAxis):
        payload["selection_scores"] = slice_array(axis.selection_scores)
    if isinstance(axis, SampleAxis):
        payload["classes"] = slice_array(axis.classes)
        payload["exclusion_reasons"] = (
            slice_sequence(axis.exclusion_reasons) if axis.exclusion_reasons is not None else None
        )
        payload["sample_table"] = (
            {name: slice_sequence(values) for name, values in axis.sample_table.items()}
            if axis.sample_table is not None
            else None
        )
    sliced_axis = type(axis).model_validate(payload)
    sliced_length = 0
    for candidate in (sliced_axis.values, sliced_axis.labels, sliced_axis.include_mask):
        if candidate is not None:
            sliced_length = len(candidate)
            break
    if sliced_length == 0:
        aligned = (
            list(sliced_axis.alternate_scales) + list(sliced_axis.alternate_label_sets) + list(sliced_axis.class_sets)
        )
        if aligned:
            sliced_length = len(aligned[0].values)
    if sliced_length:
        sliced_axis.bind_expected_length(sliced_length)
    return sliced_axis
