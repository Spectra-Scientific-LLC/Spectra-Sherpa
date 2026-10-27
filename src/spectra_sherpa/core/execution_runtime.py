"""Explicit, immutable runtime capabilities for canonical DAG execution.

The scientific executor receives one value constructed by its caller.  It
never discovers application settings, storage singletons, or filesystem roots
while a workflow is running.  Storage implementations remain application
adapters; this module defines only the narrow behavior the DAG is allowed to
use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol


class ExecutionCapabilityError(PermissionError):
    """A workflow requested authority that its runtime does not carry."""


class PredictionUncertaintyProvider(Protocol):
    """Apply one selected sidecar already bound to the complete canonical pipeline."""

    def apply(self, predictions: Any, identity: dict[str, Any], screening: dict[str, Any]) -> dict[str, Any]: ...


class ModelArtifactReader(Protocol):
    """Read-only access to one integrity-checked legacy model artifact."""

    def load(self, artifact_uid: str, *, verify: bool = True) -> tuple[dict[str, Any], dict[str, Any]]: ...


class ModelArtifactWriter(Protocol):
    """Write access used only when a scientific node emits a model artifact."""

    def save(self, artifact_uid: str, manifest: dict[str, Any], arrays: dict[str, Any]) -> str: ...

    def artifact_directory(self, artifact_uid: str) -> str: ...


class CanonicalArtifactReader(Protocol):
    """Read one state bound to a verified canonical fitted artifact."""

    def load_bound_state(
        self,
        binding: Mapping[str, object],
        *,
        expected_source_contract_digest: str,
        expected_serializer: str,
    ) -> dict[str, object]: ...


class ModelArtifactReplay(Protocol):
    """Prepare typed input and diagnostics for one verified model artifact."""

    def prepare(
        self,
        X: Any,
        source_dataset: Any,
        manifest: dict[str, Any],
    ) -> tuple[Any, tuple[str, ...]]: ...

    def prepare_dataset(self, X: Any, source_dataset: Any, manifest: dict[str, Any]) -> tuple[Any, tuple[str, ...]]: ...

    def applicability(self, extract: Any, X: Any) -> dict[str, Any] | None: ...


class ModelArtifactSemanticValidator(Protocol):
    """Re-admit application-specific semantics after integrity-checked load."""

    def validate(self, manifest: dict[str, Any], arrays: dict[str, Any]) -> None: ...


@dataclass(frozen=True)
class ResolvedExperimentFile:
    """Application-authorized filesystem identity for one experiment file."""

    path: str
    original_file_path: str
    created_datetime: str
    file_id: int | None = None
    stage: str | None = None
    size_bytes: int | None = None
    sha256: str | None = None
    prepared_overrides: Mapping[str, object] = field(default_factory=dict)
    preloaded_dataset: Any | None = None
    preloaded_asset_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "prepared_overrides", MappingProxyType(dict(self.prepared_overrides)))


@dataclass(frozen=True)
class ResolvedExperimentCollection:
    """Application-authorized files belonging to one experiment."""

    experiment_id: int
    experiment_name: str
    files: tuple[ResolvedExperimentFile, ...]
    collection_definition_bytes: bytes | None = None
    preloaded_dataset: Any | None = None
    preloaded_asset_id: str | None = None


@dataclass(frozen=True)
class ResolvedNistLibraryEntry:
    """Application-authorized local NIST entry and its immutable metadata."""

    path: str
    relative_path: str
    compound_name: str
    cas_number: str | None = None
    resolution: str | None = None
    nist_id: str | None = None
    molecular_formula: str | None = None


class DatasetSourceResolver(Protocol):
    """Resolve application-owned source identities without doing science."""

    async def resolve_experiment_file(
        self,
        *,
        experiment_id: int,
        file_id: int,
        stage: str,
    ) -> ResolvedExperimentFile: ...

    async def resolve_experiment_collection(
        self, *, experiment_id: int, stage: str = "raw"
    ) -> ResolvedExperimentCollection: ...

    async def resolve_nist_library_entry(self, *, library_id: int) -> ResolvedNistLibraryEntry: ...


@dataclass(frozen=True)
class ExecutionRuntime:
    """Closed capabilities and policy for one executor.

    ``None`` means the authority was not granted.  The dataclass is frozen so
    code running a node cannot replace or widen a capability after admission.
    The supplied adapters may of course manage their own durable state.
    """

    node_timeout_seconds: float = 3600.0
    model_artifact_reader: ModelArtifactReader | None = None
    model_artifact_writer: ModelArtifactWriter | None = None
    worker_model_artifact_reader: ModelArtifactReader | None = None
    model_artifact_replay: ModelArtifactReplay | None = None
    model_artifact_semantic_validator: ModelArtifactSemanticValidator | None = None
    canonical_artifact_reader: CanonicalArtifactReader | None = None
    dataset_source_resolver: DatasetSourceResolver | None = None
    prediction_uncertainty: PredictionUncertaintyProvider | None = None

    def __post_init__(self) -> None:
        if self.node_timeout_seconds <= 0:
            raise ValueError("execution-runtime node timeout must be positive")

    def require_model_artifact_reader(self) -> ModelArtifactReader:
        reader = self.model_artifact_reader
        if reader is None:
            raise ExecutionCapabilityError(
                "model-artifact read capability is unavailable; import/open the model in the Workbench "
                "or provide ExecutionRuntime(model_artifact_reader=...)"
            )
        return reader

    def require_worker_model_artifact_reader(self) -> ModelArtifactReader:
        reader = self.worker_model_artifact_reader
        if reader is None:
            raise ExecutionCapabilityError("worker model-artifact read capability is unavailable")
        return reader

    def require_model_artifact_writer(self) -> ModelArtifactWriter:
        writer = self.model_artifact_writer
        if writer is None:
            raise ExecutionCapabilityError(
                "model-artifact write capability is unavailable; use the public SDK operation runner "
                "or provide ExecutionRuntime(model_artifact_writer=...)"
            )
        return writer

    def require_model_artifact_replay(self) -> ModelArtifactReplay:
        replay = self.model_artifact_replay
        if replay is None:
            raise ExecutionCapabilityError(
                "model-artifact replay capability is unavailable; import/open the model in the Workbench "
                "or provide ExecutionRuntime(model_artifact_replay=...)"
            )
        return replay

    def require_model_artifact_semantic_validator(self) -> ModelArtifactSemanticValidator:
        validator = self.model_artifact_semantic_validator
        if validator is None:
            raise ExecutionCapabilityError(
                "model-artifact semantic validation is unavailable; execute through a configured "
                "Workbench model store"
            )
        return validator

    def require_canonical_artifact_reader(self) -> CanonicalArtifactReader:
        reader = self.canonical_artifact_reader
        if reader is None:
            raise ExecutionCapabilityError(
                "canonical fitted-artifact read capability is unavailable; load the canonical project and "
                "provide ExecutionRuntime(canonical_artifact_reader=...)"
            )
        return reader

    def require_dataset_source_resolver(self) -> DatasetSourceResolver:
        resolver = self.dataset_source_resolver
        if resolver is None:
            raise ExecutionCapabilityError(
                "dataset-source resolution capability is unavailable; use deploy.input for SDK arrays "
                "or execute the application-owned data source in the Workbench"
            )
        return resolver

    def for_worker(self, capabilities: tuple[str, ...]) -> "ExecutionRuntime":
        """Project this runtime to the least authority needed by one worker."""

        model_reader = None
        if "read_model_artifact" in capabilities:
            model_reader = self.require_worker_model_artifact_reader()
        canonical_reader = None
        if "read_canonical_fitted_artifact" in capabilities:
            canonical_reader = self.require_canonical_artifact_reader()
        return ExecutionRuntime(
            node_timeout_seconds=self.node_timeout_seconds,
            model_artifact_reader=model_reader,
            model_artifact_replay=self.model_artifact_replay if model_reader is not None else None,
            model_artifact_semantic_validator=(
                self.model_artifact_semantic_validator if model_reader is not None else None
            ),
            canonical_artifact_reader=canonical_reader,
        )


__all__ = [
    "CanonicalArtifactReader",
    "DatasetSourceResolver",
    "ExecutionCapabilityError",
    "ExecutionRuntime",
    "ModelArtifactReader",
    "ModelArtifactReplay",
    "ModelArtifactSemanticValidator",
    "ModelArtifactWriter",
    "ResolvedExperimentCollection",
    "ResolvedExperimentFile",
    "ResolvedNistLibraryEntry",
]
