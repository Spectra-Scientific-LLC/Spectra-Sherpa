"""
Workflow API endpoints for DAG-based analysis pipelines.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.core.mode_policy import allows_custom_code_execution
from spectra_sherpa.app.core.security import check_export_allowed
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.serialization import serialize_result

logger = logging.getLogger(__name__)

from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_edge import WorkflowEdge
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.models.workflow_version import WorkflowVersion
from spectra_sherpa.app.schemas.workflows import (
    NodeLibraryResponse,
    NodeMetadataInfo,
    NodeParameterInfo,
    NodePortInfo,
    TrialExecuteRequest,
    TrialExecuteResponse,
    WorkflowCreate,
    WorkflowDetail,
    WorkflowExecuteRequest,
    WorkflowExecuteResponse,
    WorkflowSummary,
    WorkflowUpdate,
    WorkflowValidationIssue,
    WorkflowValidationResponse,
    WorkflowVersionDetail,
    WorkflowVersionListResponse,
    WorkflowVersionSummary,
)
from spectra_sherpa.app.services.dag import (
    DAGExecutor,
    node_registry,
)
from spectra_sherpa.app.services.dag import (
    WorkflowEdge as DAGEdge,
)
from spectra_sherpa.app.services.dag import (
    WorkflowNode as DAGNode,
)
from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash
from spectra_sherpa.app.services.python_export import generate_python_code

router = APIRouter(prefix="/workflows")


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
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[WorkflowSummary]:
    """
    List all workflows for the authenticated user with comprehensive search and filtering.

    Supports:
    - Full-text search on name and description
    - Filter by status, folder, and tags
    - Date range filtering
    - Custom sorting
    """
    user_id = current_user.id

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
        .options(selectinload(Workflow.tags), selectinload(Workflow.folder))
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

    # Apply sorting
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
        WorkflowSummary(
            **{
                "id": workflow.id,
                "user_id": workflow.user_id,
                "folder_id": workflow.folder_id,
                "name": workflow.name,
                "description": workflow.description,
                "status": workflow.status,
                "canvas_state": workflow.canvas_state,
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
        )
        for workflow, node_count, edge_count in rows
    ]


# IMPORTANT: This route must be defined BEFORE /{workflow_id} routes
# to avoid "trial" being parsed as a workflow_id
@router.post("/trial/execute", response_model=TrialExecuteResponse)
async def execute_trial(
    payload: TrialExecuteRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> TrialExecuteResponse:
    """
    Execute a trial run of a node with trial parameters.

    This endpoint is used by the DetailView to run a node with temporary
    parameters without persisting anything to the database. It creates
    a fresh DAG executor for each trial run (no caching).

    The trial execution:
    1. Builds a temporary DAG from the provided nodes/edges
    2. Overrides the target node's parameters with trial_params
    3. Executes the target node and its dependencies
    4. Returns only the target node's result

    This is completely independent of any stored workflow state.
    """
    node_types = [n.node_type for n in payload.nodes]
    ualgo_types, resolved_project_id = _validate_ualgo_node_types(
        node_types,
        project_id=payload.project_id,
        require_project_id=True,
    )
    if ualgo_types:
        await _validate_ualgo_db_ownership(
            session=session,
            user_id=current_user.id,
            ualgo_types=ualgo_types,
            project_id=resolved_project_id,
        )

    try:
        # Build a fresh DAG executor for this trial (no caching)
        executor = DAGExecutor()

        logger.debug(
            "[Trial Execution] Target node: %s (type: %s)", payload.target_node_id, type(payload.target_node_id)
        )
        logger.debug("[Trial Execution] Trial params: %s", payload.trial_params)
        logger.debug("[Trial Execution] Total nodes: %s", len(payload.nodes))

        # Add all nodes to the executor
        for node in payload.nodes:
            # Override params for target node with trial_params
            is_target = node.node_id == payload.target_node_id
            params = payload.trial_params if is_target else node.parameters

            logger.debug("[Trial Execution] Node %s (type: %s):", node.node_id, node.node_type)
            logger.debug("  - Is target: %s", is_target)
            logger.debug(
                "  - String comparison: '%s' == '%s': %s",
                node.node_id,
                payload.target_node_id,
                node.node_id == payload.target_node_id,
            )
            logger.debug("  - Node params from payload: %s", node.parameters)
            logger.debug("  - Params being used: %s", params)

            dag_node = DAGNode(
                node_id=node.node_id,
                node_type=node.node_type,
                parameters=params,
            )
            executor.add_node(dag_node)

        # Add all edges
        for edge in payload.edges:
            dag_edge = DAGEdge(
                from_node=edge.from_node_id,
                to_node=edge.to_node_id,
                from_output=edge.from_output,
                to_input=edge.to_input,
            )
            executor.add_edge(dag_edge)

        # Execute the target node (and its dependencies)
        results = await executor.execute_node(payload.target_node_id, initial_data=payload.initial_data)

        # Get the target node's result
        target_result = results.get(payload.target_node_id)

        # Serialize the result
        serialized_result = serialize_result(target_result, owner_user_id=current_user.id) if target_result else None

        return TrialExecuteResponse(
            target_node_id=payload.target_node_id,
            status="completed",
            result=serialized_result,
            error=None,
        )

    except Exception as e:
        return TrialExecuteResponse(
            target_node_id=payload.target_node_id,
            status="error",
            result=None,
            error=str(e),
        )


def _parse_ualgo_project_id(node_type: str) -> int | None:
    """Extract ``project_id`` from ``ualgo.{project_id}.{slug}`` node type."""
    if not node_type.startswith("ualgo."):
        return None
    parts = node_type.split(".", 2)
    if len(parts) < 3:
        raise HTTPException(status_code=400, detail=f"Malformed custom algo node type: {node_type}")
    try:
        return int(parts[1])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Malformed custom algo node type: {node_type}") from exc


def _validate_ualgo_node_types(
    node_types: list[str],
    *,
    project_id: int | None,
    require_project_id: bool,
) -> tuple[list[str], int | None]:
    """Validate ualgo node types and resolve effective project_id."""
    ualgo_types = [nt for nt in node_types if nt.startswith("ualgo.")]
    if not ualgo_types:
        return [], project_id

    if not allows_custom_code_execution():
        raise HTTPException(status_code=403, detail="Custom code execution is disabled by server policy")

    parsed_project_ids = {_parse_ualgo_project_id(nt) for nt in ualgo_types}
    if len(parsed_project_ids) != 1:
        raise HTTPException(
            status_code=403,
            detail="Custom algo nodes from multiple projects are not allowed in one workflow",
        )

    resolved_project_id = next(iter(parsed_project_ids))
    if project_id is None:
        if require_project_id:
            raise HTTPException(
                status_code=400,
                detail="project_id is required when using custom algo nodes",
            )
        return ualgo_types, resolved_project_id

    if project_id != resolved_project_id:
        raise HTTPException(
            status_code=403,
            detail=f"Custom algo {ualgo_types[0]} belongs to a different project",
        )
    return ualgo_types, project_id


async def _validate_ualgo_db_ownership(
    *,
    session: AsyncSession,
    user_id: int,
    ualgo_types: list[str],
    project_id: int | None,
) -> None:
    """Verify each ualgo type exists and belongs to the requesting user."""
    if not ualgo_types:
        return
    if project_id is None:
        raise HTTPException(status_code=400, detail="project_id is required when using custom algo nodes")

    from spectra_sherpa.app.models.custom_algo import CustomAlgo

    result = await session.execute(
        select(CustomAlgo.node_type).where(
            CustomAlgo.node_type.in_(ualgo_types),
            CustomAlgo.user_id == user_id,
            CustomAlgo.project_id == project_id,
        )
    )
    owned = set(result.scalars().all())
    for nt in ualgo_types:
        if nt not in owned:
            raise HTTPException(
                status_code=403,
                detail=f"Custom algo {nt} not found or not owned by you",
            )


@router.post("", response_model=WorkflowDetail, status_code=201)
async def create_workflow(
    payload: WorkflowCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDetail:
    """Create a new workflow for the authenticated user."""
    user_id = current_user.id
    node_types = [n.node_type for n in payload.nodes]
    ualgo_types, inferred_project_id = _validate_ualgo_node_types(
        node_types,
        project_id=None,
        require_project_id=False,
    )
    if ualgo_types:
        await _validate_ualgo_db_ownership(
            session=session,
            user_id=user_id,
            ualgo_types=ualgo_types,
            project_id=inferred_project_id,
        )

    # Validate all node types exist in the registry
    unknown_types = [
        n.node_type
        for n in payload.nodes
        if not n.node_type.startswith("ualgo.") and n.node_type not in node_registry
    ]
    if unknown_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown node type(s): {', '.join(unknown_types)}",
        )

    # Create workflow
    workflow = Workflow(
        user_id=user_id,
        project_id=inferred_project_id,
        name=payload.name,
        description=payload.description,
        status=payload.status,
        canvas_state=payload.canvas_state,
        technique=payload.technique,
        sample_type=payload.sample_type,
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
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one()

    return WorkflowDetail.model_validate(workflow)


# IMPORTANT: This route must be defined BEFORE /{workflow_id} routes
# to avoid "spectrochempy-examples" being parsed as a workflow_id
@router.get("/spectrochempy-examples", response_model=dict[str, list[dict[str, str]]])
async def list_spectrochempy_examples(
    current_user: User = Depends(get_current_user),
) -> dict[str, list[dict[str, str]]]:
    """
    List available files in SpectroChemPy example datasets.

    Scans configured SpectroChemPy datadirs (``SCP_DATADIR``,
    ``scp.preferences.datadir``, and ``~/.spectrochempy/testdata``),
    deduplicates files, and returns metadata for each file.

    Returns a dictionary mapping dataset names (e.g., 'irdata', 'ramandata')
    to lists of available files with their labels, paths, and metadata.
    """
    from pathlib import Path

    from spectra_sherpa.app.lib.scp_compat import HAS_SCP, get_scp_datadirs, scp

    if not HAS_SCP:
        raise HTTPException(
            status_code=501,
            detail=(
                "SpectroChemPy is not installed. "
                "Example datasets are unavailable. "
                "Install with: pip install spectra-sherpa[scp]"
            ),
        )

    try:
        # Scan multiple data directories
        primary_datadir = Path(scp.preferences.datadir)
        primary_resolved = primary_datadir.expanduser().resolve(strict=False)
        data_dirs = [d for d in get_scp_datadirs() if d.exists()]

        spectral_extensions = {
            ".spg",
            ".spa",
            ".csv",
            ".jdx",
            ".dx",
            ".spc",
            ".txt",
            ".wdf",
            ".mat",
            ".asc",
        }
        scp_labels = {
            "irdata": "IR: Infrared Spectroscopy",
            "ramandata": "Raman Spectroscopy",
            "nmrdata": "NMR: Nuclear Magnetic Resonance",
            "galacticdata": "Galactic SPC Files",
            "agirdata": "Agilent IR (AGIR)",
            "dscdata": "DSC (Calorimetry)",
            "matlabdata": "MATLAB Datasets",
            "msdata": "Mass Spectrometry",
        }

        # Auto-discover SCP categories from available datadirs.
        datasets: dict[str, dict[str, Any]] = {}
        for datadir in data_dirs:
            for subdir in sorted(datadir.iterdir()):
                if not subdir.is_dir() or subdir.name.startswith((".", "_")):
                    continue
                name = subdir.name
                if name in datasets:
                    continue

                label = scp_labels.get(name, name.replace("data", " Data").title().strip())
                if name == "nmrdata":
                    datasets[name] = {"label": label, "dirs": True}
                else:
                    datasets[name] = {
                        "label": label,
                        "extensions": list(spectral_extensions),
                        "allow_numeric_ext": True,
                    }

        result = {}

        for dataset_name, config in datasets.items():
            # Use dict to deduplicate by relative path
            files_dict = {}

            for datadir in data_dirs:
                folder_path = datadir / dataset_name
                if not folder_path.exists():
                    continue

                # For NMR data, list directories (Bruker format uses directories)
                if config.get("dirs"):
                    # Find directories that contain 'fid' or 'ser' files (Bruker format)
                    for item in sorted(folder_path.rglob("*")):
                        if item.is_dir():
                            # Check if this directory contains Bruker NMR data
                            if (item / "fid").exists() or (item / "ser").exists():
                                rel_path = item.relative_to(datadir)
                                label = str(rel_path).replace(f"{dataset_name}/", "")
                                source_kind = (
                                    "primary"
                                    if datadir.expanduser().resolve(strict=False) == primary_resolved
                                    else "fallback"
                                )

                                # Deduplicate: only add if not already seen
                                if label not in files_dict:
                                    files_dict[label] = {
                                        "label": label,
                                        "value": str(rel_path),
                                        "path": str(rel_path),
                                        "source": source_kind,
                                    }
                else:
                    # For other datasets, list files by extension (case-insensitive)
                    # Create set of lowercase extensions for O(1) lookup
                    extensions_set = {ext.lower() for ext in config.get("extensions", [])}
                    allow_numeric_ext = config.get("allow_numeric_ext", False)

                    # Scan once, filter by extension set (more efficient than nested loops)
                    for file_path in sorted(folder_path.rglob("*")):
                        if not file_path.is_file():
                            continue
                        if file_path.name.startswith(("__", ".")):
                            continue

                        suffix_lower = file_path.suffix.lower()
                        is_numeric_ext = suffix_lower.lstrip(".").isdigit()
                        if suffix_lower not in extensions_set and not (allow_numeric_ext and is_numeric_ext):
                            continue

                        rel_path = file_path.relative_to(datadir)
                        label = str(rel_path).replace(f"{dataset_name}/", "")
                        source_kind = (
                            "primary" if datadir.expanduser().resolve(strict=False) == primary_resolved else "fallback"
                        )

                        # Deduplicate: only add if not already seen
                        if label not in files_dict:
                            files_dict[label] = {
                                "label": label,
                                "value": str(rel_path),
                                "path": str(rel_path),
                                "format": file_path.suffix.lower(),
                                "source": source_kind,
                            }

            if files_dict:
                # DataSourceNode is for single files only
                # For loading multiple files, users should use LoadGroupNode
                result[dataset_name] = list(files_dict.values())

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list SpectroChemPy examples: {str(e)}")


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
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if payload.nodes is not None:
        node_types = [n.node_type for n in payload.nodes]
        ualgo_types, resolved_project_id = _validate_ualgo_node_types(
            node_types,
            project_id=workflow.project_id,
            require_project_id=False,
        )
        if ualgo_types:
            await _validate_ualgo_db_ownership(
                session=session,
                user_id=user_id,
                ualgo_types=ualgo_types,
                project_id=resolved_project_id,
            )
            if workflow.project_id is None:
                workflow.project_id = resolved_project_id

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
        # Delete existing nodes
        await session.execute(select(WorkflowNode).where(WorkflowNode.workflow_id == workflow_id))
        await session.execute(WorkflowNode.__table__.delete().where(WorkflowNode.workflow_id == workflow_id))

        # Create new nodes
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

    # Update edges if provided
    if payload.edges is not None:
        # Delete existing edges
        await session.execute(WorkflowEdge.__table__.delete().where(WorkflowEdge.workflow_id == workflow_id))

        # Create new edges
        for edge_data in payload.edges:
            edge = WorkflowEdge(
                workflow_id=workflow.id,
                from_node_id=edge_data.from_node_id,
                to_node_id=edge_data.to_node_id,
                from_output=edge_data.from_output,
                to_input=edge_data.to_input,
            )
            session.add(edge)

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

    # Flush changes to database before creating snapshot
    await session.flush()

    # Reload workflow with all current relationships to capture actual state
    snapshot_query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
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
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one()

    return WorkflowDetail.model_validate(workflow)


@router.get("/{workflow_id}/versions", response_model=WorkflowVersionListResponse)
async def list_workflow_versions(
    workflow_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowVersionListResponse:
    """List all versions of a workflow for the authenticated user."""
    user_id = current_user.id

    # Verify workflow exists and user owns it
    workflow_query = select(Workflow).where(Workflow.id == workflow_id).where(Workflow.user_id == user_id)
    workflow_result = await session.execute(workflow_query)
    workflow = workflow_result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Get total count
    count_query = select(func.count(WorkflowVersion.id)).where(WorkflowVersion.workflow_id == workflow_id)
    count_result = await session.execute(count_query)
    total = count_result.scalar() or 0

    # Get versions (ordered newest first)
    query = (
        select(WorkflowVersion)
        .where(WorkflowVersion.workflow_id == workflow_id)
        .order_by(WorkflowVersion.version_number.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(query)
    versions = result.scalars().all()

    return WorkflowVersionListResponse(
        versions=[WorkflowVersionSummary.model_validate(v) for v in versions],
        total=total,
    )


@router.get("/{workflow_id}/versions/{version_id}", response_model=WorkflowVersionDetail)
async def get_workflow_version(
    workflow_id: int,
    version_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowVersionDetail:
    """Get a specific workflow version with full snapshot for the authenticated user."""
    user_id = current_user.id

    # Verify workflow exists and user owns it
    workflow_query = select(Workflow).where(Workflow.id == workflow_id).where(Workflow.user_id == user_id)
    workflow_result = await session.execute(workflow_query)
    workflow = workflow_result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Get version
    query = (
        select(WorkflowVersion)
        .where(WorkflowVersion.id == version_id)
        .where(WorkflowVersion.workflow_id == workflow_id)
    )
    result = await session.execute(query)
    version = result.scalar_one_or_none()

    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")

    return WorkflowVersionDetail.model_validate(version)


@router.post("/{workflow_id}/versions/{version_id}/restore", response_model=WorkflowDetail)
async def restore_workflow_version(
    workflow_id: int,
    version_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowDetail:
    """Restore a workflow to a previous version for the authenticated user."""
    user_id = current_user.id

    # Verify workflow exists and user owns it
    workflow_query = select(Workflow).where(Workflow.id == workflow_id).where(Workflow.user_id == user_id)
    workflow_result = await session.execute(workflow_query)
    workflow = workflow_result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Get version to restore
    version_query = (
        select(WorkflowVersion)
        .where(WorkflowVersion.id == version_id)
        .where(WorkflowVersion.workflow_id == workflow_id)
    )
    version_result = await session.execute(version_query)
    version = version_result.scalar_one_or_none()

    if version is None:
        raise HTTPException(status_code=404, detail="Version not found")

    # Restore workflow from snapshot
    snapshot = version.snapshot

    # Update workflow fields
    if "name" in snapshot:
        workflow.name = snapshot["name"]
    if "description" in snapshot:
        workflow.description = snapshot["description"]
    if "status" in snapshot:
        workflow.status = snapshot["status"]
    if "canvas_state" in snapshot:
        workflow.canvas_state = snapshot["canvas_state"]
    if "notes" in snapshot:
        workflow.notes = snapshot["notes"]
    if "technique" in snapshot:
        workflow.technique = snapshot["technique"]
    if "sample_type" in snapshot:
        workflow.sample_type = snapshot["sample_type"]

    # Delete existing nodes and edges
    await session.execute(WorkflowNode.__table__.delete().where(WorkflowNode.workflow_id == workflow_id))
    await session.execute(WorkflowEdge.__table__.delete().where(WorkflowEdge.workflow_id == workflow_id))

    # Restore nodes from snapshot
    if "nodes" in snapshot:
        for node_data in snapshot["nodes"]:
            node = WorkflowNode(
                workflow_id=workflow_id,
                node_id=node_data["node_id"],
                node_type=node_data["node_type"],
                label=node_data.get("label"),
                parameters=node_data.get("parameters", {}),
                position_x=node_data.get("position_x"),
                position_y=node_data.get("position_y"),
            )
            session.add(node)

    # Restore edges from snapshot
    if "edges" in snapshot:
        for edge_data in snapshot["edges"]:
            edge = WorkflowEdge(
                workflow_id=workflow_id,
                from_node_id=edge_data["from_node_id"],
                to_node_id=edge_data["to_node_id"],
                from_output=edge_data.get("from_output", "default"),
                to_input=edge_data.get("to_input", "default"),
            )
            session.add(edge)

    # Create a new version record for the restore action
    latest_version_query = select(func.max(WorkflowVersion.version_number)).where(
        WorkflowVersion.workflow_id == workflow_id
    )
    latest_version_result = await session.execute(latest_version_query)
    latest_version = latest_version_result.scalar() or 0
    new_version_number = latest_version + 1

    restore_version = WorkflowVersion(
        workflow_id=workflow_id,
        version_number=new_version_number,
        created_by=user_id,
        change_description=f"Restored from version {version.version_number}",
        snapshot=snapshot,
    )
    session.add(restore_version)

    await session.commit()

    # Reload with relationships
    reload_query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
        )
    )
    reload_result = await session.execute(reload_query)
    workflow = reload_result.scalar_one()

    return WorkflowDetail.model_validate(workflow)


@router.delete("/{workflow_id}", status_code=204)
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

    await session.delete(workflow)
    await session.commit()


@router.post("/{workflow_id}/validate", response_model=WorkflowValidationResponse)
async def validate_workflow_endpoint(
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowValidationResponse:
    """Validate a workflow without executing it.

    Checks: graph structure, required parameters, port type compatibility.
    Returns structured list of errors and warnings.
    """
    user_id = current_user.id

    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .where(Workflow.user_id == user_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Build executor (same pattern as execute_workflow)
    executor = DAGExecutor()
    all_issues: list[WorkflowValidationIssue] = []

    for node in workflow.nodes:
        dag_node = DAGNode(
            node_id=node.node_id,
            node_type=node.node_type,
            parameters=node.parameters or {},
        )
        try:
            executor.add_node(dag_node)
        except KeyError as e:
            all_issues.append(
                WorkflowValidationIssue(
                    level="error",
                    node_id=node.node_id,
                    port=None,
                    message=f"Unknown node type: {e}",
                )
            )

    for edge in workflow.edges:
        dag_edge = DAGEdge(
            from_node=edge.from_node_id,
            to_node=edge.to_node_id,
            from_output=edge.from_output,
            to_input=edge.to_input,
        )
        try:
            executor.add_edge(dag_edge)
        except ValueError as e:
            all_issues.append(
                WorkflowValidationIssue(
                    level="error",
                    node_id=None,
                    port=None,
                    message=str(e),
                )
            )

    # Run structural + parameter + port type validation
    if not any(i.level == "error" for i in all_issues):
        validation = executor.validate_full()
        for issue in validation.issues:
            all_issues.append(
                WorkflowValidationIssue(
                    level=issue.level,
                    node_id=issue.node_id,
                    port=issue.port,
                    message=issue.message,
                )
            )

    errors = [i for i in all_issues if i.level == "error"]
    warnings = [i for i in all_issues if i.level == "warning"]

    return WorkflowValidationResponse(
        is_valid=len(errors) == 0,
        issues=all_issues,
        error_count=len(errors),
        warning_count=len(warnings),
    )


@router.post("/{workflow_id}/execute", response_model=WorkflowExecuteResponse)
async def execute_workflow(
    workflow_id: int,
    payload: WorkflowExecuteRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkflowExecuteResponse:
    """Execute a workflow for the authenticated user."""
    user_id = current_user.id

    # Load workflow with nodes and edges
    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .where(Workflow.user_id == user_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    node_types = [n.node_type for n in workflow.nodes]
    ualgo_types, resolved_project_id = _validate_ualgo_node_types(
        node_types,
        project_id=workflow.project_id,
        require_project_id=False,
    )
    if ualgo_types:
        await _validate_ualgo_db_ownership(
            session=session,
            user_id=user_id,
            ualgo_types=ualgo_types,
            project_id=resolved_project_id,
        )

    # Snapshot ORM attributes while session is clean (before execution may
    # dirty or expire them, making lazy loads fail in the error handler).
    wf_integrity_hash = workflow.integrity_hash
    wf_version_id = getattr(workflow, "current_version_id", None)
    wf_project_id = getattr(workflow, "project_id", None)

    executor = None
    try:
        # Build DAG executor
        executor = DAGExecutor()

        # Add nodes
        for node in workflow.nodes:
            dag_node = DAGNode(
                node_id=node.node_id,
                node_type=node.node_type,
                parameters=node.parameters,
                position={"x": node.position_x, "y": node.position_y} if node.position_x and node.position_y else None,
            )
            executor.add_node(dag_node)

        # Add edges
        for edge in workflow.edges:
            dag_edge = DAGEdge(
                from_node=edge.from_node_id,
                to_node=edge.to_node_id,
                from_output=edge.from_output,
                to_input=edge.to_input,
            )
            executor.add_edge(dag_edge)

        # Build per-node status broadcast callback
        import time as _time

        from spectra_sherpa.app.services.websocket_manager import ws_manager

        async def _broadcast_node_status(node_id: str, status: str, error: str | None = None) -> None:
            try:
                await ws_manager.broadcast(
                    f"workflow:{workflow_id}",
                    {
                        "type": "node_status",
                        "node_id": node_id,
                        "status": status,
                        "error": error,
                        "timestamp": _time.time(),
                    },
                )
            except Exception:
                pass  # Never let broadcast failure affect execution

        # Execute
        if payload.node_id:
            # Execute single node and its dependencies (with initial_data for DATA nodes)
            results = await executor.execute_node(payload.node_id, initial_data=payload.initial_data)
        else:
            # Execute entire workflow
            results = await executor.execute(
                initial_data=payload.initial_data,
                status_callback=_broadcast_node_status,
            )

        # Serialize results to JSON-safe format (per-node, so one failure doesn't lose all)
        logger.debug("[Serialization] Starting serialization of %s node results...", len(results))
        serialized_results = {}
        serialization_errors = []
        for node_id, node_result in results.items():
            result_type = type(node_result).__name__
            try:
                serialized_results[node_id] = serialize_result(node_result, owner_user_id=user_id)
                # Log summary of serialized result
                sr = serialized_results[node_id]
                if isinstance(sr, dict):
                    keys = list(sr.keys())[:8]
                    logger.debug("  Serialized node %s (%s): keys=%s", node_id, result_type, keys)
                else:
                    logger.debug("  Serialized node %s (%s): type=%s", node_id, result_type, type(sr).__name__)
            except Exception as ser_err:
                logger.warning(
                    "  Serialization failed for node %s (%s): %s", node_id, result_type, ser_err, exc_info=True
                )
                serialization_errors.append(f"Node {node_id}: {ser_err}")
                serialized_results[node_id] = {
                    "error": f"Serialization failed: {ser_err}",
                    "type": result_type,
                }

        # Persist model artifacts to DB (if any training nodes ran)
        if executor and getattr(executor, "saved_artifacts", None):
            from spectra_sherpa.app.services.model_store import persist_model_artifact_records

            await persist_model_artifact_records(
                session,
                executor.saved_artifacts,
                user_id=user_id,
                workflow_id=workflow_id,
                workflow_version_id=wf_version_id,
                project_id=wf_project_id,
            )

        # Update workflow execution timestamp
        workflow.last_executed_at = datetime.utcnow()
        await session.commit()

        error_msg = "; ".join(serialization_errors) if serialization_errors else None
        final_status = executor.status.value if not serialization_errors else "partial"
        node_statuses = executor.get_status()["node_statuses"]
        logger.debug(
            "[Serialization] Done. status=%s, result_keys=%s, node_statuses=%s",
            final_status,
            list(serialized_results.keys()),
            node_statuses,
        )
        if error_msg:
            logger.debug("[Serialization] Errors: %s", error_msg)

        return WorkflowExecuteResponse(
            workflow_id=workflow_id,
            status=final_status,
            results=serialized_results,
            diagnostics=serialize_result(getattr(executor, "diagnostics", {}), owner_user_id=user_id),
            node_statuses=node_statuses,
            executed_at=datetime.utcnow(),
            error=error_msg,
            integrity_hash=wf_integrity_hash,
        )

    except Exception as e:
        logger.debug("Workflow execution failed for workflow_id=%s", workflow_id, exc_info=True)

        # Persist any model artifacts that were saved to disk before the failure.
        # Without this, partial executions leave orphan files with no DB records.
        if executor and getattr(executor, "saved_artifacts", None):
            try:
                # Roll back any dirty state from the failed execution before
                # attempting new DB writes. This is safe even if session is clean.
                await session.rollback()

                from spectra_sherpa.app.services.model_store import persist_model_artifact_records

                await persist_model_artifact_records(
                    session,
                    executor.saved_artifacts,
                    user_id=user_id,
                    workflow_id=workflow_id,
                    workflow_version_id=wf_version_id,
                    project_id=wf_project_id,
                )
                await session.commit()
            except Exception as art_err:
                logger.warning("Could not persist model artifacts from partial run: %s", art_err)
                try:
                    await session.rollback()
                except Exception:
                    pass

        # Preserve successfully completed node outputs when later nodes fail.
        partial_results: dict[str, Any] = {}
        partial_serialization_errors: list[str] = []
        raw_results = executor.results if executor else {}
        for node_id, node_result in raw_results.items():
            result_type = type(node_result).__name__
            try:
                partial_results[node_id] = serialize_result(node_result, owner_user_id=user_id)
            except Exception as ser_err:
                partial_serialization_errors.append(f"Node {node_id}: {ser_err}")
                partial_results[node_id] = {
                    "error": f"Serialization failed: {ser_err}",
                    "type": result_type,
                }

        error_parts = [str(e)]
        if partial_serialization_errors:
            error_parts.append("; ".join(partial_serialization_errors))
        error_msg = " | ".join(part for part in error_parts if part)
        response_status = "partial" if partial_results else "error"

        return WorkflowExecuteResponse(
            workflow_id=workflow_id,
            status=response_status,
            results=partial_results,
            diagnostics=serialize_result(
                getattr(executor, "diagnostics", {}) if executor else {},
                owner_user_id=user_id,
            ),
            node_statuses=executor.get_status()["node_statuses"] if executor else {},
            executed_at=datetime.utcnow(),
            error=error_msg,
            integrity_hash=wf_integrity_hash,
        )


@router.get("/nodes/library", response_model=NodeLibraryResponse)
async def get_node_library(
    current_user: User = Depends(get_current_user),
) -> NodeLibraryResponse:
    """
    Get available node types from the registry.

    Includes backend version for client-side cache invalidation.
    """
    from spectra_sherpa.app.core.config import settings

    # Exclude custom_algo nodes — those are served via the project-scoped endpoint.
    # Use list_nodes_with_aliases() so legacy workflows that reference old node
    # type strings (e.g. "smooth.whittaker", "classification.simca_predict") can
    # still resolve metadata in the frontend.
    nodes = [n for n in node_registry.list_nodes_with_aliases() if n.category != "custom_algo"]

    node_infos = []
    for node_meta in nodes:
        params = [
            NodeParameterInfo(
                name=p.name,
                label=p.label,
                param_type=p.param_type,
                default=p.default,
                min_value=p.min_value,
                max_value=p.max_value,
                step=p.step,
                options=p.options,
                description=p.description,
                required=p.required,
                category=p.category,
                visible_when=p.visible_when,
            )
            for p in node_meta.parameters
        ]

        # Serialize input ports
        input_ports = None
        if node_meta.input_ports:
            input_ports = [
                NodePortInfo(
                    name=port.name,
                    type_ref=port.type_ref,
                    required=port.required,
                    label=port.label,
                    description=port.description,
                )
                for port in node_meta.input_ports
            ]

        # Serialize output ports
        output_ports = None
        if node_meta.output_ports:
            output_ports = [
                NodePortInfo(
                    name=port.name,
                    type_ref=port.type_ref,
                    required=port.required,
                    label=port.label,
                    description=port.description,
                )
                for port in node_meta.output_ports
            ]

        node_infos.append(
            NodeMetadataInfo(
                node_type=node_meta.node_type,
                category=node_meta.category,
                label=node_meta.label,
                description=node_meta.description,
                parameters=params,
                input_types=node_meta.input_types,
                output_type=node_meta.output_type,
                input_ports=input_ports,
                output_ports=output_ports,
                diagnostics=node_meta.diagnostics,
                help_url=node_meta.help_url,
            )
        )

    return NodeLibraryResponse(
        nodes=node_infos, total=len(node_infos), version=settings.app_version  # For cache invalidation
    )


@router.get("/types/registry")
async def get_type_registry(
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Get the type registry for client-side type validation.

    Returns all type definitions, subtype relationships, and version info
    so the frontend can validate connections without per-edge API calls.
    """
    from spectra_sherpa.app.types import type_registry

    return type_registry.to_api_json()


