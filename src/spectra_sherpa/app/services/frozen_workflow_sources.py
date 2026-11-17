"""Request-owned experiment source envelopes for exact saved-workflow admission.

Capture bytes and interpretation metadata together. Canonical source nodes still
own parsing, target selection and scientific semantics; this resolver never
falls back to live storage after capture.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import anyio
from sqlalchemy import select

from spectra_sherpa.app.lib.registered_reference_storage import read_registered_reference_sidecar
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.services.collection_definitions import read_collection_definition
from spectra_sherpa.app.services.dataset_access import require_experiment_access
from spectra_sherpa.app.services.dataset_source_resolver import ApplicationDatasetSourceResolver, _experiment_path
from spectra_sherpa.app.services.prepared_data import load_prepared_data_overrides_strict
from spectra_sherpa.core.execution_runtime import ResolvedExperimentCollection, ResolvedExperimentFile

_MAX_BYTES = 64 * 1024 * 1024
_MAX_FILES = 128


def _copy_envelope(value):
    return replace(value, prepared_overrides=copy.deepcopy(dict(value.prepared_overrides)))


class FrozenWorkflowSources:
    """Closed resolver; only explicitly captured identities can be dereferenced."""

    def __init__(self, files, collections, views):
        self._files = files
        self._collections = collections
        self._views = views

    async def resolve_experiment_file(self, *, experiment_id, file_id, stage):
        try:
            return _copy_envelope(self._files[(experiment_id, stage, file_id)])
        except KeyError as exc:
            raise ValueError("Source is outside the admitted snapshot") from exc

    async def resolve_experiment_collection(self, *, experiment_id, stage="raw"):
        try:
            value = self._collections[(experiment_id, stage)]
            return replace(value, files=tuple(_copy_envelope(item) for item in value.files))
        except KeyError as exc:
            raise ValueError("Collection is outside the admitted snapshot") from exc

    async def resolve_dataset_view(self, *, experiment_id, view_id, selection_sha256):
        try:
            return copy.deepcopy(self._views[(experiment_id, view_id, selection_sha256)])
        except KeyError as exc:
            raise ValueError("Dataset view is outside the admitted snapshot") from exc

    async def resolve_nist_library_entry(self, *, library_id):
        raise ValueError("Library sources are outside the admitted snapshot")


def _capture_file(record, root, remaining):
    path = _experiment_path(record.experiment_id, record.file_path)
    # Registered references may depend on a separate member tree. This bounded
    # envelope does not silently reinterpret a reference as an ordinary file.
    if read_registered_reference_sidecar(path) is not None:
        raise ValueError("Registered references require a complete reference snapshot")
    prepared = load_prepared_data_overrides_strict(file_path=str(path)).to_sidecar_dict()
    destination = root / str(record.id) / path.name
    destination.parent.mkdir()
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source, destination.open("xb") as target:
        for chunk in iter(lambda: source.read(min(1024 * 1024, remaining + 1)), b""):
            size += len(chunk)
            if size > remaining:
                raise ValueError("Workflow source snapshot exceeds the byte limit")
            target.write(chunk)
            digest.update(chunk)
    return ResolvedExperimentFile(
        path=str(destination),
        original_file_path=record.file_path,
        created_datetime=record.created_at.isoformat(),
        file_id=record.id,
        stage=record.stage,
        size_bytes=size,
        sha256=digest.hexdigest(),
        prepared_overrides=copy.deepcopy(prepared),
    )


async def _drained_read(function, *args):
    # Cancellation cannot delete the temporary directory while its writer is
    # still alive. This task performs only request-owned filesystem work.
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        with anyio.CancelScope(shield=True):
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
        if task.done() and not task.cancelled():
            task.exception()
        raise


@asynccontextmanager
async def freeze_workflow_sources(session, *, nodes, actor_id, project_id):
    """Capture exact file/collection bindings; caller owns admission transaction.

    Live access is checked before reading. The eventual caller must compare the
    captured identities to its approved state before committing admission. This
    function does not claim that mutable filesystem writes are transactional.
    """
    if not 1 <= len(nodes) <= 128:
        raise ValueError("Workflow snapshot node limit exceeded")
    files, collections, views = {}, {}, {}
    collection_scopes = {}
    total = 0
    source_count = 0
    with TemporaryDirectory(prefix="spectra-admitted-sources-") as directory:
        root = Path(directory)
        for node in nodes:
            if node.node_type not in {"data.file_load", "data.collection_load"}:
                continue
            source_count += 1
            if source_count > 8:
                raise ValueError("Workflow snapshot source limit exceeded")
            params = node.parameters
            experiment_id = int(params["experiment_id"])
            stage = params.get("stage", "raw")
            await require_experiment_access(session, experiment_id, actor_id, project_id)
            ids = (
                [int(params["file_id"])]
                if node.node_type == "data.file_load"
                else [int(value) for value in params.get("selected_file_ids", [])]
            )
            if not ids or len(ids) > _MAX_FILES or len(set(ids)) != len(ids):
                raise ValueError("Snapshot requires distinct explicit source members")
            records = list(
                (
                    await session.scalars(
                        select(ExperimentFile)
                        .where(
                            ExperimentFile.experiment_id == experiment_id,
                            ExperimentFile.stage == stage,
                            ExperimentFile.id.in_(ids),
                        )
                        .order_by(ExperimentFile.id)
                    )
                ).all()
            )
            if {record.id for record in records} != set(ids):
                raise ValueError("Snapshot source member unavailable")
            captured = []
            for record in records:
                key = (experiment_id, stage, record.id)
                if key not in files:
                    if len(files) >= _MAX_FILES:
                        raise ValueError("Workflow snapshot file limit exceeded")
                    files[key] = await _drained_read(_capture_file, record, root, _MAX_BYTES - total)
                    total += files[key].size_bytes
                captured.append(files[key])
            if node.node_type == "data.collection_load":
                key = (experiment_id, stage)
                scope = tuple(sorted(ids))
                if key in collection_scopes and collection_scopes[key] != scope:
                    raise ValueError("Conflicting collection scopes require separate admission")
                if key not in collections:
                    experiment = await session.get(Experiment, experiment_id)
                    definition = await _drained_read(read_collection_definition, experiment_id)
                    collections[key] = ResolvedExperimentCollection(
                        experiment_id=experiment_id,
                        experiment_name=experiment.name,
                        files=tuple(captured),
                        collection_definition_bytes=definition.canonical_bytes if definition else None,
                    )
                    collection_scopes[key] = scope
                if params.get("dataset_view_id") is not None:
                    view_key = (experiment_id, params["dataset_view_id"], params.get("dataset_view_sha256", ""))
                    if view_key not in views:
                        views[view_key] = await ApplicationDatasetSourceResolver().resolve_dataset_view(
                            experiment_id=view_key[0],
                            view_id=view_key[1],
                            selection_sha256=view_key[2],
                        )
        if not source_count:
            raise ValueError("Workflow has no supported experiment source")
        yield FrozenWorkflowSources(files, collections, views)
