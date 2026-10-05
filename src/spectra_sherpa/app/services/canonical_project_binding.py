"""Bind a scientist-selected local source to an imported canonical project.

The sealed canonical package deliberately contains no sample data and no
caller-chosen file path.  This service is the one local, visible binding step:
it creates or updates a typed source node in the importing user's project,
without changing any admitted application node or fitted-state identity.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_edge import WorkflowEdge
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.services.audit.emitter import audit_emitter
from spectra_sherpa.app.services.canonical_project_custody import (
    CanonicalArtifactReadGrant,
    CanonicalProjectCustodyError,
    resolve_canonical_application_plan_provenance,
    resolve_canonical_artifact_read_grant,
)
from spectra_sherpa.app.services.canonical_project_dependencies import canonical_project_dependency_readiness
from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash
from spectra_sherpa.app.services.project_data_sources import sync_workflow_data_sources
from spectra_sherpa.app.services.workflow_access import (
    CANONICAL_LOCAL_SOURCE_NODE_ID,
    canonical_application_integrity_hash,
    require_experiment_access,
    require_file_access,
)


class CanonicalProjectBindingError(ValueError):
    """An imported canonical project cannot accept the requested local source."""


@dataclass(frozen=True)
class CanonicalProjectBindingResult:
    """The durable source and artifact identities an executor may use."""

    workflow_id: int
    source_node_id: str
    integrity_hash: str
    artifact_read_grant: CanonicalArtifactReadGrant
    status: str


async def bind_canonical_project_source(
    session: AsyncSession,
    *,
    user_id: int,
    workflow_id: int,
    experiment_id: int,
    file_id: int,
    stage: str,
    asset_id: str | None = None,
) -> CanonicalProjectBindingResult:
    """Persist one owned file source before canonical application execution.

    A caller may replace the local input later, but cannot alter the admitted
    artifact-bound application nodes.  Runtime ``initial_data`` is rejected
    for this source by the execution route so the visible, integrity-hashed
    binding is always the source that actually ran.
    """

    workflow = await session.scalar(
        select(Workflow)
        .where(Workflow.id == workflow_id, Workflow.user_id == user_id)
        .options(selectinload(Workflow.nodes), selectinload(Workflow.edges))
    )
    if workflow is None or workflow.project_id is None:
        raise CanonicalProjectBindingError("canonical project workflow is unavailable")

    try:
        grant = await resolve_canonical_artifact_read_grant(session, user_id=user_id, workflow_id=workflow.id)
    except CanonicalProjectCustodyError as exc:
        raise CanonicalProjectBindingError("canonical project artifact custody is unavailable") from exc

    if canonical_application_integrity_hash(workflow.nodes, workflow.edges) != grant.application_integrity_hash:
        raise CanonicalProjectBindingError("canonical application graph is unavailable")
    try:
        provenance = await resolve_canonical_application_plan_provenance(
            session,
            user_id=user_id,
            workflow_id=workflow.id,
        )
    except CanonicalProjectCustodyError as exc:
        raise CanonicalProjectBindingError("canonical application provenance is unavailable") from exc
    dependency_readiness = canonical_project_dependency_readiness(provenance.application_plan)

    await require_experiment_access(session, experiment_id, user_id, workflow.project_id)
    await require_file_access(session, experiment_id, file_id, user_id, stage)

    # Re-admit the exact asset before persisting the source identity. A single-
    # asset source may omit the field; a multi-asset source never may.
    from spectra_sherpa.app.services.model_application import load_project_dataset

    try:
        await load_project_dataset(
            session,
            user_id=user_id,
            experiment_id=experiment_id,
            stage=stage,
            file_id=file_id,
            asset_id=asset_id,
        )
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise CanonicalProjectBindingError("canonical project scientific asset is unavailable") from exc

    source_parameters = {"experiment_id": experiment_id, "file_id": file_id, "stage": stage}
    if asset_id is not None:
        source_parameters["asset_id"] = asset_id
    source = next((node for node in workflow.nodes if node.node_id == CANONICAL_LOCAL_SOURCE_NODE_ID), None)
    application_nodes = [node for node in workflow.nodes if node.node_id != CANONICAL_LOCAL_SOURCE_NODE_ID]
    if not application_nodes:
        raise CanonicalProjectBindingError("canonical project has no application path")
    first_application_node = min(
        application_nodes,
        key=lambda node: (node.execution_order if node.execution_order is not None else 2**31, node.id),
    )
    if source is not None:
        if source.node_type != "data.file_load":
            raise CanonicalProjectBindingError("canonical local source identity is unavailable")
        source.parameters = source_parameters
        source.execution_order = 0
        expected_edge = (
            CANONICAL_LOCAL_SOURCE_NODE_ID,
            "default",
            first_application_node.node_id,
            "default",
        )
        source_edges = [
            edge
            for edge in workflow.edges
            if edge.from_node_id == CANONICAL_LOCAL_SOURCE_NODE_ID or edge.to_node_id == CANONICAL_LOCAL_SOURCE_NODE_ID
        ]
        if (
            len(source_edges) != 1
            or (
                source_edges[0].from_node_id,
                source_edges[0].from_output,
                source_edges[0].to_node_id,
                source_edges[0].to_input,
            )
            != expected_edge
        ):
            raise CanonicalProjectBindingError("canonical local source topology is unavailable")
    else:
        for node in application_nodes:
            if node.execution_order is not None:
                node.execution_order += 1
        source = WorkflowNode(
            workflow_id=workflow.id,
            node_id=CANONICAL_LOCAL_SOURCE_NODE_ID,
            node_type="data.file_load",
            parameters=source_parameters,
            execution_order=0,
        )
        session.add(source)
        session.add(
            WorkflowEdge(
                workflow_id=workflow.id,
                from_node_id=CANONICAL_LOCAL_SOURCE_NODE_ID,
                from_output="default",
                to_node_id=first_application_node.node_id,
                to_input="default",
            )
        )
        await session.flush()
        await session.refresh(workflow, attribute_names=["nodes", "edges"])

    node_records = [
        {"node_id": node.node_id, "node_type": node.node_type, "parameters": node.parameters} for node in workflow.nodes
    ]
    edge_records = [
        {
            "from_node_id": edge.from_node_id,
            "from_output": edge.from_output,
            "to_node_id": edge.to_node_id,
            "to_input": edge.to_input,
        }
        for edge in workflow.edges
    ]
    workflow.integrity_hash = compute_workflow_hash(node_records, edge_records)
    workflow.status = "active" if dependency_readiness.ready else "dependency_blocked"
    await sync_workflow_data_sources(workflow, session, workflow.nodes)
    audit_emitter.emit(
        session=session,
        action="workflow.canonical_source_bound",
        target_type="Workflow",
        target_id=workflow.id,
        after={
            "project_id": workflow.project_id,
            "source_node_id": CANONICAL_LOCAL_SOURCE_NODE_ID,
            "experiment_id": experiment_id,
            "file_id": file_id,
            "stage": stage,
            "asset_id": asset_id,
            "artifact_digest": grant.artifact_digest,
            "application_integrity_hash": grant.application_integrity_hash,
        },
    )
    await session.flush()
    if not workflow.integrity_hash:
        raise CanonicalProjectBindingError("canonical local source integrity is unavailable")
    return CanonicalProjectBindingResult(
        workflow_id=workflow.id,
        source_node_id=CANONICAL_LOCAL_SOURCE_NODE_ID,
        integrity_hash=workflow.integrity_hash,
        artifact_read_grant=grant,
        status=workflow.status,
    )


__all__ = [
    "CANONICAL_LOCAL_SOURCE_NODE_ID",
    "CanonicalProjectBindingError",
    "CanonicalProjectBindingResult",
    "bind_canonical_project_source",
]
