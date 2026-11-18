"""Trusted request-local permission to use installed pack operations."""

from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from spectra_sherpa.app.lib.workflow_population import WORKFLOW_POPULATION_OPERATION
from spectra_sherpa.core.execution_runtime import ExecutionCapabilityError, ModelArtifactReader
from spectra_sherpa.core.model_artifact import ReadOnlyModelArtifactReader, parse_model_manifest_json
from spectra_sherpa.core.pack_manifest import MAX_PACKS, PackReference
from spectra_sherpa.core.pack_requirements import PackPreprocessingBinding, read_pack_preprocessing_binding

MODEL_SOURCE_IMPORTS = frozenset({"import.matlab_dso", "import.registered_reference"})
MODEL_PROVENANCE_ONLY_STEPS = MODEL_SOURCE_IMPORTS | {
    "data.file_load",
    "data.attach_target",
    "data.train_test_split",
    "data.filter_samples",
    "spectrasherpa.experiment_dataset_read/2",
    WORKFLOW_POPULATION_OPERATION,
}


class PackExecutionDenied(ExecutionCapabilityError):
    """Current permission for the required installed packs is unavailable."""


PackExecutionAuthorizer = Callable[[tuple[PackReference, ...]], Awaitable[None]]
_authorizer: ContextVar[PackExecutionAuthorizer | None] = ContextVar("pack_execution_authorizer", default=None)


@contextmanager
def use_pack_execution_authorizer(authorizer: PackExecutionAuthorizer) -> Iterator[None]:
    """Scope host authorization to the caller's operation and child tasks."""
    token = _authorizer.set(authorizer)
    try:
        yield
    finally:
        _authorizer.reset(token)


async def require_pack_execution(
    required: tuple[PackReference, ...], authorize: PackExecutionAuthorizer | None = None
) -> None:
    if not required:
        return
    if authorize is None:
        authorize = _authorizer.get()
    if authorize is None:
        packs = ", ".join(f"{pack.pack_id} {pack.version}" for pack in required)
        raise PackExecutionDenied(f"Permission to run these analysis extensions is unavailable: {packs}")
    await authorize(required)


_admitted_replay: ContextVar[tuple[PackReference, ...]] = ContextVar("pack_replay", default=())


def combine_pack_requirements(*groups: tuple[PackReference, ...]) -> tuple[PackReference, ...]:
    references: dict[str, PackReference] = {}
    for group in groups:
        for reference in group:
            if references.setdefault(reference.pack_id, reference) != reference:
                raise PackExecutionDenied("Retained analysis extensions require conflicting builds")
    if len(references) > MAX_PACKS:
        raise PackExecutionDenied("Too many retained analysis extensions")
    return tuple(references[name] for name in sorted(references))


def model_replay_requirements(
    manifest: dict[str, Any], binding: PackPreprocessingBinding | None = None
) -> tuple[PackReference, ...]:
    binding = binding if binding is not None else read_pack_preprocessing_binding(manifest)
    if binding is None:
        return ()
    chain = manifest["preprocessing_chain"]
    return combine_pack_requirements(
        *(
            step.producer.required
            for step in binding.steps
            if chain[step.step_index]["op_id"] not in MODEL_PROVENANCE_ONLY_STEPS
        )
    )


def read_model_replay_requirements(reader: ModelArtifactReader, model_id: str) -> tuple[PackReference, ...]:
    from spectra_sherpa.core.captured_model_artifacts import MAX_MODEL_MANIFEST_BYTES, CapturedModelArtifacts

    if type(reader) is CapturedModelArtifacts:
        item = next((item for item in reader.artifacts if item.artifact_uid == model_id), None)
        if item is None:
            raise FileNotFoundError("Model is outside the admitted captured inventory")
        manifest = parse_model_manifest_json(item.manifest_bytes)
    elif type(reader) is ReadOnlyModelArtifactReader:
        with (reader._artifact_dir(model_id) / "manifest.json").open("rb") as file:
            payload = file.read(MAX_MODEL_MANIFEST_BYTES + 1)
        if len(payload) > MAX_MODEL_MANIFEST_BYTES:
            raise ValueError("Model manifest exceeds the bounded replay admission limit")
        manifest = parse_model_manifest_json(payload)
    elif callable(load_manifest := getattr(reader, "load_manifest", None)):
        manifest = load_manifest(model_id)
    else:
        manifest, _ = reader.load(model_id)
    return model_replay_requirements(manifest)


@contextmanager
def use_admitted_pack_replay(required: tuple[PackReference, ...]) -> Iterator[None]:
    """Pass only exact, dispatch-admitted identities to model replay."""
    token = _admitted_replay.set(required)
    try:
        yield
    finally:
        _admitted_replay.reset(token)


def require_admitted_pack_replay(manifest: dict[str, Any]) -> PackPreprocessingBinding | None:
    binding = read_pack_preprocessing_binding(manifest)
    if binding is not None and not set(model_replay_requirements(manifest, binding)).issubset(_admitted_replay.get()):
        raise PackExecutionDenied("Permission to replay this saved model is unavailable")
    return binding
