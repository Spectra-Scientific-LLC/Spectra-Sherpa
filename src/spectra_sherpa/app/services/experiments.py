from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.models.exp_version import ExpVersion
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile

ALLOWED_STAGES = {"raw", "preprocessed", "synthetic"}


def experiment_dir(experiment_id: int) -> Path:
    return settings.data_dir / "experiments" / f"exp_{experiment_id:03d}"


def ensure_experiment_dirs(experiment_id: int) -> None:
    exp_dir = experiment_dir(experiment_id)
    (exp_dir / "objects").mkdir(parents=True, exist_ok=True)
    (exp_dir / "versions").mkdir(parents=True, exist_ok=True)


def metadata_path_for(experiment_id: int) -> Path:
    return experiment_dir(experiment_id) / "metadata.json"


def write_metadata(metadata_path: Path, metadata: dict[str, Any]) -> None:
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(metadata, indent=2, default=str))


def read_metadata(metadata_path: Path) -> dict[str, Any]:
    if not metadata_path.exists():
        return {}
    return dict(json.loads(metadata_path.read_text()))


def relative_to_data_dir(path: Path) -> str:
    return str(path.relative_to(settings.data_dir))


def resolve_data_path(relative_path: str) -> Path:
    return (settings.data_dir / relative_path).resolve()


async def create_experiment(
    session: AsyncSession,
    user_id: int,
    name: str,
    description: str | None,
    metadata: dict[str, Any],
    project_id: int | None = None,
) -> Experiment:
    experiment = Experiment(
        user_id=user_id,
        name=name,
        description=description,
        metadata_path="",
        project_id=project_id,
    )
    session.add(experiment)
    await session.flush()

    try:
        metadata_file = metadata_path_for(experiment.id)
        ensure_experiment_dirs(experiment.id)
        write_metadata(metadata_file, metadata)
        experiment.metadata_path = relative_to_data_dir(metadata_file)

        # ISO 17025 audit — experiment.created (Phase 3 coverage).
        from spectra_sherpa.app.services.audit import audit_emitter

        audit_emitter.emit(
            session=session,
            action="experiment.created",
            target_type="Experiment",
            target_id=experiment.id,
            after={"name": experiment.name, "project_id": experiment.project_id},
        )

        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await session.refresh(experiment)
    return experiment


async def get_experiment(session: AsyncSession, experiment_id: int) -> Experiment | None:
    result = await session.execute(
        select(Experiment)
        .where(Experiment.id == experiment_id)
        .options(
            selectinload(Experiment.mixtures),
            selectinload(Experiment.factor_definitions),
            selectinload(Experiment.samples),
        )
    )
    return result.scalar_one_or_none()  # type: ignore[no-any-return]


async def list_experiments(
    session: AsyncSession,
    user_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    project_id: int | None = None,
) -> list[Experiment]:
    query = select(Experiment).order_by(Experiment.created_at.desc())
    if user_id is not None:
        query = query.where(Experiment.user_id == user_id)
    if project_id is not None:
        query = query.where(Experiment.project_id == project_id)
    query = query.limit(limit).offset(offset)
    result = await session.execute(query)
    return list(result.scalars())


async def update_experiment(
    session: AsyncSession,
    experiment: Experiment,
    name: str | None,
    description: str | None,
    metadata: dict[str, Any] | None,
    project_id: int | None = None,
) -> Experiment:
    # Capture pre-mutation state for audit (Phase 3 update coverage).
    # Read pre-state metadata from disk BEFORE write_metadata overwrites
    # it — without this snapshot the audit row would prove "metadata
    # touched" without recording what actually changed (ISO 17025 §7.5
    # requires the trail to answer 'what was the old value?').
    _previous_metadata: dict[str, Any] = {}
    if experiment.metadata_path:
        try:
            _previous_metadata = read_metadata(resolve_data_path(experiment.metadata_path))
        except (OSError, ValueError, json.JSONDecodeError):
            # Unreadable metadata file = empty pre-state. Don't fail the
            # update on a corrupted/missing snapshot file; the diff just
            # shows {} → new.
            _previous_metadata = {}

    _audit_before = {
        "name": experiment.name,
        "description": experiment.description,
        "project_id": experiment.project_id,
        "metadata": _previous_metadata,
        "metadata_sha256": _canonical_metadata_sha256(_previous_metadata),
    }

    if name is not None:
        experiment.name = name
    if description is not None:
        experiment.description = description
    if project_id is not None:
        experiment.project_id = project_id
    try:
        _new_metadata: dict[str, Any] = _previous_metadata
        if metadata is not None:
            metadata_file = metadata_path_for(experiment.id)
            write_metadata(metadata_file, metadata)
            experiment.metadata_path = relative_to_data_dir(metadata_file)
            _new_metadata = metadata

        # ISO 17025 audit — experiment.updated. Emitted only when
        # something actually changed; idle PUTs don't generate noise.
        from spectra_sherpa.app.services.audit import audit_emitter

        _audit_after = {
            "name": experiment.name,
            "description": experiment.description,
            "project_id": experiment.project_id,
            "metadata": _new_metadata,
            "metadata_sha256": _canonical_metadata_sha256(_new_metadata),
        }
        if _audit_before != _audit_after:
            audit_emitter.emit(
                session=session,
                action="experiment.updated",
                target_type="Experiment",
                target_id=experiment.id,
                before=_audit_before,
                after=_audit_after,
            )

        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await session.refresh(experiment)
    return experiment


