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
from typing import Annotated, Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator
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
)

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
        return v  # type: ignore[no-any-return]

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
        provenance: Provenance | None = None,
        quality: QualityMetrics | None = None,
        backend: str = "numpy",
        title: str | None = None,
        units: str | None = None,
        extra: dict[str, Any] | None = None,
        dataset_id: str | None = None,
    ) -> None:
        # Core data — accept nD arrays (dim 0 = samples, dim -1 = features)
        arr = np.asarray(X, dtype=np.float64)
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
            axis_copy = feature_axis.copy()
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
            sample_copy = sample_axis.copy()
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
                ac = axis_info.copy()
                ac.bind_expected_length(expected_size)
                self._axes[normalized] = ac

        # Validate target
        if target is not None:
            t = np.asarray(target)
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
        """Alias for X — used by nodes and adapters for array access."""
        return self._X

    @property
    def shape(self) -> tuple:
        return self._X.shape  # type: ignore[return-value]

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
            t = np.asarray(value)
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
        copied = value.copy()
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
        copied = value.copy()
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
            provenance=self._provenance.copy(),
            quality=self._quality.model_copy(deep=True),
            backend=self.backend,
            title=self.title,
            units=self.units,
            extra=copy.deepcopy(self._extra),
        )

        if dim0_ax is not None and not isinstance(dim0_ax, SampleAxis):
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
        sample = self.sample_axis

        # ── Non-tuple keys: apply to dim 0 (samples) ──
        if isinstance(key, np.ndarray) and key.dtype == bool:
            new_X = self._X[key]
            new_sample = _slice_sample_axis(sample, key) if sample else None
            new_target = self._target[key] if self._target is not None else None
            return self._sliced_copy(new_X, feature_axis=feature, sample_axis=new_sample, target=new_target)

        if isinstance(key, (int, np.integer)):
            new_X = self._X[key : key + 1]
            new_sample = _slice_sample_axis(sample, slice(key, key + 1)) if sample else None
            new_target = self._target[key : key + 1] if self._target is not None else None
            return self._sliced_copy(new_X, feature_axis=feature, sample_axis=new_sample, target=new_target)

        if isinstance(key, slice):
            new_X = self._X[key]
            new_sample = _slice_sample_axis(sample, key) if sample else None
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
                new_sample = _slice_sample_axis(sample, row_key) if sample else None
                new_feature = _slice_axis(feature, col_key) if feature else None
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
                new_sample = _slice_sample_axis(sample, row_key) if sample else None
                new_feature = _slice_axis(feature, col_key) if feature else None
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
                new_sample = _slice_sample_axis(sample, row_key) if sample else None
                new_feature = _slice_axis(feature, col_key) if feature else None
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
            if sample is not None:
                new_sample = _slice_sample_axis(sample, key)
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
        sample_axis: SampleAxis | None,
        target: np.ndarray | None,
        inner_axes: dict[int, AxisInfo] | None = None,
    ) -> SherpaDataset:
        """Create a new SherpaDataset from sliced data, preserving metadata."""
        # Default: carry forward existing inner axes if not explicitly provided
        if inner_axes is None:
            inner_axes = self.inner_axes or None
        return SherpaDataset(
            X=X,
            feature_axis=feature_axis.copy() if feature_axis else None,
            sample_axis=sample_axis,  # already sliced/copied
            axes=inner_axes,
            target=target,
            target_context=self._target_context.model_copy(deep=True),
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
        """Serialize to JSON-safe dict.

        Wire format version:
        - ``"1.0"`` for 2D data with no inner axes (backward compatible)
        - ``"2.0"`` for nD data or data with inner axes
        """
        safe_data = np.where(np.isfinite(self._X), self._X, None).tolist()

        has_inner = bool(self.inner_axes)
        version = "2.0" if self._X.ndim > 2 or has_inner else "1.0"

        result: dict[str, Any] = {
            "type": "SherpaDataset",
            "version": version,
            "dataset_id": self._dataset_id,
            "shape": list(self.shape),
            "ndim": self._X.ndim,
            "data": safe_data,
            "n_samples": self.shape[0],
            "n_features": self.shape[-1],
            "title": self.title,
            "units": self.units,
            "backend": self.backend,
        }

        fa = self.get_feature_axis()
        if fa is not None:
            result["feature_axis"] = _serialize_axis_typed(fa)
        if self.sample_axis:
            result["sample_axis"] = _serialize_axis(self.sample_axis)

        # Inner axes (v2 only)
        if has_inner:
            inner_dict: dict[str, Any] = {}
            for dim, ax in self._axes.items():
                if dim not in (self._SAMPLE_DIM, self._SPECTRAL_DIM):
                    inner_dict[str(dim)] = _serialize_axis_typed(ax)
            result["inner_axes"] = inner_dict

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
        """Deserialize from SherpaDataset wire format (v1.0 and v2.0)."""
        dtype = d.get("type")
        if dtype != "SherpaDataset":
            raise ValueError(f"Expected type='SherpaDataset', got '{dtype}'")

        # version = d.get("version", "1.0")

        feature_axis: FeatureAxis | None = None
        if d.get("feature_axis"):
            feature_axis = _deserialize_typed_axis(d["feature_axis"])
            if not isinstance(feature_axis, FeatureAxis):
                feature_axis = None  # safety: must be a FeatureAxis subclass

        sample_axis = _deserialize_sample_axis(dict(d["sample_axis"])) if d.get("sample_axis") else None
        target = np.asarray(d["target"]) if d.get("target") is not None else None

        # Inner axes (v2+)
        inner_axes: dict[int, AxisInfo] | None = None
        if d.get("inner_axes"):
            inner_axes = {}
            for dim_str, ax_dict in d["inner_axes"].items():
                inner_axes[int(dim_str)] = _deserialize_typed_axis(ax_dict)

        domain = DomainContext.model_validate(d.get("domain", {}))
        target_context = TargetContext.model_validate(d.get("target_context", {}))
        provenance = Provenance.from_list(d.get("provenance", []))

        quality_data = d.get("quality", {})
        quality = QualityMetrics.model_validate(quality_data) if quality_data else QualityMetrics()

        ds = cls(
            X=np.asarray(d["data"]),
            feature_axis=feature_axis,
            sample_axis=sample_axis,
            axes=inner_axes,
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


def _deserialize_typed_axis(d: dict[str, Any]) -> AxisInfo:
    """Deserialize an axis from a dict with an ``axis_class`` type tag."""
    class_name = d.get("axis_class", "AxisInfo")
    cls = _AXIS_CLASS_MAP.get(class_name, AxisInfo)
    return cls(
        values=np.asarray(d["data"]) if d.get("data") is not None else None,
        labels=d.get("labels"),
        units=d.get("units"),
        title=d.get("title"),
    )


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


def _slice_axis(axis: AxisInfo | None, key: Any) -> AxisInfo | None:
    """Slice any axis along its dimension, preserving the concrete axis type."""
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

    # Construct same type as input axis
    return type(axis)(
        values=new_values,
        labels=new_labels,
        units=axis.units,
        title=axis.title,
    )
