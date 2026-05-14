"""
CRUD endpoints: list / create / get / update / delete workflows.
"""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import get_current_user, get_session, require_project
from spectra_sherpa.app.models.advisor_channel import AdvisorChannel
from spectra_sherpa.app.models.project_data_source import ProjectDataSource, WorkflowDataSource
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_edge import WorkflowEdge
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.models.workflow_version import WorkflowVersion
from spectra_sherpa.app.schemas.projects import AdvisorChannelOut
from spectra_sherpa.app.schemas.workflows import (
    AIForkRequest,
    AIForkResponse,
    ReorderSheetsRequest,
    WorkflowCreate,
    WorkflowDagSpecEdge,
    WorkflowDagSpecNode,
    WorkflowDataSourcesUpdate,
    WorkflowDetail,
    WorkflowPrimaryDataSourceUpdate,
    WorkflowSummary,
    WorkflowTabColorUpdate,
    WorkflowUpdate,
)
from spectra_sherpa.app.services.dag import node_registry
from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash
from spectra_sherpa.app.services.project_data_sources import (
    effective_workflow_tab_color,
    ensure_sheet_advisor_channel,
    sync_workflow_data_sources,
)
from spectra_sherpa.app.services.tools.builtin.workflow import validate_dag_spec_for_parent

from ._helpers import _validate_edge_refs

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows")

AI_FORK_LAYOUT_START_X = 175.0
AI_FORK_LAYOUT_START_Y = 50.0
AI_FORK_LAYOUT_COLUMN_GAP = 325.0
AI_FORK_LAYOUT_ROW_GAP = 200.0
AI_FORK_MIN_NODE_GAP_X = 90.0
AI_FORK_MIN_NODE_GAP_Y = 70.0


def _dag_spec_positions_are_usable(nodes: list[WorkflowDagSpecNode]) -> bool:
    """Keep supplied positions only when every node has a non-overlapping location."""
    positions: list[tuple[float, float]] = []
    for node in nodes:
        if node.position is None:
            return False
        positions.append((node.position.x, node.position.y))

    for idx, (x1, y1) in enumerate(positions):
        for x2, y2 in positions[idx + 1 :]:
            if abs(x1 - x2) < AI_FORK_MIN_NODE_GAP_X and abs(y1 - y2) < AI_FORK_MIN_NODE_GAP_Y:
                return False
    return True


def _layout_dag_spec_nodes(
    nodes: list[WorkflowDagSpecNode],
    edges: list[WorkflowDagSpecEdge],
) -> dict[str, tuple[float, float]]:
    """Lay out an agent-generated DAG with the vertical template-style canvas flow."""
    node_ids = [node.id for node in nodes]
    original_index = {node_id: index for index, node_id in enumerate(node_ids)}
    node_id_set = set(node_ids)
    outgoing: dict[str, list[str]] = defaultdict(list)
    incoming: dict[str, list[str]] = defaultdict(list)
    indegree = {node_id: 0 for node_id in node_ids}

    for edge in edges:
        if edge.source not in node_id_set or edge.target not in node_id_set:
            continue
        outgoing[edge.source].append(edge.target)
        incoming[edge.target].append(edge.source)
        if edge.to_input != "model" and edge.from_output != "model":
            indegree[edge.target] += 1

    for targets in outgoing.values():
        targets.sort(key=lambda item: original_index[item])

    depth = {node_id: 0 for node_id in node_ids}
    ready = deque(
        sorted(
            (node_id for node_id, count in indegree.items() if count == 0),
            key=lambda item: original_index[item],
        )
    )
    seen: set[str] = set()

    while ready:
        source = ready.popleft()
        seen.add(source)
        for target in outgoing[source]:
            if any(
                edge.source == source
                and edge.target == target
                and (edge.to_input == "model" or edge.from_output == "model")
                for edge in edges
            ):
                continue
            depth[target] = max(depth[target], depth[source] + 1)
            indegree[target] -= 1
            if indegree[target] == 0:
                ready.append(target)

    # validate_workflow rejects cycles, but keep this helper total for malformed manual calls.
    for node_id in node_ids:
        if node_id not in seen:
            depth[node_id] = max(depth.values(), default=0) + 1

    layers: dict[int, list[str]] = defaultdict(list)
    for node_id in node_ids:
        layers[depth[node_id]].append(node_id)

    positions: dict[str, tuple[float, float]] = {}
    columns: dict[str, int] = {}
    for layer in sorted(layers):
        layer_node_ids = layers[layer]
        layer_node_ids.sort(key=lambda item: original_index[item])
        for default_column, node_id in enumerate(layer_node_ids):
            predecessor_columns = [columns[source] for source in incoming[node_id] if source in columns]
            column = max(predecessor_columns) if len(layer_node_ids) == 1 and predecessor_columns else default_column
            columns[node_id] = column
            positions[node_id] = (
                AI_FORK_LAYOUT_START_X + (column * AI_FORK_LAYOUT_COLUMN_GAP),
                AI_FORK_LAYOUT_START_Y + (layer * AI_FORK_LAYOUT_ROW_GAP),
            )
    return positions


def _workflow_data_source_ids(workflow: Workflow) -> list[int]:
    links = sorted(
        workflow.data_source_links,
        key=lambda link: (0 if link.role == "primary" else 1, link.id),
    )
    return [link.data_source_id for link in links]


def _workflow_advisor_channel_id(workflow: Workflow) -> int | None:
    for channel in workflow.advisor_channels:
        if channel.channel_type == "sheet":
            return channel.id
    return None