def _canonical_metadata_sha256(metadata: dict[str, Any]) -> str:
    """Stable hash for metadata equality / quick-diff in the audit trail.

    sort_keys=True so reordering keys doesn't flip the hash. Used as a
    forensic-friendly anchor: even if downstream consumers truncate the
    full ``metadata`` snapshot for storage, the hash remains a tamper-
    evident witness of the exact bytes that were live at audit time.
    """
    import hashlib

    payload = json.dumps(metadata, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


async def delete_experiment(session: AsyncSession, experiment: Experiment) -> None:
    # ISO 17025 audit — emit BEFORE delete so before_state captures
    # the row identity. Commits in the same TX as the delete.
    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="experiment.deleted",
        target_type="Experiment",
        target_id=experiment.id,
        before={"name": experiment.name, "project_id": experiment.project_id},
    )
    await session.delete(experiment)
    await session.commit()


def delete_experiment_files(experiment_id: int) -> None:
    exp_dir = experiment_dir(experiment_id)
    if exp_dir.exists():
        for path in sorted(exp_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        exp_dir.rmdir()


async def add_experiment_file(
    session: AsyncSession,
    experiment_id: int,
    stage: str,
    file_path: str,
    file_size_bytes: int,
    file_type: str | None,
    *,
    flush_only: bool = False,
) -> ExperimentFile:
    if stage not in ALLOWED_STAGES:
        raise ValueError("Invalid stage")

    # Check for duplicate file path within the same experiment/stage
    existing = await session.execute(
        select(ExperimentFile)
        .where(ExperimentFile.experiment_id == experiment_id)
        .where(ExperimentFile.file_path == file_path)
    )
    if existing.scalar_one_or_none() is not None:
        raise ValueError(f"File already exists in dataset: {file_path}")

    experiment_file = ExperimentFile(
        experiment_id=experiment_id,
        file_path=file_path,
        file_type=file_type,
        stage=stage,
        file_size_bytes=file_size_bytes,
    )
    session.add(experiment_file)
    await session.flush()  # assign file id for audit target

    # ISO 17025 audit — experiment_file.created (Phase 3 — "what data
    # was loaded into the experiment"). Commits in the same TX as the
    # ExperimentFile row whether the caller used flush_only or commit
    # path.
    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="experiment_file.created",
        target_type="ExperimentFile",
        target_id=experiment_file.id,
        after={
            "experiment_id": experiment_id,
            "file_path": file_path,
            "file_type": file_type,
            "stage": stage,
            "file_size_bytes": file_size_bytes,
        },
    )

    if not flush_only:
        await session.commit()
    await session.refresh(experiment_file)
    return experiment_file


def _resolve_scp_path(name: str) -> Path:
    """Resolve a SCP dataset name to its filesystem path, with boundary checks."""
    from spectra_sherpa.app.lib.scp_compat import resolve_scp_path

    # Reject obvious traversal attempts
    if ".." in name or name.startswith("/"):
        raise ValueError(f"Invalid SCP dataset name: {name}")

    resolved = resolve_scp_path(name.rstrip("/"))
    if resolved is not None:
        return resolved.resolve()

    raise FileNotFoundError(f"SCP dataset not found: {name}")


