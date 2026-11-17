"""Project-bound projections of existing OSS facts; no interpretation or execution."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.core.security import check_egress_permission
from spectra_sherpa.app.models.data_egress import DataType, EgressDestination
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.services.inspection_grants import InspectionIdentity

MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_WORKFLOW_NODES = 500
MAX_WORKFLOW_EDGES = 1000


class DatasetArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    dataset_id: str = Field(min_length=1, max_length=128)


class WorkflowArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    workflow_id: int = Field(gt=0)


async def authorize_reader(
    session: AsyncSession, identity: InspectionIdentity, operation: str, arguments: DatasetArguments | WorkflowArguments
) -> User:
    from spectra_sherpa.app.services.inspection_bridge import InspectionRefused

    if not identity.project_summaries:
        raise InspectionRefused("project_summary_consent_required")
    user = await session.scalar(
        select(User)
        .where(User.id == identity.actor_id)
        .options(selectinload(User.egress_defaults))
        .execution_options(populate_existing=True)
    )
    if user is None or not user.is_active:
        raise InspectionRefused("access_denied")
    data_types = [DataType.METADATA]
    if operation == "inspect_workflow":
        data_types.append(DataType.WORKFLOWS)
    for data_type in data_types:
        if not await check_egress_permission(
            user,
            "allow_llm_context",
            data_type=data_type,
            destination=EgressDestination.LLM_CONTEXT,
            session=session,
            fail_closed_on_policy_error=True,
        ):
            raise InspectionRefused("privacy_denied")
    if isinstance(arguments, DatasetArguments):
        from spectra_sherpa.app.services.dataset_registry import dataset_registry

        try:
            project_id = dataset_registry.project_for_owner(arguments.dataset_id, user_id=identity.actor_id)
        except (KeyError, PermissionError) as exc:
            raise InspectionRefused("object_unavailable") from exc
        if project_id != identity.project_id:
            raise InspectionRefused("object_unavailable")
    else:
        found = await session.scalar(
            select(Workflow.id).where(
                Workflow.id == arguments.workflow_id,
                Workflow.project_id == identity.project_id,
                Workflow.user_id == identity.actor_id,
            )
        )
        if found is None:
            raise InspectionRefused("object_unavailable")
    return user


async def read_project_facts(
    sessions: async_sessionmaker[AsyncSession],
    identity: InspectionIdentity,
    operation: str,
    arguments: DatasetArguments | WorkflowArguments,
) -> dict[str, Any]:
    async with sessions() as session:
        user = await authorize_reader(session, identity, operation, arguments)
        if isinstance(arguments, WorkflowArguments):
            from spectra_sherpa.app.services.tools.builtin.workflow import inspect_workflow

            return await inspect_workflow(
                arguments.workflow_id,
                detail_level="summary",
                session=session,
                user=user,
                project_id=identity.project_id,
                max_nodes=MAX_WORKFLOW_NODES,
                max_edges=MAX_WORKFLOW_EDGES,
            )
    from spectra_sherpa.app.services.tools.builtin.datasets import describe_dataset

    return await asyncio.to_thread(
        describe_dataset,
        arguments.dataset_id,
        tier=0,
        user=SimpleNamespace(id=identity.actor_id),
        project_id=identity.project_id,
        max_snapshot_bytes=MAX_SNAPSHOT_BYTES,
    )