def _workflow_summary_payload(workflow: Workflow, node_count: int = 0, edge_count: int = 0) -> dict:
    return {
        "id": workflow.id,
        "user_id": workflow.user_id,
        "project_id": workflow.project_id,
        "folder_id": workflow.folder_id,
        "name": workflow.name,
        "description": workflow.description,
        "status": workflow.status,
        "canvas_state": workflow.canvas_state,
        "tab_color": effective_workflow_tab_color(workflow),
        "tab_color_override": workflow.tab_color_override,
        "color_source": workflow.color_source,
        "primary_data_source_id": workflow.primary_data_source_id,
        "data_source_ids": _workflow_data_source_ids(workflow),
        "advisor_channel_id": _workflow_advisor_channel_id(workflow),
        "created_from_template_name": workflow.created_from_template_name,
        "created_from_template_version": workflow.created_from_template_version,
        "created_from_workflow_id": workflow.created_from_workflow_id,
        "sheet_order": workflow.sheet_order,
        "created_at": workflow.created_at,
        "updated_at": workflow.updated_at,
        "last_executed_at": workflow.last_executed_at,
        "integrity_hash": workflow.integrity_hash,
        "technique": workflow.technique,
        "sample_type": workflow.sample_type,
        "node_count": node_count or 0,
        "edge_count": edge_count or 0,
        "tags": workflow.tags,
        "folder": workflow.folder,
    }


async def _project_sheet_summaries(
    project_id: int,
    user_id: int,
    session: AsyncSession,
) -> list[WorkflowSummary]:
    query = (
        select(
            Workflow,
            func.count(func.distinct(WorkflowNode.id)).label("node_count"),
            func.count(func.distinct(WorkflowEdge.id)).label("edge_count"),
        )
        .outerjoin(WorkflowNode)
        .outerjoin(WorkflowEdge)
        .where(Workflow.user_id == user_id, Workflow.project_id == project_id)
        .group_by(Workflow.id)
        .options(
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
            selectinload(Workflow.primary_data_source),
            selectinload(Workflow.data_source_links),
            selectinload(Workflow.advisor_channels),
        )
        .order_by(Workflow.sheet_order.asc(), Workflow.updated_at.desc())
    )
    result = await session.execute(query)
    rows = result.all()
    return [
        WorkflowSummary(**_workflow_summary_payload(workflow, node_count, edge_count))
        for workflow, node_count, edge_count in rows
    ]


async def _normalize_project_sheet_order(
    project_id: int,
    user_id: int,
    session: AsyncSession,
) -> None:
    result = await session.execute(
        select(Workflow)
        .where(Workflow.project_id == project_id, Workflow.user_id == user_id)
        .order_by(Workflow.sheet_order.asc(), Workflow.updated_at.desc())
    )
    for index, workflow in enumerate(result.scalars().all()):
        workflow.sheet_order = index


async def _require_project_data_source(
    data_source_id: int,
    project_id: int | None,
    session: AsyncSession,
) -> ProjectDataSource:
    if project_id is None:
        raise HTTPException(status_code=400, detail="Project is required before assigning a data source")

    result = await session.execute(
        select(ProjectDataSource).where(
            ProjectDataSource.id == data_source_id,
            ProjectDataSource.project_id == project_id,
        )
    )
    data_source = result.scalar_one_or_none()
    if data_source is None:
        raise HTTPException(status_code=404, detail="Project data source not found")
    return data_source