async def import_reference_dataset(
    session: AsyncSession,
    experiment_id: int,
    source: str,
    name: str,
) -> list[ExperimentFile]:
    """Import a reference dataset into an experiment as raw files.

    For synthetic: copies first-party NPZ artifacts into the synthetic stage.
    For eigenvector: exports spectra (+ properties) as CSV.
    For sklearn: exports as CSV.
    For spectrochempy: copies the actual file(s) from testdata.

    All DB writes use flush_only=True so the caller can commit the full
    batch atomically.  On error, written files are cleaned up.
    """
    import pandas as pd

    exp_dir = experiment_dir(experiment_id)
    raw_dir = exp_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    created: list[ExperimentFile] = []
    written_files: list[Path] = []  # track for rollback

    try:
        if source == "synthetic":
            from spectra_sherpa.app.lib.synthetic_references import (
                SYNTHETIC_REFERENCE_CATALOG,
                synthetic_reference_path,
            )

            if name not in SYNTHETIC_REFERENCE_CATALOG:
                raise ValueError(f"Unknown synthetic reference dataset: {name}")

            source_path = synthetic_reference_path(name)
            if not source_path.exists():
                raise FileNotFoundError(f"Synthetic reference dataset not found: {source_path.name}")
            synthetic_dir = exp_dir / "synthetic"
            synthetic_dir.mkdir(parents=True, exist_ok=True)
            target_name = source_path.name
            target_path = synthetic_dir / target_name
            rel = target_path.relative_to(exp_dir).as_posix()
            if target_path.exists():
                existing_result = await session.execute(
                    select(ExperimentFile).where(
                        ExperimentFile.experiment_id == experiment_id,
                        ExperimentFile.stage == "synthetic",
                        ExperimentFile.file_path == rel,
                    )
                )
                existing_file = existing_result.scalar_one_or_none()
                if existing_file is not None:
                    return [existing_file]
            target_path.write_bytes(source_path.read_bytes())
            written_files.append(target_path)
            created.append(
                await add_experiment_file(
                    session,
                    experiment_id,
                    "synthetic",
                    rel,
                    target_path.stat().st_size,
                    "npz",
                    flush_only=True,
                )
            )

        elif source == "eigenvector":
            from spectra_sherpa.app.lib.eigenvector import DATASET_CATALOG, load_eigenvector_dataset

            if name not in DATASET_CATALOG:
                raise ValueError(f"Unknown eigenvector dataset: {name}")

            result = load_eigenvector_dataset(name)
            spectra = result["spectra"]
            wavelengths = result["wavelengths"]
            columns = (
                [str(w) for w in wavelengths] if wavelengths is not None else [str(i) for i in range(spectra.shape[1])]
            )

            df = pd.DataFrame(spectra, columns=columns)

            # Append property columns so spectra + properties live in ONE file
            if result.get("properties") is not None and result.get("prop_names"):
                for i, pname in enumerate(result["prop_names"]):
                    df[pname] = result["properties"][:, i]

            if result.get("sample_ids"):
                df.index = result["sample_ids"]
                df.index.name = "sample_id"

            csv_name = f"{name}.csv"
            csv_path = raw_dir / csv_name
            if csv_path.exists():
                raise ValueError(f"File already exists: {csv_name}")
            df.to_csv(csv_path)
            written_files.append(csv_path)
            rel = csv_path.relative_to(exp_dir).as_posix()
            created.append(
                await add_experiment_file(
                    session, experiment_id, "raw", rel, csv_path.stat().st_size, "csv", flush_only=True
                )
            )

        elif source == "sklearn":
            from spectra_sherpa.app.lib.sklearn_info import _LOADERS, SKLEARN_CATALOG

            if name not in SKLEARN_CATALOG:
                raise ValueError(f"Unknown sklearn dataset: {name}")

            from sklearn import datasets as sk_datasets

            loader = getattr(sk_datasets, _LOADERS[name])
            bunch = loader()
            feature_names = list(getattr(bunch, "feature_names", []))
            if not feature_names:
                feature_names = [f"feature_{i}" for i in range(bunch.data.shape[1])]
            df = pd.DataFrame(bunch.data, columns=feature_names)
            target_names = list(getattr(bunch, "target_names", []))
            if target_names:
                df["target"] = [target_names[t] for t in bunch.target]
            else:
                df["target"] = bunch.target

            csv_name = f"sklearn_{name}.csv"
            csv_path = raw_dir / csv_name
            if csv_path.exists():
                raise ValueError(f"File already exists: {csv_name}")
            df.to_csv(csv_path, index=False)
            written_files.append(csv_path)
            rel = csv_path.relative_to(exp_dir).as_posix()
            created.append(
                await add_experiment_file(
                    session, experiment_id, "raw", rel, csv_path.stat().st_size, "csv", flush_only=True
                )
            )

        elif source == "spectrochempy":
            from spectra_sherpa.app.lib.scp_catalog import get_scp_catalog_entry, load_scp_reference_as_sherpa

            entry = get_scp_catalog_entry(name)
            dataset = load_scp_reference_as_sherpa(name)
            X = dataset.X.reshape(dataset.n_samples, dataset.n_features)
            feature_axis = dataset.get_feature_axis()
            axis_values = getattr(feature_axis, "values", None) if feature_axis is not None else None
            axis_labels = getattr(feature_axis, "labels", None) if feature_axis is not None else None
            if axis_values is not None:
                axis = [str(value) for value in axis_values]
            elif axis_labels is not None:
                axis = [str(value) for value in axis_labels]
            else:
                axis = [str(idx) for idx in range(dataset.n_features)]

            sample_axis = dataset.sample_axis
            sample_labels = list(sample_axis.labels) if sample_axis is not None and sample_axis.labels else []
            if len(sample_labels) != dataset.n_samples:
                sample_labels = [f"sample_{idx + 1}" for idx in range(dataset.n_samples)]

            x_title = getattr(feature_axis, "title", None) if feature_axis is not None else None
            x_units = getattr(feature_axis, "units", None) if feature_axis is not None else None
            axis_header = str(entry.get("x_title") or x_title or "Feature")
            if entry.get("x_units") or x_units:
                axis_header = f"{axis_header} ({entry.get('x_units') or x_units})"

            df = pd.DataFrame({axis_header: axis})
            for row, label in zip(X, sample_labels, strict=True):
                df[str(label)] = row

            csv_name = f"scp_{name.replace('/', '_')}.csv"
            csv_path = raw_dir / csv_name
            if csv_path.exists():
                raise ValueError(f"File already exists: {csv_name}")
            df.to_csv(csv_path, index=False)
            written_files.append(csv_path)
            rel = csv_path.relative_to(exp_dir).as_posix()
            created.append(
                await add_experiment_file(
                    session,
                    experiment_id,
                    "raw",
                    rel,
                    csv_path.stat().st_size,
                    "csv",
                    flush_only=True,
                )
            )
        elif source == "oes":
            from spectra_sherpa.app.lib.oes_datasets import OES_CATALOG, load_oes_dataset

            if name not in OES_CATALOG:
                raise ValueError(f"Unknown OES dataset: {name}")

            result = load_oes_dataset(name)
            spectra = result["spectra"]
            wavelengths = result["wavelengths"]

            columns = (
                [str(w) for w in wavelengths] if wavelengths is not None else [str(i) for i in range(spectra.shape[1])]
            )
            df = pd.DataFrame(spectra, columns=columns)

            if result.get("sample_ids"):
                df.index = result["sample_ids"]
                df.index.name = "sample_id"

            csv_name = f"{name}.csv"
            csv_path = raw_dir / csv_name
            if csv_path.exists():
                raise ValueError(f"File already exists: {csv_name}")
            df.to_csv(csv_path)
            written_files.append(csv_path)
            rel = csv_path.relative_to(exp_dir).as_posix()
            created.append(
                await add_experiment_file(
                    session, experiment_id, "raw", rel, csv_path.stat().st_size, "csv", flush_only=True
                )
            )

        else:
            raise ValueError(f"Unknown reference source: {source}")

    except Exception:
        # Clean up any files we wrote before the error
        for f in written_files:
            if f.exists():
                f.unlink()
        raise

    return created


