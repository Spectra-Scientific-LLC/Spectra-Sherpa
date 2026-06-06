"""Shared workflow execution access checks.

DAG nodes run outside the FastAPI dependency stack. Any endpoint or service
that turns stored workflow rows into a DAGExecutor must validate data and
model references before execution, because individual nodes may dereference
filesystem-backed artifacts without user/project context.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.model_artifact import ModelArtifact

DATA_ACCESS_NODE_TYPES = {"data.source", "data.file_load", "data.my_dataset"}
MODEL_LOAD_NODE_TYPES = {"model.load_apply"}


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _merged_node_parameters(node: Any, initial_data: dict[str, Any] | None) -> dict[str, Any]:
    params = getattr(node, "parameters", None)
    merged = dict(params) if isinstance(params, dict) else {}
    node_id = getattr(node, "node_id", None)
    overrides = initial_data.get(node_id) if initial_data and node_id is not None else None
    if isinstance(overrides, dict):
        merged.update(overrides)
    return merged


async def require_experiment_access(
    session: AsyncSession,
    experiment_id: int,
    user_id: int,
    workflow_project_id: int | None,
) -> None:
    result = await session.execute(
        select(Experiment.id, Experiment.project_id).where(
            Experiment.id == experiment_id,
            Experiment.user_id == user_id,
        )
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    if workflow_project_id is not None and row.project_id != workflow_project_id:
        raise HTTPException(status_code=404, detail="Dataset not found in this project")


async def require_file_access(
    session: AsyncSession,
    experiment_id: int,
    file_id: int,
    user_id: int,
    stage: str | None = None,
) -> None:
    query = (
        select(ExperimentFile.id)
        .join(Experiment, ExperimentFile.experiment_id == Experiment.id)
        .where(
            Experiment.id == experiment_id,
            Experiment.user_id == user_id,
            ExperimentFile.id == file_id,
        )
    )
    if stage:
        query = query.where(ExperimentFile.stage == stage)
    result = await session.execute(query)
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Dataset file not found")


async def require_model_artifact_access(
    session: AsyncSession,
    artifact_uid: str,
    user_id: int,
    workflow_project_id: int | None,
) -> None:
    result = await session.execute(
        select(ModelArtifact.artifact_uid, ModelArtifact.project_id).where(
            ModelArtifact.artifact_uid == artifact_uid,
            ModelArtifact.user_id == user_id,
            ModelArtifact.is_active.is_(True),
        )
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Model artifact '{artifact_uid}' not found")
    if workflow_project_id is not None and row.project_id is not None and row.project_id != workflow_project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Model artifact '{artifact_uid}' is not available in this project",
        )


async def validate_workflow_execution_access(
    nodes: list[Any],
    initial_data: dict[str, Any] | None,
    user_id: int,
    workflow_project_id: int | None,
    session: AsyncSession,
) -> None:
    """Fail closed before workflow execution dereferences DB/file artifacts."""
    for node in nodes:
        node_type = getattr(node, "node_type", None)

        if node_type in MODEL_LOAD_NODE_TYPES:
            params = _merged_node_parameters(node, initial_data)
            model_id = params.get("model_id")
            if isinstance(model_id, str) and model_id:
                await require_model_artifact_access(session, model_id, user_id, workflow_project_id)
            continue

        if node_type not in DATA_ACCESS_NODE_TYPES:
            continue

        params = _merged_node_parameters(node, initial_data)
        if node_type == "data.my_dataset":
            experiment_id = _int_or_none(params.get("dataset_id"))
            if experiment_id is not None:
                await require_experiment_access(session, experiment_id, user_id, workflow_project_id)
            continue

        experiment_id = _int_or_none(params.get("experiment_id"))
        file_id = _int_or_none(params.get("file_id"))
        if experiment_id is None:
            continue

        await require_experiment_access(session, experiment_id, user_id, workflow_project_id)
        if file_id is not None:
            stage = params.get("stage")
            await require_file_access(
                session,
                experiment_id,
                file_id,
                user_id,
                stage=stage if isinstance(stage, str) else None,
            )