async def _load_workflow_for_sheet_metadata(
    workflow_id: int,
    user_id: int,
    session: AsyncSession,
) -> Workflow:
    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id, Workflow.user_id == user_id)
        .options(
            selectinload(Workflow.primary_data_source),
            selectinload(Workflow.data_source_links),
            selectinload(Workflow.advisor_channels),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if workflow.project_id is None:
        raise HTTPException(status_code=400, detail="Workflow must belong to a project")
    await require_project(workflow.project_id, user_id, session)
    return workflow


async def _apply_explicit_workflow_data_sources(
    workflow: Workflow,
    data_source_ids: list[int],
    primary_data_source_id: int | None,
    session: AsyncSession,
) -> None:
    if workflow.project_id is None:
        raise HTTPException(status_code=400, detail="Workflow must belong to a project")

    ordered_ids = list(dict.fromkeys(data_source_ids))
    if primary_data_source_id is not None and primary_data_source_id not in ordered_ids:
        ordered_ids.insert(0, primary_data_source_id)
    if ordered_ids:
        result = await session.execute(
            select(ProjectDataSource).where(
                ProjectDataSource.project_id == workflow.project_id,
                ProjectDataSource.id.in_(ordered_ids),
            )
        )
        found_ids = {data_source.id for data_source in result.scalars().all()}
        missing_ids = [data_source_id for data_source_id in ordered_ids if data_source_id not in found_ids]
        if missing_ids:
            raise HTTPException(
                status_code=404,
                detail=f"Project data source(s) not found: {', '.join(str(item) for item in missing_ids)}",
            )

    resolved_primary_id = primary_data_source_id
    if resolved_primary_id is None and ordered_ids:
        resolved_primary_id = ordered_ids[0]

    await session.execute(delete(WorkflowDataSource).where(WorkflowDataSource.workflow_id == workflow.id))
    for data_source_id in ordered_ids:
        session.add(
            WorkflowDataSource(
                workflow_id=workflow.id,
                data_source_id=data_source_id,
                role="primary" if data_source_id == resolved_primary_id else "secondary",
            )
        )

    workflow.primary_data_source_id = resolved_primary_id
    if workflow.tab_color_override:
        workflow.color_source = "manual"
    elif resolved_primary_id is not None:
        workflow.color_source = "data"
    else:
        workflow.color_source = "blank"

    await session.flush()
    await session.refresh(workflow, ["primary_data_source", "data_source_links"])
    workflow.tab_color = effective_workflow_tab_color(workflow)
    await ensure_sheet_advisor_channel(workflow, session, workflow.tab_color)


async def _workflow_detail_response(workflow_id: int, session: AsyncSession) -> WorkflowDetail:
    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
            selectinload(Workflow.primary_data_source),
            selectinload(Workflow.data_source_links),
            selectinload(Workflow.advisor_channels),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one()
    return WorkflowDetail.model_validate(workflow)


async def _unique_copy_name(
    source_name: str,
    project_id: int | None,
    user_id: int,
    session: AsyncSession,
) -> str:
    base_name = f"{source_name} (copy)"
    existing_result = await session.execute(
        select(Workflow.name).where(
            Workflow.user_id == user_id,
            Workflow.project_id == project_id,
        )
    )
    existing_names = set(existing_result.scalars().all())
    if base_name not in existing_names:
        return base_name

    suffix = 2
    while f"{base_name} ({suffix})" in existing_names:
        suffix += 1
    return f"{base_name} ({suffix})"


@router.get("", response_model=list[WorkflowSummary])
async def list_workflows(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None, description="Filter by status"),
    search: str | None = Query(None, description="Search in workflow name and description"),
    folder_id: int | None = Query(None, description="Filter by folder ID"),
    tag_ids: list[int] | None = Query(None, description="Filter by tag IDs (workflows with ANY of these tags)"),
    created_after: datetime | None = Query(None, description="Filter workflows created after this date"),
    created_before: datetime | None = Query(None, description="Filter workflows created before this date"),
    updated_after: datetime | None = Query(None, description="Filter workflows updated after this date"),
    updated_before: datetime | None = Query(None, description="Filter workflows updated before this date"),
    sort_by: str = Query("updated_at", description="Sort by field: name, created_at, updated_at"),
    sort_order: str = Query("desc", description="Sort order: asc or desc"),
    project_id: int | None = Query(None, description="Filter by project ID"),
    in_workbook: bool = Query(False, description="Return project sheet tabs ordered by sheet_order"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[WorkflowSummary]:
    """
    List all workflows for the authenticated user with comprehensive search and filtering.

    Response summaries include technique and sample_type provenance fields.

    Supports:
    - Full-text search on name and description
    - Filter by status, folder, and tags
    - Date range filtering
    - Custom sorting
    """
    user_id = current_user.id

    if in_workbook and project_id is None:
        raise HTTPException(status_code=400, detail="project_id is required when in_workbook=true")

    if project_id is not None:
        await require_project(project_id, user_id, session)

    # Build base query with tags and folder relationships
    # Use DISTINCT count to handle potential duplicates from joins
    query = (
        select(
            Workflow,
            func.count(func.distinct(WorkflowNode.id)).label("node_count"),
            func.count(func.distinct(WorkflowEdge.id)).label("edge_count"),
        )
        .outerjoin(WorkflowNode)
        .outerjoin(WorkflowEdge)
        .where(Workflow.user_id == user_id)
        .group_by(Workflow.id)
        .options(
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
            selectinload(Workflow.primary_data_source),
            selectinload(Workflow.data_source_links),
            selectinload(Workflow.advisor_channels),
        )
    )

    # Apply filters
    if status:
        query = query.where(Workflow.status == status)

    if search:
        # Full-text search on name and description
        search_pattern = f"%{search}%"
        query = query.where((Workflow.name.ilike(search_pattern)) | (Workflow.description.ilike(search_pattern)))

    if folder_id is not None:
        query = query.where(Workflow.folder_id == folder_id)

    if project_id is not None:
        query = query.where(Workflow.project_id == project_id)

    if in_workbook:
        query = query.where(Workflow.sheet_order.is_not(None))

    if tag_ids:
        # Filter workflows that have ANY of the specified tags
        # Use subquery to avoid duplicate rows in count aggregation
        from spectra_sherpa.app.models.workflow_tag import workflow_tag_association

        tag_subquery = (
            select(workflow_tag_association.c.workflow_id)
            .where(workflow_tag_association.c.tag_id.in_(tag_ids))
            .distinct()
        )
        query = query.where(Workflow.id.in_(tag_subquery))

    if created_after:
        query = query.where(Workflow.created_at >= created_after)

    if created_before:
        query = query.where(Workflow.created_at <= created_before)

    if updated_after:
        query = query.where(Workflow.updated_at >= updated_after)

    if updated_before:
        query = query.where(Workflow.updated_at <= updated_before)

    # Apply sorting. Workbook tab lists are always ordered by dense sheet order.
    if in_workbook:
        query = query.order_by(Workflow.sheet_order.asc(), Workflow.updated_at.desc())
    else:
        sort_field = {
            "name": Workflow.name,
            "created_at": Workflow.created_at,
            "updated_at": Workflow.updated_at,
        }.get(sort_by, Workflow.updated_at)

        if sort_order == "asc":
            query = query.order_by(sort_field.asc())
        else:
            query = query.order_by(sort_field.desc())

    query = query.limit(limit).offset(offset)

    result = await session.execute(query)
    rows = result.all()

    return [
        WorkflowSummary(**_workflow_summary_payload(workflow, node_count, edge_count))
        for workflow, node_count, edge_count in rows
    ]


@router.post("", response_model=WorkflowDetail, status_code=201)
async def create_workflow(
    payload: WorkflowCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDetail:
    """Create a new workflow for the authenticated user."""
    user_id = current_user.id

    if payload.project_id is not None:
        await require_project(payload.project_id, user_id, session)
    if payload.primary_data_source_id is not None:
        await _require_project_data_source(payload.primary_data_source_id, payload.project_id, session)

    max_order_query = select(func.max(Workflow.sheet_order)).where(Workflow.user_id == user_id)
    if payload.project_id is None:
        max_order_query = max_order_query.where(Workflow.project_id.is_(None))
    else:
        max_order_query = max_order_query.where(Workflow.project_id == payload.project_id)
    max_order = await session.scalar(max_order_query)
    sheet_order = (max_order if max_order is not None else -1) + 1

    # Validate all node types exist in the registry
    unknown_types = [n.node_type for n in payload.nodes if n.node_type not in node_registry]
    if unknown_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown node type(s): {', '.join(unknown_types)}",
        )

    # Validate edge references point to actual nodes
    if payload.edges:
        _validate_edge_refs(payload.nodes, payload.edges)

    # Create workflow
    workflow = Workflow(
        user_id=user_id,
        name=payload.name,
        description=payload.description,
        status=payload.status,
        canvas_state=payload.canvas_state,
        technique=payload.technique,
        sample_type=payload.sample_type,
        project_id=payload.project_id,
        tab_color=payload.tab_color,
        tab_color_override=payload.tab_color,
        color_source=payload.color_source or ("manual" if payload.tab_color else "blank"),
        primary_data_source_id=payload.primary_data_source_id,
        sheet_order=sheet_order,
    )
    session.add(workflow)
    await session.flush()  # Get workflow ID

    # Create nodes
    for node_data in payload.nodes:
        node = WorkflowNode(
            workflow_id=workflow.id,
            node_id=node_data.node_id,
            node_type=node_data.node_type,
            label=node_data.label,
            parameters=node_data.parameters,
            position_x=node_data.position_x,
            position_y=node_data.position_y,
        )
        session.add(node)

    # Create edges
    for edge_data in payload.edges:
        edge = WorkflowEdge(
            workflow_id=workflow.id,
            from_node_id=edge_data.from_node_id,
            to_node_id=edge_data.to_node_id,
            from_output=edge_data.from_output,
            to_input=edge_data.to_input,
        )
        session.add(edge)

    # Compute integrity hash from nodes/edges
    node_dicts = [n.model_dump() for n in payload.nodes]
    edge_dicts = [e.model_dump() for e in payload.edges]
    workflow.integrity_hash = compute_workflow_hash(
        nodes=node_dicts,
        edges=edge_dicts,
    )
    await sync_workflow_data_sources(workflow, session, payload.nodes)
    await ensure_sheet_advisor_channel(workflow, session, workflow.tab_color)

    # ISO 17025 audit — workflow.created with full identity + param snapshot
    # commits in the same TX as the workflow row itself (decision #9
    # fail-closed). target_id = workflow.id (assigned by the flush above).
    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="workflow.created",
        target_type="Workflow",
        target_id=workflow.id,
        after={
            "name": workflow.name,
            "project_id": workflow.project_id,
            "technique": workflow.technique,
            "integrity_hash": workflow.integrity_hash,
            "node_count": len(payload.nodes),
            "edge_count": len(payload.edges),
        },
        context={
            "parameter_set": {n.node_id: n.parameters for n in payload.nodes if n.parameters},
        },
    )

    await session.commit()
    await session.refresh(workflow)

    # Reload with relationships
    query = (
        select(Workflow)
        .where(Workflow.id == workflow.id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
            selectinload(Workflow.primary_data_source),
            selectinload(Workflow.data_source_links),
            selectinload(Workflow.advisor_channels),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one()

    return WorkflowDetail.model_validate(workflow)


@router.put("/reorder-sheets", response_model=list[WorkflowSummary])
async def reorder_sheets(
    payload: ReorderSheetsRequest,
    project_id: int = Query(..., description="Project whose workflow tabs are being reordered"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[WorkflowSummary]:
    """Persist dense sheet tab ordering for all workflows in a project."""
    user_id = current_user.id
    await require_project(project_id, user_id, session)

    result = await session.execute(
        select(Workflow).where(Workflow.project_id == project_id, Workflow.user_id == user_id)
    )
    workflows = result.scalars().all()
    workflows_by_id = {workflow.id: workflow for workflow in workflows}
    sheet_ids = {wid for wid, wf in workflows_by_id.items() if wf.sheet_order is not None}
    ordered_ids = payload.ordered_ids

    if len(ordered_ids) != len(set(ordered_ids)):
        raise HTTPException(status_code=400, detail="ordered_ids contains duplicate workflow IDs")

    # Tolerate stale clients: the payload may be missing sheets that another
    # tab/collaborator added between fetch and reorder, or include sheets
    # that have since been deleted. Filter unknown IDs out and append any
    # known sheets the client didn't see, preserving their existing order.
    known_ordered = [wid for wid in ordered_ids if wid in sheet_ids]
    missing = sorted(
        sheet_ids - set(known_ordered),
        key=lambda wid: (
            workflows_by_id[wid].sheet_order if workflows_by_id[wid].sheet_order is not None else 1_000_000,
            wid,
        ),
    )
    final_order = known_ordered + missing

    for index, workflow_id in enumerate(final_order):
        workflows_by_id[workflow_id].sheet_order = index

    await session.commit()
    return await _project_sheet_summaries(project_id, user_id, session)


@router.post("/{workflow_id}/duplicate", response_model=WorkflowDetail, status_code=201)
async def duplicate_workflow(
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDetail:
    """Clone a workflow as a new project sheet without copying runs or version history."""
    user_id = current_user.id
    source_query = (
        select(Workflow)
        .where(Workflow.id == workflow_id, Workflow.user_id == user_id)
        .options(selectinload(Workflow.nodes), selectinload(Workflow.edges))
    )
    source_result = await session.execute(source_query)
    source = source_result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if source.project_id is None:
        raise HTTPException(status_code=400, detail="Only project workflows can be duplicated as sheets")

    await require_project(source.project_id, user_id, session)
    max_order = await session.scalar(
        select(func.max(Workflow.sheet_order)).where(
            Workflow.project_id == source.project_id,
            Workflow.user_id == user_id,
        )
    )
    copy_name = await _unique_copy_name(source.name, source.project_id, user_id, session)

    duplicate = Workflow(
        user_id=user_id,
        project_id=source.project_id,
        name=copy_name,
        description=source.description,
        status=source.status,
        canvas_state=source.canvas_state,
        notes=source.notes,
        technique=source.technique,
        sample_type=source.sample_type,
        tab_color=source.tab_color,
        tab_color_override=source.tab_color_override,
        color_source=source.color_source,
        created_from_template_id=source.created_from_template_id,
        created_from_template_name=source.created_from_template_name,
        created_from_template_version=source.created_from_template_version,
        sheet_order=(max_order if max_order is not None else -1) + 1,
    )
    session.add(duplicate)
    await session.flush()

    node_dicts = []
    for node_data in source.nodes:
        node = WorkflowNode(
            workflow_id=duplicate.id,
            node_id=node_data.node_id,
            node_type=node_data.node_type,
            label=node_data.label,
            parameters=node_data.parameters,
            annotation=node_data.annotation,
            position_x=node_data.position_x,
            position_y=node_data.position_y,
        )
        session.add(node)
        node_dicts.append(
            {
                "node_id": node_data.node_id,
                "node_type": node_data.node_type,
                "label": node_data.label,
                "parameters": node_data.parameters,
                "annotation": node_data.annotation,
                "position_x": node_data.position_x,
                "position_y": node_data.position_y,
            }
        )

    edge_dicts = []
    for edge_data in source.edges:
        edge = WorkflowEdge(
            workflow_id=duplicate.id,
            from_node_id=edge_data.from_node_id,
            to_node_id=edge_data.to_node_id,
            from_output=edge_data.from_output,
            to_input=edge_data.to_input,
        )
        session.add(edge)
        edge_dicts.append(
            {
                "from_node_id": edge_data.from_node_id,
                "to_node_id": edge_data.to_node_id,
                "from_output": edge_data.from_output,
                "to_input": edge_data.to_input,
            }
        )

    duplicate.integrity_hash = compute_workflow_hash(nodes=node_dicts, edges=edge_dicts)
    await sync_workflow_data_sources(duplicate, session, source.nodes)
    await ensure_sheet_advisor_channel(duplicate, session, duplicate.tab_color)
    await session.commit()

    query = (
        select(Workflow)
        .where(Workflow.id == duplicate.id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
            selectinload(Workflow.primary_data_source),
            selectinload(Workflow.data_source_links),
            selectinload(Workflow.advisor_channels),
        )
    )
    result = await session.execute(query)
    duplicate = result.scalar_one()
    return WorkflowDetail.model_validate(duplicate)


@router.put("/{workflow_id}/data-sources", response_model=WorkflowDetail)
async def update_workflow_data_sources(
    workflow_id: int,
    payload: WorkflowDataSourcesUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDetail:
    """Explicitly set the project data sources associated with a workflow sheet."""
    workflow = await _load_workflow_for_sheet_metadata(workflow_id, current_user.id, session)
    await _apply_explicit_workflow_data_sources(
        workflow,
        payload.data_source_ids,
        payload.primary_data_source_id,
        session,
    )
    await session.commit()
    return await _workflow_detail_response(workflow_id, session)


@router.put("/{workflow_id}/primary-data-source", response_model=WorkflowDetail)
async def update_workflow_primary_data_source(
    workflow_id: int,
    payload: WorkflowPrimaryDataSourceUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDetail:
    """Change the workflow sheet's primary project data source."""
    workflow = await _load_workflow_for_sheet_metadata(workflow_id, current_user.id, session)
    existing_ids = _workflow_data_source_ids(workflow)
    await _apply_explicit_workflow_data_sources(
        workflow,
        existing_ids,
        payload.primary_data_source_id,
        session,
    )
    await session.commit()
    return await _workflow_detail_response(workflow_id, session)


@router.put("/{workflow_id}/tab-color", response_model=WorkflowDetail)
async def update_workflow_tab_color(
    workflow_id: int,
    payload: WorkflowTabColorUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDetail:
    """Set or clear the manual sheet tab color override."""
    workflow = await _load_workflow_for_sheet_metadata(workflow_id, current_user.id, session)
    workflow.tab_color_override = payload.tab_color
    workflow.color_source = "manual" if payload.tab_color else ("data" if workflow.primary_data_source_id else "blank")
    workflow.tab_color = effective_workflow_tab_color(workflow)
    await ensure_sheet_advisor_channel(workflow, session, workflow.tab_color)
    await session.commit()
    return await _workflow_detail_response(workflow_id, session)


@router.post("/{workflow_id}/advisor-channel", response_model=AdvisorChannelOut, status_code=201)
async def create_or_get_workflow_advisor_channel(
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> AdvisorChannelOut:
    """Ensure and return the Sherpa Advisor channel dedicated to this workflow sheet."""
    workflow = await _load_workflow_for_sheet_metadata(workflow_id, current_user.id, session)
    channel = await ensure_sheet_advisor_channel(workflow, session, workflow.tab_color)
    if channel is None:
        raise HTTPException(status_code=400, detail="Workflow must belong to a project")
    await session.commit()
    await session.refresh(channel)
    return AdvisorChannelOut.model_validate(channel)


@router.get("/{workflow_id}", response_model=WorkflowDetail)
async def get_workflow(
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDetail:
    """Get a specific workflow by ID for the authenticated user."""
    user_id = current_user.id

    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .where(Workflow.user_id == user_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.primary_data_source),
            selectinload(Workflow.data_source_links),
            selectinload(Workflow.advisor_channels),
            selectinload(Workflow.folder),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    return WorkflowDetail.model_validate(workflow)


@router.put("/{workflow_id}", response_model=WorkflowDetail)
async def update_workflow(
    workflow_id: int,
    payload: WorkflowUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDetail:
    """Update a workflow for the authenticated user."""
    user_id = current_user.id

    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .where(Workflow.user_id == user_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.primary_data_source),
            selectinload(Workflow.data_source_links),
            selectinload(Workflow.advisor_channels),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Capture before-state for audit. Pre-mutation snapshot of fields
    # the route is allowed to change. Picked to support reproducibility
    # of "what changed" without dumping the entire row.
    _audit_before = {
        "name": workflow.name,
        "status": workflow.status,
        "integrity_hash": workflow.integrity_hash,
        "node_count": len(workflow.nodes or []),
        "parameter_set": {n.node_id: n.parameters for n in (workflow.nodes or []) if n.parameters},
    }

    if payload.nodes is not None:
        node_types = [n.node_type for n in payload.nodes]
        unknown_types = [node_type for node_type in node_types if node_type not in node_registry]
        if unknown_types:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown node type(s): {', '.join(unknown_types)}",
            )

    # Update workflow fields
    if payload.name is not None:
        workflow.name = payload.name
    if payload.description is not None:
        workflow.description = payload.description
    if payload.status is not None:
        workflow.status = payload.status
    if payload.canvas_state is not None:
        workflow.canvas_state = payload.canvas_state
    if payload.notes is not None:
        workflow.notes = payload.notes
    if payload.folder_id is not None:
        workflow.folder_id = payload.folder_id
    if payload.technique is not None:
        workflow.technique = payload.technique
    if payload.sample_type is not None:
        workflow.sample_type = payload.sample_type
    if payload.primary_data_source_id is not None:
        data_source = await _require_project_data_source(payload.primary_data_source_id, workflow.project_id, session)
        workflow.primary_data_source_id = payload.primary_data_source_id
        workflow.primary_data_source = data_source
        if not workflow.tab_color_override:
            workflow.color_source = "data"
    if payload.color_source is not None:
        workflow.color_source = payload.color_source
    if "tab_color" in payload.model_fields_set:
        workflow.tab_color_override = payload.tab_color
        workflow.color_source = "manual" if payload.tab_color else "blank"
    if "tab_color_override" in payload.model_fields_set:
        workflow.tab_color_override = payload.tab_color_override
        workflow.color_source = "manual" if payload.tab_color_override else "blank"

    # Update tags if provided
    if payload.tag_ids is not None:
        from spectra_sherpa.app.models.workflow_tag import WorkflowTag

        # Clear existing tags
        workflow.tags = []

        # Add new tags
        if payload.tag_ids:
            tag_query = (
                select(WorkflowTag).where(WorkflowTag.id.in_(payload.tag_ids)).where(WorkflowTag.user_id == user_id)
            )
            tag_result = await session.execute(tag_query)
            tags = tag_result.scalars().all()
            workflow.tags = list(tags)

    # Update nodes if provided
    if payload.nodes is not None:
        # Clear via ORM relationship (delete-orphan cascade handles DB deletion)
        workflow.nodes.clear()

        # Create new nodes through the relationship
        for node_data in payload.nodes:
            node = WorkflowNode(
                workflow_id=workflow.id,
                node_id=node_data.node_id,
                node_type=node_data.node_type,
                label=node_data.label,
                parameters=node_data.parameters,
                position_x=node_data.position_x,
                position_y=node_data.position_y,
            )
            workflow.nodes.append(node)

    # Update edges if provided
    if payload.edges is not None:
        # Validate edge references against the node set (new or existing)
        ref_nodes = payload.nodes if payload.nodes is not None else workflow.nodes
        _validate_edge_refs(ref_nodes, payload.edges)

        # Clear via ORM relationship (delete-orphan cascade handles DB deletion)
        workflow.edges.clear()

        # Create new edges through the relationship
        for edge_data in payload.edges:
            edge = WorkflowEdge(
                workflow_id=workflow.id,
                from_node_id=edge_data.from_node_id,
                to_node_id=edge_data.to_node_id,
                from_output=edge_data.from_output,
                to_input=edge_data.to_input,
            )
            workflow.edges.append(edge)

    # Recompute integrity hash if nodes or edges changed
    if payload.nodes is not None or payload.edges is not None:
        hash_nodes = (
            [n.model_dump() for n in payload.nodes]
            if payload.nodes
            else (
                [{"node_id": n.node_id, "node_type": n.node_type, "parameters": n.parameters} for n in workflow.nodes]
                if hasattr(workflow, "nodes")
                else []
            )
        )
        hash_edges = (
            [e.model_dump() for e in payload.edges]
            if payload.edges
            else (
                [
                    {
                        "from_node_id": e.from_node_id,
                        "to_node_id": e.to_node_id,
                        "from_output": e.from_output,
                        "to_input": e.to_input,
                    }
                    for e in workflow.edges
                ]
                if hasattr(workflow, "edges")
                else []
            )
        )
        workflow.integrity_hash = compute_workflow_hash(hash_nodes, hash_edges)

    if (
        payload.nodes is not None
        or "tab_color" in payload.model_fields_set
        or "tab_color_override" in payload.model_fields_set
    ):
        await sync_workflow_data_sources(workflow, session, payload.nodes)
    else:
        workflow.tab_color = effective_workflow_tab_color(workflow)
    await ensure_sheet_advisor_channel(workflow, session, workflow.tab_color)

    # Flush changes to database before creating snapshot
    await session.flush()

    if payload.create_version:
        # Reload workflow with all current relationships to capture actual state
        snapshot_query = (
            select(Workflow)
            .where(Workflow.id == workflow_id)
            .options(
                selectinload(Workflow.nodes),
                selectinload(Workflow.edges),
                selectinload(Workflow.tags),
                selectinload(Workflow.folder),
                selectinload(Workflow.primary_data_source),
                selectinload(Workflow.data_source_links),
                selectinload(Workflow.advisor_channels),
            )
        )
        snapshot_result = await session.execute(snapshot_query)
        workflow_with_relationships = snapshot_result.scalar_one()

        # Create version snapshot from actual workflow state in database
        # Get the latest version number for this workflow
        latest_version_query = select(func.max(WorkflowVersion.version_number)).where(
            WorkflowVersion.workflow_id == workflow_id
        )
        latest_version_result = await session.execute(latest_version_query)
        latest_version = latest_version_result.scalar() or 0
        new_version_number = latest_version + 1

        # Create snapshot of current workflow state from database
        snapshot = {
            "name": workflow_with_relationships.name,
            "description": workflow_with_relationships.description,
            "status": workflow_with_relationships.status,
            "canvas_state": workflow_with_relationships.canvas_state,
            "notes": workflow_with_relationships.notes,
            "integrity_hash": workflow_with_relationships.integrity_hash,
            "technique": workflow_with_relationships.technique,
            "sample_type": workflow_with_relationships.sample_type,
            "tab_color": workflow_with_relationships.tab_color,
            "tab_color_override": workflow_with_relationships.tab_color_override,
            "color_source": workflow_with_relationships.color_source,
            "primary_data_source_id": workflow_with_relationships.primary_data_source_id,
            "data_source_ids": workflow_with_relationships.data_source_ids,
            "created_from_template_name": workflow_with_relationships.created_from_template_name,
            "created_from_template_version": workflow_with_relationships.created_from_template_version,
            "sheet_order": workflow_with_relationships.sheet_order,
            "nodes": [
                {
                    "node_id": n.node_id,
                    "node_type": n.node_type,
                    "label": n.label,
                    "parameters": n.parameters,
                    "annotation": n.annotation,
                    "position_x": n.position_x,
                    "position_y": n.position_y,
                }
                for n in workflow_with_relationships.nodes
            ],
            "edges": [
                {
                    "from_node_id": e.from_node_id,
                    "to_node_id": e.to_node_id,
                    "from_output": e.from_output,
                    "to_input": e.to_input,
                }
                for e in workflow_with_relationships.edges
            ],
        }

        version = WorkflowVersion(
            workflow_id=workflow_id,
            version_number=new_version_number,
            created_by=user_id,
            change_description=payload.change_description if hasattr(payload, "change_description") else None,
            snapshot=snapshot,
        )
        session.add(version)
        await session.flush()  # assign version.id for audit

        # ISO 17025 audit — workflow_version.created with the full
        # parameter-set snapshot in the context payload.
        from spectra_sherpa.app.services.audit import audit_emitter

        audit_emitter.emit(
            session=session,
            action="workflow_version.created",
            target_type="WorkflowVersion",
            target_id=version.id,
            after={
                "workflow_id": workflow_id,
                "version_number": new_version_number,
                "change_description": version.change_description,
                "integrity_hash": snapshot.get("integrity_hash"),
                "node_count": len(snapshot.get("nodes", [])),
                "edge_count": len(snapshot.get("edges", [])),
            },
            context={
                "parameter_set": {
                    n["node_id"]: n["parameters"] for n in snapshot.get("nodes", []) if n.get("parameters")
                },
            },
        )

    # ISO 17025 audit — workflow.updated. Captures the before-snapshot
    # taken at load time and the after-snapshot from the now-mutated
    # workflow row, so an auditor can reconstruct the parameter delta
    # for the run that follows. Commits with the row update (fail-closed).
    from spectra_sherpa.app.services.audit import audit_emitter as _audit_emitter

    _audit_after = {
        "name": workflow.name,
        "status": workflow.status,
        "integrity_hash": workflow.integrity_hash,
        "node_count": len(workflow.nodes or []),
        "parameter_set": {n.node_id: n.parameters for n in (workflow.nodes or []) if n.parameters},
    }
    _audit_emitter.emit(
        session=session,
        action="workflow.updated",
        target_type="Workflow",
        target_id=workflow_id,
        before=_audit_before,
        after=_audit_after,
    )

    await session.commit()

    # Reload with relationships for response
    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
            selectinload(Workflow.primary_data_source),
            selectinload(Workflow.data_source_links),
            selectinload(Workflow.advisor_channels),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one()

    return WorkflowDetail.model_validate(workflow)


@router.delete("/{workflow_id}", status_code=204, response_class=Response)
async def delete_workflow(
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete a workflow for the authenticated user."""
    user_id = current_user.id

    query = select(Workflow).where(Workflow.id == workflow_id).where(Workflow.user_id == user_id)
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    project_id = workflow.project_id

    # ISO 17025 audit — emit BEFORE the delete so before_state captures
    # the row's identity. The audit row commits in the same TX as the
    # delete (fail-closed).
    from spectra_sherpa.app.services.audit import audit_emitter

    audit_emitter.emit(
        session=session,
        action="workflow.deleted",
        target_type="Workflow",
        target_id=workflow_id,
        before={
            "name": workflow.name,
            "project_id": project_id,
            "integrity_hash": workflow.integrity_hash,
        },
    )

    await session.delete(workflow)
    if project_id is not None:
        await session.flush()
        await _normalize_project_sheet_order(project_id, user_id, session)
    await session.commit()


@router.post("/{workflow_id}/ai-fork", response_model=AIForkResponse)
async def ai_fork_workflow(
    workflow_id: int,
    payload: AIForkRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Agentic Workflow Generation endpoint.
    Forks an existing workflow, creates a new one with the proposed DAG,
    and binds it to a pre-created conversation_id.
    """
    from spectra_sherpa.app.contracts.ai_provider_registry import get_sherpa_advisor

    user_id = current_user.id
    provider = get_sherpa_advisor()
    has_agentic_tools = getattr(provider, "has_feature", lambda _feature: False)("agentic_tools")
    if not provider.is_available or not has_agentic_tools:
        raise HTTPException(status_code=403, detail="SherpaAdvisor is not available.")

    # Idempotency check: if a channel already exists for this conversation_id,
    # return it only when it belongs to the current user's workflow.
    existing_channel_query = select(AdvisorChannel).where(AdvisorChannel.conversation_id == payload.new_conversation_id)
    existing_channel_result = await session.execute(existing_channel_query)
    existing_channel = existing_channel_result.scalar_one_or_none()
    if existing_channel:
        if existing_channel.workflow_id is None:
            raise HTTPException(status_code=409, detail="Conversation is already bound to a non-sheet channel")
        owner_result = await session.execute(
            select(Workflow.user_id).where(Workflow.id == existing_channel.workflow_id)
        )
        owner_id = owner_result.scalar_one_or_none()
        if owner_id != user_id:
            raise HTTPException(status_code=404, detail="Parent workflow not found")
        return AIForkResponse(
            new_workflow_id=existing_channel.workflow_id,
            new_channel_id=existing_channel.id,
        )

    # 1. Fetch parent workflow
    query = (
        select(Workflow)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.data_source_links),
        )
        .where(Workflow.id == workflow_id, Workflow.user_id == user_id)
    )
    result = await session.execute(query)
    parent_wf = result.scalar_one_or_none()
    if not parent_wf:
        raise HTTPException(status_code=404, detail="Parent workflow not found")

    if not parent_wf.project_id:
        raise HTTPException(status_code=400, detail="Cannot fork a workflow that doesn't belong to a project")

    if not parent_wf.data_source_links and parent_wf.primary_data_source_id is None:
        raise HTTPException(
            status_code=400,
            detail="Cannot generate an AI fork for a workflow without data sources",
        )

    validation = await validate_dag_spec_for_parent(
        payload.dag_spec,
        workflow_id,
        session,
        current_user,
    )
    if not validation["valid"]:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Proposed workflow is invalid",
                "issues": validation["issues"],
            },
        )

    # 2. Get order for new sheet
    max_order_query = select(func.max(Workflow.sheet_order)).where(
        Workflow.project_id == parent_wf.project_id, Workflow.user_id == user_id
    )
    max_order_result = await session.execute(max_order_query)
    max_order = max_order_result.scalar()
    next_order = 0 if max_order is None else max_order + 1

    # 3. Create workflow
    from spectra_sherpa.app.core.constants import AI_PURPLE

    sheet_name = payload.suggested_name or payload.sheet_name or f"AI alt of {parent_wf.name}"
    new_wf = Workflow(
        user_id=user_id,
        project_id=parent_wf.project_id,
        name=sheet_name,
        status="draft",
        color_source="ai",
        tab_color=AI_PURPLE,
        created_from_workflow_id=parent_wf.id,
        sheet_order=next_order,
    )
    session.add(new_wf)
    await session.flush()

    generated_positions = None
    if not _dag_spec_positions_are_usable(payload.dag_spec.nodes):
        generated_positions = _layout_dag_spec_nodes(payload.dag_spec.nodes, payload.dag_spec.edges)

    new_nodes: list[WorkflowNode] = []
    for n in payload.dag_spec.nodes:
        if generated_positions is not None:
            position_x, position_y = generated_positions[n.id]
        elif n.position is not None:
            position_x, position_y = n.position.x, n.position.y
        else:
            position_x, position_y = AI_FORK_LAYOUT_START_X, AI_FORK_LAYOUT_START_Y

        new_node = WorkflowNode(
            workflow_id=new_wf.id,
            node_id=n.id,
            node_type=n.type,
            parameters=n.parameters,
            position_x=position_x,
            position_y=position_y,
        )
        new_nodes.append(new_node)
        session.add(new_node)

    for e in payload.dag_spec.edges:
        session.add(
            WorkflowEdge(
                workflow_id=new_wf.id,
                from_node_id=e.source,
                to_node_id=e.target,
                from_output=e.from_output,
                to_input=e.to_input,
            )
        )

    await sync_workflow_data_sources(new_wf, session, new_nodes)
    if parent_wf.primary_data_source_id is not None:
        await session.flush()
        new_wf.primary_data_source_id = parent_wf.primary_data_source_id
        links_result = await session.execute(
            select(WorkflowDataSource).where(WorkflowDataSource.workflow_id == new_wf.id)
        )
        for link in links_result.scalars():
            link.role = "primary" if link.data_source_id == parent_wf.primary_data_source_id else "secondary"

    # 4. Create advisor channel
    channel = AdvisorChannel(
        project_id=parent_wf.project_id,
        workflow_id=new_wf.id,
        channel_type="sheet",
        title=sheet_name,
        color=AI_PURPLE,
        conversation_id=payload.new_conversation_id,
    )
    session.add(channel)

    await session.commit()

    return AIForkResponse(
        new_workflow_id=new_wf.id,
        new_channel_id=channel.id,
    )