async def list_experiment_files(
    session: AsyncSession, experiment_id: int, stage: str | None = None
) -> list[ExperimentFile]:
    query = select(ExperimentFile).where(ExperimentFile.experiment_id == experiment_id)
    if stage:
        query = query.where(ExperimentFile.stage == stage)
    result = await session.execute(query)
    return list(result.scalars())


async def get_experiment_file(session: AsyncSession, experiment_id: int, file_id: int) -> ExperimentFile | None:
    result = await session.execute(
        select(ExperimentFile).where(ExperimentFile.experiment_id == experiment_id).where(ExperimentFile.id == file_id)
    )
    return result.scalar_one_or_none()  # type: ignore[no-any-return]


async def delete_experiment_file(session: AsyncSession, experiment_file: ExperimentFile) -> None:
    # ISO 17025 audit — emit before delete so before_state captures
    # the row's identity (what data was removed from the experiment).
    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="experiment_file.deleted",
        target_type="ExperimentFile",
        target_id=experiment_file.id,
        before={
            "experiment_id": experiment_file.experiment_id,
            "file_path": experiment_file.file_path,
            "file_type": experiment_file.file_type,
            "stage": experiment_file.stage,
        },
    )
    await session.delete(experiment_file)
    await session.commit()


async def get_version_by_name(session: AsyncSession, experiment_id: int, version_name: str) -> ExpVersion | None:
    result = await session.execute(
        select(ExpVersion)
        .where(ExpVersion.experiment_id == experiment_id)
        .where(ExpVersion.version_name == version_name)
    )
    return result.scalar_one_or_none()  # type: ignore[no-any-return]