@router.get("/{workflow_id}/export/python")
async def export_workflow_to_python(
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Export a workflow as executable Python code for the authenticated user."""
    if not await check_export_allowed(current_user):
        raise HTTPException(status_code=403, detail="Export not permitted for this user")

    user_id = current_user.id

    # Load workflow with nodes and edges
    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .where(Workflow.user_id == user_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    try:
        python_code = generate_python_code(workflow)
        return {
            "workflow_id": workflow_id,
            "workflow_name": workflow.name,
            "python_code": python_code,
            "filename": f"{workflow.name.lower().replace(' ', '_')}_workflow.py",
        }
    except ValueError as e:
        # Unsupported node types or cycles — client-actionable error
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        logger.exception("Unexpected error exporting workflow %s", workflow_id)
        raise HTTPException(status_code=500, detail="Failed to export workflow. Check server logs.")


@router.get("/{workflow_id}/export/notebook")
async def export_workflow_to_notebook(
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Export a workflow as a Jupyter notebook (.ipynb) for the authenticated user."""
    if not await check_export_allowed(current_user):
        raise HTTPException(status_code=403, detail="Export not permitted for this user")

    user_id = current_user.id

    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .where(Workflow.user_id == user_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    try:
        from spectra_sherpa.app.services.notebook_export import generate_notebook

        notebook = generate_notebook(workflow)
        safe_name = workflow.name.lower().replace(" ", "_")
        return {
            "workflow_id": workflow_id,
            "workflow_name": workflow.name,
            "notebook": notebook,
            "filename": f"{safe_name}_workflow.ipynb",
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception:
        logger.exception("Unexpected error exporting notebook for workflow %s", workflow_id)
        raise HTTPException(status_code=500, detail="Failed to export notebook. Check server logs.")
