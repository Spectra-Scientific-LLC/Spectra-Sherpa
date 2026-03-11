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
    return json.loads(metadata_path.read_text())


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
    return result.scalar_one_or_none()


async def list_experiments(
    session: AsyncSession, user_id: int | None = None, limit: int = 50, offset: int = 0
) -> list[Experiment]:
    query = select(Experiment).order_by(Experiment.created_at.desc())
    if user_id is not None:
        query = query.where(Experiment.user_id == user_id)
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
    if name is not None:
        experiment.name = name
    if description is not None:
        experiment.description = description
    if project_id is not None:
        experiment.project_id = project_id
    try:
        if metadata is not None:
            metadata_file = metadata_path_for(experiment.id)
            write_metadata(metadata_file, metadata)
            experiment.metadata_path = relative_to_data_dir(metadata_file)

        await session.commit()
    except Exception:
        await session.rollback()
        raise
    await session.refresh(experiment)
    return experiment


async def delete_experiment(session: AsyncSession, experiment: Experiment) -> None:
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
    if flush_only:
        await session.flush()
    else:
        await session.commit()
    await session.refresh(experiment_file)
    return experiment_file


def _resolve_scp_path(name: str) -> Path:
    """Resolve a SCP dataset name to its filesystem path, with boundary checks."""
    from spectra_sherpa.app.lib.scp_compat import get_scp_datadirs

    # Reject obvious traversal attempts
    if ".." in name or name.startswith("/"):
        raise ValueError(f"Invalid SCP dataset name: {name}")

    for datadir in get_scp_datadirs():
        candidate = (datadir / name.rstrip("/")).resolve()
        # Ensure resolved path stays within the datadir
        try:
            candidate.relative_to(datadir.resolve())
        except ValueError:
            raise ValueError(f"Invalid SCP dataset name: {name}")
        if candidate.exists():
            return candidate

    raise FileNotFoundError(f"SCP dataset not found: {name}")


async def import_reference_dataset(
    session: AsyncSession,
    experiment_id: int,
    source: str,
    name: str,
) -> list[ExperimentFile]:
    """Import a reference dataset into an experiment as raw files.

    For eigenvector: exports spectra (+ properties) as CSV.
    For sklearn: exports as CSV.
    For spectrochempy: copies the actual file(s) from testdata.

    All DB writes use flush_only=True so the caller can commit the full
    batch atomically.  On error, written files are cleaned up.
    """
    import shutil

    import pandas as pd

    exp_dir = experiment_dir(experiment_id)
    raw_dir = exp_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    created: list[ExperimentFile] = []
    written_files: list[Path] = []  # track for rollback

    try:
        if source == "eigenvector":
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
            resolved = _resolve_scp_path(name)
            # Namespace prefix to avoid collisions between datasets
            scp_prefix = "scp_" + name.replace("/", "_") + "_"

            if resolved.is_file():
                dest_name = scp_prefix + resolved.name
                dest = raw_dir / dest_name
                if dest.exists():
                    raise ValueError(f"File already exists: {dest_name}")
                shutil.copy2(resolved, dest)
                written_files.append(dest)
                rel = dest.relative_to(exp_dir).as_posix()
                created.append(
                    await add_experiment_file(
                        session,
                        experiment_id,
                        "raw",
                        rel,
                        dest.stat().st_size,
                        dest.suffix.lstrip(".") or None,
                        flush_only=True,
                    )
                )
            elif resolved.is_dir():
                for child in sorted(resolved.iterdir()):
                    if child.is_file() and not child.name.startswith((".", "_")):
                        dest_name = scp_prefix + child.name
                        dest = raw_dir / dest_name
                        if dest.exists():
                            raise ValueError(f"File already exists: {dest_name}")
                        shutil.copy2(child, dest)
                        written_files.append(dest)
                        rel = dest.relative_to(exp_dir).as_posix()
                        created.append(
                            await add_experiment_file(
                                session,
                                experiment_id,
                                "raw",
                                rel,
                                dest.stat().st_size,
                                child.suffix.lstrip(".") or None,
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
    return result.scalar_one_or_none()


async def delete_experiment_file(session: AsyncSession, experiment_file: ExperimentFile) -> None:
    await session.delete(experiment_file)
    await session.commit()


async def get_version_by_name(session: AsyncSession, experiment_id: int, version_name: str) -> ExpVersion | None:
    result = await session.execute(
        select(ExpVersion)
        .where(ExpVersion.experiment_id == experiment_id)
        .where(ExpVersion.version_name == version_name)
    )
    return result.scalar_one_or_none()
