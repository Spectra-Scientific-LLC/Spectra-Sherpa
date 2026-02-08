from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.exp_version import ExpVersion
from app.models.experiment import Experiment
from app.models.experiment_file import ExperimentFile

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
) -> Experiment:
    experiment = Experiment(
        user_id=user_id,
        name=name,
        description=description,
        metadata_path="",
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
) -> Experiment:
    if name is not None:
        experiment.name = name
    if description is not None:
        experiment.description = description
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
) -> ExperimentFile:
    if stage not in ALLOWED_STAGES:
        raise ValueError("Invalid stage")

    experiment_file = ExperimentFile(
        experiment_id=experiment_id,
        file_path=file_path,
        file_type=file_type,
        stage=stage,
        file_size_bytes=file_size_bytes,
    )
    session.add(experiment_file)
    await session.commit()
    await session.refresh(experiment_file)
    return experiment_file


async def list_experiment_files(
    session: AsyncSession, experiment_id: int, stage: str | None = None
) -> list[ExperimentFile]:
    query = select(ExperimentFile).where(ExperimentFile.experiment_id == experiment_id)
    if stage:
        query = query.where(ExperimentFile.stage == stage)
    result = await session.execute(query)
    return list(result.scalars())


async def get_experiment_file(
    session: AsyncSession, experiment_id: int, file_id: int
) -> ExperimentFile | None:
    result = await session.execute(
        select(ExperimentFile)
        .where(ExperimentFile.experiment_id == experiment_id)
        .where(ExperimentFile.id == file_id)
    )
    return result.scalar_one_or_none()


async def delete_experiment_file(session: AsyncSession, experiment_file: ExperimentFile) -> None:
    await session.delete(experiment_file)
    await session.commit()


async def get_version_by_name(
    session: AsyncSession, experiment_id: int, version_name: str
) -> ExpVersion | None:
    result = await session.execute(
        select(ExpVersion)
        .where(ExpVersion.experiment_id == experiment_id)
        .where(ExpVersion.version_name == version_name)
    )
    return result.scalar_one_or_none()


class ExperimentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_experiment(
        self,
        user_id: int,
        name: str,
        description: str | None,
        metadata: dict[str, Any],
    ) -> Experiment:
        return await create_experiment(
            self.session,
            user_id=user_id,
            name=name,
            description=description,
            metadata=metadata,
        )

    async def get_experiment(self, experiment_id: int) -> Experiment | None:
        return await get_experiment(self.session, experiment_id)

    async def list_experiments(
        self, limit: int = 50, offset: int = 0
    ) -> list[Experiment]:
        return await list_experiments(self.session, limit=limit, offset=offset)

    async def update_experiment(
        self,
        experiment: Experiment,
        name: str | None,
        description: str | None,
        metadata: dict[str, Any] | None,
    ) -> Experiment:
        return await update_experiment(
            self.session,
            experiment=experiment,
            name=name,
            description=description,
            metadata=metadata,
        )

    async def delete_experiment(self, experiment: Experiment) -> None:
        await delete_experiment(self.session, experiment)

    async def add_file(
        self,
        experiment_id: int,
        stage: str,
        file_path: str,
        file_size_bytes: int,
        file_type: str | None,
    ) -> ExperimentFile:
        return await add_experiment_file(
            self.session,
            experiment_id=experiment_id,
            stage=stage,
            file_path=file_path,
            file_size_bytes=file_size_bytes,
            file_type=file_type,
        )

    async def list_files(
        self, experiment_id: int, stage: str | None = None
    ) -> list[ExperimentFile]:
        return await list_experiment_files(self.session, experiment_id, stage=stage)

    async def delete_file(self, experiment_file: ExperimentFile) -> None:
        await delete_experiment_file(self.session, experiment_file)

    async def get_version_by_name(
        self, experiment_id: int, version_name: str
    ) -> ExpVersion | None:
        return await get_version_by_name(
            self.session, experiment_id=experiment_id, version_name=version_name
        )
