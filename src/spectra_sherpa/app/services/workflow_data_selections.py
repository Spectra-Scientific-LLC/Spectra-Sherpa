"""Atomic, append-only sheet data-selection revisions."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.contracts.project_access import uses_managed_project_access
from spectra_sherpa.app.contracts.scientific_access import require_scientific_access
from spectra_sherpa.app.lib.target_authority import verify_target_authority
from spectra_sherpa.app.models.dataset_view import DatasetView
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_data_selection_revision import WorkflowDataSelectionRevision
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.schemas.workflow_data_selection import WorkflowSourceSelection
from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash
from spectra_sherpa.app.services.dataset_views import receipt_sha256, verify_selection_receipt
from spectra_sherpa.app.services.model_application import load_project_dataset


def source_parameters(selection: WorkflowSourceSelection) -> dict[str, Any]:
    return {
        "experiment_id": selection.experiment_id,
        "stage": selection.stage,
        "asset_id": selection.asset_id or "",
        "selected_file_ids": [str(value) for value in selection.selected_file_ids or []],
        "source_manifest_sha256": selection.source_manifest_sha256,
        "collection_definition_sha256": selection.collection_definition_sha256 or "",
        "scientific_collection_sha256": selection.scientific_collection_sha256,
        "target_authority": (
            selection.target_authority.canonical_dict() if selection.target_authority is not None else None
        ),
        "group_column": selection.group_column or "",
        "dataset_view_id": selection.dataset_view_id,
        "dataset_view_sha256": selection.dataset_view_sha256 or "",
        "group_title": selection.dataset_name,
    }


def selection_from_parameters(parameters: dict[str, Any], *, dataset_name: str) -> WorkflowSourceSelection:
    selected = parameters.get("selected_file_ids")
    return WorkflowSourceSelection(
        experiment_id=int(parameters["experiment_id"]),
        dataset_name=dataset_name,
        stage=parameters.get("stage") or "raw",
        selected_file_ids=[int(value) for value in selected] if selected else None,
        asset_id=parameters.get("asset_id") or None,
        source_manifest_sha256=parameters["source_manifest_sha256"],
        collection_definition_sha256=parameters.get("collection_definition_sha256") or None,
        scientific_collection_sha256=parameters["scientific_collection_sha256"],
        target_authority=parameters.get("target_authority"),
        group_column=parameters.get("group_column") or None,
        dataset_view_id=parameters.get("dataset_view_id") or None,
        dataset_view_sha256=parameters.get("dataset_view_sha256") or None,
    )


def _is_unbound_collection_load(parameters: dict[str, Any]) -> bool:
    """Distinguish a pristine authoring node from a damaged source binding."""
    return not any(
        parameters.get(name)
        for name in (
            "experiment_id",
            "asset_id",
            "selected_file_ids",
            "source_manifest_sha256",
            "collection_definition_sha256",
            "scientific_collection_sha256",
            "target_authority",
            "group_column",
            "dataset_view_id",
            "dataset_view_sha256",
            "group_title",
        )
    )


async def load_selection_context(
    session: AsyncSession,
    *,
    workflow_id: int,
    source_node_id: str,
    user_id: int,
    for_update: bool = False,
) -> tuple[Workflow, WorkflowNode, WorkflowDataSelectionRevision | None, WorkflowSourceSelection | None]:
    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id, or_(Workflow.user_id == user_id, uses_managed_project_access()))
        .options(selectinload(Workflow.nodes), selectinload(Workflow.edges), selectinload(Workflow.data_source_links))
    )
    if for_update:
        query = query.with_for_update()
    workflow = await session.scalar(query)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if uses_managed_project_access():
        await require_scientific_access(session, user_id, workflow.project_id, "write" if for_update else "read")
    node = next((item for item in workflow.nodes if item.node_id == source_node_id), None)
    if node is None or node.node_type != "data.collection_load":
        raise HTTPException(status_code=404, detail="Workflow data source not found")
    try:
        selection = selection_from_parameters(
            dict(node.parameters or {}), dataset_name=node.parameters.get("group_title") or node.label or source_node_id
        )
    except (KeyError, TypeError, ValueError) as exc:
        # An unbound Collection Load is a valid authoring state.  Returning an
        # empty selection lets the Data page create its first append-only
        # custody revision.  Execution still rejects the incomplete node via
        # the canonical node validator.
        if _is_unbound_collection_load(dict(node.parameters or {})):
            selection = None
        else:
            raise HTTPException(
                status_code=409,
                detail="Workflow source has incomplete data-selection custody",
            ) from exc
    current = await session.scalar(
        select(WorkflowDataSelectionRevision)
        .where(
            WorkflowDataSelectionRevision.workflow_id == workflow_id,
            WorkflowDataSelectionRevision.source_node_id == source_node_id,
        )
        .order_by(WorkflowDataSelectionRevision.revision_number.desc())
        .limit(1)
    )
    return workflow, node, current, selection


async def validate_selection(
    session: AsyncSession,
    *,
    selection: WorkflowSourceSelection,
    user_id: int,
    workflow_project_id: int | None,
    allow_deleted_view: bool = False,
) -> None:
    query = select(Experiment).where(Experiment.id == selection.experiment_id)
    if uses_managed_project_access():
        # Never expose whether an experiment exists in a different tenant/project.
        await require_scientific_access(session, user_id, workflow_project_id, "read")
        query = query.where(Experiment.project_id == workflow_project_id)
    else:
        query = query.where(Experiment.user_id == user_id)
    experiment = await session.scalar(query.execution_options(populate_existing=True))
    if experiment is None:
        raise HTTPException(status_code=404, detail="Dataset not found in this workflow project")
    if workflow_project_id is not None and experiment.project_id != workflow_project_id:
        raise HTTPException(status_code=409, detail="Dataset belongs to a different project")
    loaded = await load_project_dataset(
        session,
        user_id=user_id,
        experiment_id=selection.experiment_id,
        stage=selection.stage,
        file_ids=selection.selected_file_ids,
        asset_id=selection.asset_id,
    )
    if (
        loaded.source_manifest_sha256 != selection.source_manifest_sha256
        or loaded.collection_definition_sha256 != selection.collection_definition_sha256
        or loaded.scientific_collection_sha256 != selection.scientific_collection_sha256
    ):
        raise HTTPException(status_code=409, detail="Data selection no longer matches the admitted dataset identity")
    if selection.target_authority is not None:
        try:
            verify_target_authority(loaded.dataset, selection.target_authority)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    if selection.group_column and selection.target_authority is None:
        raise HTTPException(status_code=400, detail="Grouping requires a selected target authority")
    if selection.dataset_view_id is not None:
        view_query = select(DatasetView).where(
            DatasetView.id == selection.dataset_view_id,
            DatasetView.experiment_id == selection.experiment_id,
            DatasetView.project_id == workflow_project_id,
        )
        if not allow_deleted_view:
            view_query = view_query.where(DatasetView.deleted_at.is_(None))
        view = await session.scalar(view_query)
        if view is None:
            raise HTTPException(status_code=404, detail="Saved dataset definition not found in this project")
        if (
            view.selection_sha256 != selection.dataset_view_sha256
            or receipt_sha256(view.selection) != view.selection_sha256
        ):
            raise HTTPException(status_code=409, detail="Saved dataset definition digest changed")
        try:
            verify_selection_receipt(loaded, view.selection)
        except ValueError as exc:
            raise HTTPException(
                status_code=409, detail="Saved dataset definition no longer matches its source or cohort"
            ) from exc
        receipt = view.selection
        if (
            selection.stage != receipt["stage"]
            or selection.selected_file_ids != receipt["selected_file_ids"]
            or selection.asset_id != receipt["asset_id"]
            or selection.source_manifest_sha256 != receipt["source_manifest_sha256"]
            or selection.collection_definition_sha256 != receipt["collection_definition_sha256"]
            or selection.scientific_collection_sha256 != receipt["scientific_collection_sha256"]
            or (selection.target_authority.canonical_dict() if selection.target_authority else None)
            != receipt["target_authority"]
            or selection.group_column != receipt["group_column"]
        ):
            raise HTTPException(status_code=409, detail="Workflow selection differs from the saved dataset definition")


def workflow_graph_digest(workflow: Workflow) -> str:
    return compute_workflow_hash(
        nodes=[
            {"node_id": node.node_id, "node_type": node.node_type, "parameters": node.parameters or {}}
            for node in workflow.nodes
        ],
        edges=[
            {
                "from_node_id": edge.from_node_id,
                "to_node_id": edge.to_node_id,
                "from_output": edge.from_output,
                "to_input": edge.to_input,
            }
            for edge in workflow.edges
        ],
    )


async def next_revision_number(session: AsyncSession, workflow_id: int, source_node_id: str) -> int:
    latest = await session.scalar(
        select(func.max(WorkflowDataSelectionRevision.revision_number)).where(
            WorkflowDataSelectionRevision.workflow_id == workflow_id,
            WorkflowDataSelectionRevision.source_node_id == source_node_id,
        )
    )
    return int(latest or 0) + 1


async def execution_selection_revisions(
    session: AsyncSession,
    *,
    workflow_id: int,
    graph_digest: str | None,
    source_nodes: list[WorkflowNode],
    user_id: int | None = None,
    workflow_project_id: int | None = None,
) -> list[dict[str, Any]]:
    """Freeze latest revisions whose source binding is still exact in this graph."""
    claimed_view_nodes = {
        node.node_id
        for node in source_nodes
        if node.node_type == "data.collection_load"
        and (
            (node.parameters or {}).get("dataset_view_id") is not None
            or bool((node.parameters or {}).get("dataset_view_sha256"))
        )
    }
    if not graph_digest:
        if claimed_view_nodes:
            raise HTTPException(status_code=409, detail="Saved dataset definitions require an exact workflow graph")
        return []
    rows = list(
        (
            await session.execute(
                select(WorkflowDataSelectionRevision)
                .where(
                    WorkflowDataSelectionRevision.workflow_id == workflow_id,
                )
                .order_by(
                    WorkflowDataSelectionRevision.source_node_id,
                    WorkflowDataSelectionRevision.revision_number.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    latest: dict[str, WorkflowDataSelectionRevision] = {}
    for row in rows:
        latest.setdefault(row.source_node_id, row)
    current_nodes = {node.node_id: node for node in source_nodes if node.node_type == "data.collection_load"}
    for node_id in claimed_view_nodes:
        if node_id not in latest:
            raise HTTPException(
                status_code=409,
                detail=f"Workflow source {node_id} claims a saved dataset definition without a data-selection revision",
            )
    frozen: list[dict[str, Any]] = []
    for row in latest.values():
        current = current_nodes.get(row.source_node_id)
        if current is None:
            continue
        try:
            expected = WorkflowSourceSelection.model_validate(row.selection)
            observed = selection_from_parameters(
                dict(current.parameters or {}),
                dataset_name=expected.dataset_name,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Workflow source {row.source_node_id} no longer matches its recorded data selection",
            ) from exc
        if observed != expected:
            raise HTTPException(
                status_code=409,
                detail=f"Workflow source {row.source_node_id} changed outside its data-selection revision",
            )
        if expected.dataset_view_id is not None:
            if user_id is None:
                raise HTTPException(status_code=409, detail="Saved dataset definition needs actor-scoped revalidation")
            await validate_selection(
                session,
                selection=expected,
                user_id=user_id,
                workflow_project_id=workflow_project_id,
                allow_deleted_view=True,
            )
        frozen.append(
            {
                "revision_id": row.id,
                "revision_number": row.revision_number,
                "source_node_id": row.source_node_id,
                "created_by": row.created_by,
                "created_at": row.created_at.isoformat(),
                "origin": row.origin,
                "reason": row.reason,
                "graph_digest": graph_digest,
                "selection_graph_digest": row.graph_digest,
                "selection": row.selection,
            }
        )
    return frozen


async def record_restored_selection_revisions(
    session: AsyncSession, *, workflow: Workflow, user_id: int, version_id: int, record_initial: bool = False
) -> None:
    """Append restoration custody without rewriting any historical selection."""
    import uuid

    digest = workflow_graph_digest(workflow)
    workflow.integrity_hash = digest
    for node in workflow.nodes:
        if node.node_type != "data.collection_load":
            continue
        current = await session.scalar(
            select(WorkflowDataSelectionRevision)
            .where(
                WorkflowDataSelectionRevision.workflow_id == workflow.id,
                WorkflowDataSelectionRevision.source_node_id == node.node_id,
            )
            .order_by(WorkflowDataSelectionRevision.revision_number.desc())
            .limit(1)
        )
        try:
            selection = selection_from_parameters(
                dict(node.parameters or {}),
                dataset_name=node.parameters.get("group_title") or node.label or node.node_id,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(409, "Restored source lacks exact data-selection custody") from exc
        await validate_selection(session, selection=selection, user_id=user_id, workflow_project_id=workflow.project_id)
        # Preserve legacy absence of revision history without skipping admission.
        if current is None and not record_initial:
            continue
        if current is not None and selection.model_dump(mode="json") == current.selection:
            continue
        session.add(
            WorkflowDataSelectionRevision(
                workflow_id=workflow.id,
                source_node_id=node.node_id,
                revision_number=current.revision_number + 1 if current is not None else 1,
                parent_revision_id=current.id if current is not None else None,
                created_by=user_id,
                origin="version_restore",
                reason=f"Restored workflow version {version_id}",
                idempotency_key=f"restore:{uuid.uuid4()}",
                selection=selection.model_dump(mode="json"),
                graph_digest=digest,
            )
        )
