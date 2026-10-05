"""Application-owned resolution of database-backed scientific data sources.

The canonical DAG receives only immutable, already-confined source records.
Database models, application settings, and sidecar storage remain on this side
of the execution boundary; parsing and scientific transformation remain in the
node implementations.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import select

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.db import session as db_session
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.nist_library import NistLibrary
from spectra_sherpa.app.services.collection_definitions import read_collection_definition
from spectra_sherpa.app.services.prepared_data import load_prepared_data_overrides
from spectra_sherpa.core.execution_runtime import (
    ResolvedExperimentCollection,
    ResolvedExperimentFile,
    ResolvedNistLibraryEntry,
)

_MAX_COLLECTION_FILES = 512
_MAX_COLLECTION_SOURCE_BYTES = 512 * 1024 * 1024
_MAX_SOURCE_FILE_BYTES = 256 * 1024 * 1024


def async_session():
    """Resolve the current application session factory when execution starts."""

    return db_session.async_session()


def _confined_path(root: Path, relative: str, *, description: str) -> Path:
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError(f"{description} path escapes the configured data directory")
    if not resolved.is_file():
        raise ValueError(f"{description} content is missing")
    return resolved


def _experiment_path(experiment_id: int, relative: str) -> Path:
    root = Path(settings.data_dir) / "experiments" / f"exp_{experiment_id:03d}"
    return _confined_path(root, relative, description=f"experiment {experiment_id} file")


def _resolved_experiment_file(record: ExperimentFile) -> ResolvedExperimentFile:
    path = _experiment_path(int(record.experiment_id), str(record.file_path))
    source_size = int(path.stat().st_size)
    if source_size > _MAX_SOURCE_FILE_BYTES:
        raise ValueError("experiment file exceeds the 256 MiB ingestion limit")
    overrides = load_prepared_data_overrides(file_path=str(path)).to_sidecar_dict()
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return ResolvedExperimentFile(
        path=str(path),
        original_file_path=str(record.file_path),
        created_datetime=record.created_at.isoformat(),
        file_id=int(record.id),
        stage=str(record.stage),
        size_bytes=source_size,
        sha256=digest.hexdigest(),
        prepared_overrides=overrides,
    )


class ApplicationDatasetSourceResolver:
    """Resolve exact local source records through application persistence."""

    def __init__(self, *, preloaded_datasets: Mapping[str, Any] | None = None) -> None:
        self._preloaded_datasets = tuple(
            getattr(value, "loaded_dataset", value) for value in (preloaded_datasets or {}).values()
        )

    def _preloaded(
        self,
        *,
        experiment_id: int,
        stage: str,
        file_id: int | None,
    ) -> Any | None:
        matches = []
        for loaded in self._preloaded_datasets:
            if int(getattr(loaded, "experiment_id", -1)) != experiment_id:
                continue
            if str(getattr(loaded, "stage", "")) != stage:
                continue
            loaded_ids = [int(value) for value in getattr(loaded, "file_ids", ())]
            if file_id is not None and loaded_ids != [file_id]:
                continue
            if file_id is None and not loaded_ids:
                continue
            matches.append(loaded)
        if not matches:
            return None
        digests = {str(match.dataset.scientific_digest) for match in matches}
        if len(digests) != 1:
            raise ValueError("execution carries conflicting preloaded dataset authorities")
        return matches[0]

    async def resolve_experiment_file(
        self,
        *,
        experiment_id: int,
        file_id: int,
        stage: str,
    ) -> ResolvedExperimentFile:
        preloaded = self._preloaded(experiment_id=experiment_id, stage=stage, file_id=file_id)
        async with async_session() as session:
            result = await session.execute(
                select(ExperimentFile).where(
                    ExperimentFile.experiment_id == experiment_id,
                    ExperimentFile.id == file_id,
                    ExperimentFile.stage == stage,
                )
            )
            record = result.scalar_one_or_none()
        if record is None:
            raise ValueError(
                f"File {file_id} not found in experiment {experiment_id} for stage {stage!r}. "
                "The file may exist in a different stage (raw/preprocessed/synthetic)."
            )
        if preloaded is None:
            return await asyncio.to_thread(_resolved_experiment_file, record)
        resolved = await asyncio.to_thread(_resolved_experiment_file, record)
        return replace(
            resolved,
            preloaded_dataset=preloaded.dataset,
            preloaded_asset_id=preloaded.asset_id,
        )

    async def resolve_experiment_collection(
        self, *, experiment_id: int, stage: str = "raw"
    ) -> ResolvedExperimentCollection:
        if stage not in {"raw", "preprocessed", "synthetic"}:
            raise ValueError("experiment collection stage is invalid")
        preloaded = self._preloaded(experiment_id=experiment_id, stage=stage, file_id=None)
        async with async_session() as session:
            experiment = await session.scalar(select(Experiment).where(Experiment.id == experiment_id))
            if experiment is None:
                raise ValueError(f"Dataset {experiment_id} not found.")
            records = list(
                (
                    await session.scalars(
                        select(ExperimentFile)
                        .where(
                            ExperimentFile.experiment_id == experiment_id,
                            ExperimentFile.stage == stage,
                        )
                        .order_by(ExperimentFile.id)
                    )
                ).all()
            )
        if len(records) > _MAX_COLLECTION_FILES:
            raise ValueError(f"experiment collection exceeds the {_MAX_COLLECTION_FILES}-file limit")
        if preloaded is not None:
            definition = await asyncio.to_thread(read_collection_definition, experiment_id)
            resolved_files = await asyncio.gather(
                *(asyncio.to_thread(_resolved_experiment_file, record) for record in records)
            )
            return ResolvedExperimentCollection(
                experiment_id=experiment_id,
                experiment_name=str(experiment.name),
                # A full collection may execute from the already-admitted in-memory
                # dataset, but a scientist can subsequently project an exact subset.
                # Every member therefore carries the same size, digest, and prepared
                # data authority as an ordinary collection read.  Preloading is a
                # performance optimization, never a weaker source contract.
                files=tuple(resolved_files),
                preloaded_dataset=preloaded.dataset,
                preloaded_asset_id=preloaded.asset_id,
                collection_definition_bytes=definition.canonical_bytes if definition is not None else None,
            )
        declared_size = sum(int(record.file_size_bytes or 0) for record in records)
        if declared_size > _MAX_COLLECTION_SOURCE_BYTES:
            raise ValueError("experiment collection exceeds the 512 MiB source limit")
        resolved_files = []
        actual_size = 0
        for record in records:
            resolved = await asyncio.to_thread(_resolved_experiment_file, record)
            actual_size += int(resolved.size_bytes or 0)
            if actual_size > _MAX_COLLECTION_SOURCE_BYTES:
                raise ValueError("experiment collection exceeds the 512 MiB source limit")
            resolved_files.append(resolved)
        return ResolvedExperimentCollection(
            experiment_id=experiment_id,
            experiment_name=str(experiment.name),
            files=tuple(resolved_files),
            collection_definition_bytes=(
                definition.canonical_bytes
                if (definition := await asyncio.to_thread(read_collection_definition, experiment_id)) is not None
                else None
            ),
            preloaded_dataset=None if preloaded is None else preloaded.dataset,
            preloaded_asset_id=None if preloaded is None else preloaded.asset_id,
        )

    async def resolve_nist_library_entry(self, *, library_id: int) -> ResolvedNistLibraryEntry:
        async with async_session() as session:
            entry = await session.scalar(select(NistLibrary).where(NistLibrary.id == library_id))
        if entry is None:
            raise ValueError(f"Library entry {library_id} not found")
        relative_path = str(entry.file_path)
        path = _confined_path(Path(settings.data_dir), relative_path, description=f"NIST entry {library_id}")
        return ResolvedNistLibraryEntry(
            path=str(path),
            relative_path=relative_path,
            compound_name=str(entry.compound_name),
            cas_number=str(entry.cas_number) if entry.cas_number is not None else None,
            resolution=str(entry.resolution) if entry.resolution is not None else None,
            nist_id=str(entry.nist_id) if getattr(entry, "nist_id", None) is not None else None,
            molecular_formula=(
                str(entry.molecular_formula) if getattr(entry, "molecular_formula", None) is not None else None
            ),
        )


__all__ = ["ApplicationDatasetSourceResolver"]
