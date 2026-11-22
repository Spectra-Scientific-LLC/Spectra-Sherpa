"""Project-bound projections of existing OSS facts; no interpretation or execution."""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.contracts.runtime_status import external_services_available
from spectra_sherpa.app.core.config import app_config
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


def connection_is_consent() -> bool:
    """Whether this connection's own confirmation stands in for local mode's default-off egress switch.

    Creating an inspection connection requires the user to confirm that results
    may reach the client's chosen AI provider. In local mode that confirmation is
    the consent for the connection's reads, so a user does not also have to
    enable network egress globally. An explicit EGRESS_ENABLED setting, an
    unavailable runtime, and hosted deployments keep the global switch.
    """
    return app_config.mode == "local" and not os.getenv("EGRESS_ENABLED") and external_services_available()


async def authorize_policy(session: AsyncSession, identity: InspectionIdentity, data_types: list[str]) -> User:
    """Use the existing current egress authority; no policy cache.

    The user's AI-sharing permission and any per-data-type rule still apply;
    only local mode's default global switch is replaced by the connection's
    confirmation (see ``connection_is_consent``).
    """
    from spectra_sherpa.app.services.inspection_bridge import InspectionRefused

    user = await session.scalar(
        select(User)
        .where(User.id == identity.actor_id)
        .options(selectinload(User.egress_defaults))
        .execution_options(populate_existing=True)
    )
    if user is None or not user.is_active:
        raise InspectionRefused("access_denied")
    for data_type in data_types:
        if not await check_egress_permission(
            user,
            "allow_llm_context",
            data_type=data_type,
            destination=EgressDestination.LLM_CONTEXT,
            session=session,
            skip_global_check=connection_is_consent(),
            fail_closed_on_policy_error=True,
        ):
            raise InspectionRefused("privacy_denied")
    return user


async def authorize_reader(
    session: AsyncSession, identity: InspectionIdentity, operation: str, arguments: DatasetArguments | WorkflowArguments
) -> User:
    from spectra_sherpa.app.services.inspection_bridge import InspectionRefused

    if not identity.project_summaries:
        raise InspectionRefused("project_summary_consent_required")
    data_types = [DataType.METADATA]
    if operation == "inspect_workflow":
        data_types.append(DataType.WORKFLOWS)
    user = await authorize_policy(session, identity, data_types)
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
