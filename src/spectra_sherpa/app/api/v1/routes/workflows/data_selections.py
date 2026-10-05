"""Sheet/source-node scoped data-selection provenance."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow_data_selection_revision import WorkflowDataSelectionRevision
from spectra_sherpa.app.models.workflow_version import WorkflowVersion
from spectra_sherpa.app.schemas.workflow_data_selection import (
    WorkflowDataSelectionApply,
    WorkflowDataSelectionContext,
    WorkflowDataSelectionRevisionOut,
)
from spectra_sherpa.app.services.project_data_sources import sync_workflow_data_sources
from spectra_sherpa.app.services.run_params import build_workflow_version_snapshot
from spectra_sherpa.app.services.workflow_data_selections import (
    load_selection_context,
    next_revision_number,
    source_parameters,
    validate_selection,
    workflow_graph_digest,
)

router = APIRouter(prefix="/workflows")


def _revision_out(
    revision: WorkflowDataSelectionRevision,
    *,
    workflow_name: str,
    source_node_label: str,
    created_by_name: str,
) -> WorkflowDataSelectionRevisionOut:
    return WorkflowDataSelectionRevisionOut(
        id=revision.id,
        workflow_id=revision.workflow_id,
        workflow_name=workflow_name,
        source_node_id=revision.source_node_id,
        source_node_label=source_node_label,
        revision_number=revision.revision_number,
        parent_revision_id=revision.parent_revision_id,
        created_by=revision.created_by,
        created_by_name=created_by_name,
        created_at=revision.created_at,
        origin=revision.origin,
        reason=revision.reason,
        selection=revision.selection,
        graph_digest=revision.graph_digest,
    )


@router.get(
    "/{workflow_id}/data-selections/{source_node_id}",
    response_model=WorkflowDataSelectionContext,
)
async def get_workflow_data_selection(
    workflow_id: int,
    source_node_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDataSelectionContext:
    workflow, node, current, saved = await load_selection_context(
        session, workflow_id=workflow_id, source_node_id=source_node_id, user_id=current_user.id
    )
    current_out = None
    if current is not None:
        author_name = (
            await session.scalar(select(User.username).where(User.id == current.created_by))
            or f"User {current.created_by}"
        )
        current_out = _revision_out(
            current,
            workflow_name=workflow.name,
            source_node_label=node.label or node.node_id,
            created_by_name=author_name,
        )
    return WorkflowDataSelectionContext(
        workflow_id=workflow.id,
        workflow_name=workflow.name,
        source_node_id=node.node_id,
        source_node_label=node.label or node.node_id,
        project_id=workflow.project_id,
        current_revision=current_out,
        saved_selection=saved,
    )


@router.put(
    "/{workflow_id}/data-selections/{source_node_id}",
    response_model=WorkflowDataSelectionRevisionOut,
)
async def apply_workflow_data_selection(
    workflow_id: int,
    source_node_id: str,
    payload: WorkflowDataSelectionApply,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDataSelectionRevisionOut:
    workflow, node, current, _ = await load_selection_context(
        session,
        workflow_id=workflow_id,
        source_node_id=source_node_id,
        user_id=current_user.id,
        for_update=True,
    )
    replay = await session.scalar(
        select(WorkflowDataSelectionRevision).where(
            WorkflowDataSelectionRevision.workflow_id == workflow_id,
            WorkflowDataSelectionRevision.source_node_id == source_node_id,
            WorkflowDataSelectionRevision.idempotency_key == payload.idempotency_key,
        )
    )
    if replay is not None:
        if (
            replay.selection != payload.selection.model_dump(mode="json")
            or replay.origin != payload.origin
            or replay.reason != ((payload.reason or "").strip() or None)
        ):
            raise HTTPException(status_code=409, detail="Idempotency key was already used for another selection")
        return _revision_out(
            replay,
            workflow_name=workflow.name,
            source_node_label=node.label or node.node_id,
            created_by_name=(await session.scalar(select(User.username).where(User.id == replay.created_by)))
            or f"User {replay.created_by}",
        )
    observed_revision = current.revision_number if current is not None else None
    if payload.expected_revision != observed_revision:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Data selection changed in another edit. Reload before applying your draft.",
                "expected_revision": payload.expected_revision,
                "current_revision": observed_revision,
            },
        )
    await validate_selection(
        session,
        selection=payload.selection,
        user_id=current_user.id,
        workflow_project_id=workflow.project_id,
    )
    before = dict(node.parameters or {})
    node.parameters = source_parameters(payload.selection)
    await sync_workflow_data_sources(workflow, session, workflow.nodes)
    await session.flush()
    await session.refresh(workflow, attribute_names=["data_source_links"])
    digest = workflow_graph_digest(workflow)
    workflow.integrity_hash = digest
    revision = WorkflowDataSelectionRevision(
        workflow_id=workflow.id,
        source_node_id=node.node_id,
        revision_number=await next_revision_number(session, workflow.id, node.node_id),
        parent_revision_id=current.id if current is not None else None,
        created_by=current_user.id,
        origin=payload.origin,
        reason=(payload.reason or "").strip() or None,
        idempotency_key=payload.idempotency_key,
        selection=payload.selection.model_dump(mode="json"),
        graph_digest=digest,
    )
    session.add(revision)
    await session.flush()
    latest_version = await session.scalar(
        select(WorkflowVersion.version_number)
        .where(WorkflowVersion.workflow_id == workflow.id)
        .order_by(WorkflowVersion.version_number.desc())
        .limit(1)
    )
    session.add(
        WorkflowVersion(
            workflow_id=workflow.id,
            version_number=int(latest_version or 0) + 1,
            created_by=current_user.id,
            change_description=(
                f"Applied data selection revision {revision.revision_number} to {node.label or node.node_id}"
            ),
            snapshot=build_workflow_version_snapshot(workflow),
        )
    )
    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="workflow.data_selection.applied",
        target_type="Workflow",
        target_id=workflow.id,
        before={"source_node_id": node.node_id, "parameters": before},
        after={
            "source_node_id": node.node_id,
            "revision_id": revision.id,
            "revision_number": revision.revision_number,
            "graph_digest": digest,
            "parameters": node.parameters,
        },
        context={"origin": payload.origin, "reason": revision.reason},
    )
    await session.commit()
    await session.refresh(revision)
    return _revision_out(
        revision,
        workflow_name=workflow.name,
        source_node_label=node.label or node.node_id,
        created_by_name=current_user.username,
    )


@router.get(
    "/{workflow_id}/data-selections/{source_node_id}/revisions",
    response_model=list[WorkflowDataSelectionRevisionOut],
)
async def list_workflow_data_selection_revisions(
    workflow_id: int,
    source_node_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[WorkflowDataSelectionRevisionOut]:
    workflow, node, _, _ = await load_selection_context(
        session, workflow_id=workflow_id, source_node_id=source_node_id, user_id=current_user.id
    )
    rows = list(
        (
            await session.execute(
                select(WorkflowDataSelectionRevision)
                .where(
                    WorkflowDataSelectionRevision.workflow_id == workflow_id,
                    WorkflowDataSelectionRevision.source_node_id == source_node_id,
                )
                .options(selectinload(WorkflowDataSelectionRevision.author))
                .order_by(WorkflowDataSelectionRevision.revision_number.desc())
            )
        )
        .scalars()
        .all()
    )
    return [
        _revision_out(
            row,
            workflow_name=workflow.name,
            source_node_label=node.label or node.node_id,
            created_by_name=row.author.username,
        )
        for row in rows
    ]
