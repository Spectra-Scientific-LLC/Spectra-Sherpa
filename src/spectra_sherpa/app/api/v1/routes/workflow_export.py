"""
API endpoints for workflow export and documentation.
"""

from __future__ import annotations

from asyncio import to_thread
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.core.security import check_export_allowed
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.schemas.run_evidence import EvidenceGap, RunEvidence
from spectra_sherpa.core.node_identity import canonicalize_serialized_workflow

router = APIRouter(prefix="/workflows")


@router.get("/{workflow_id}/export/markdown", response_class=PlainTextResponse)
async def export_workflow_to_markdown(
    workflow_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> str:
    """
    Export a workflow as a comprehensive Markdown document.

    Includes workflow metadata, nodes, edges, annotations, and documentation.
    """
    if not await check_export_allowed(current_user):
        raise HTTPException(status_code=403, detail="Export not permitted for this user")

    user_id = current_user.id

    # Load workflow with all relationships
    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .where(Workflow.user_id == user_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.tags),
            selectinload(Workflow.folder),
            selectinload(Workflow.versions),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Generate markdown documentation
    md_lines = []

    # Title and metadata
    md_lines.append(f"# {workflow.name}\n")

    if workflow.description:
        md_lines.append(f"{workflow.description}\n")

    md_lines.append("## Metadata\n")
    md_lines.append(f"- **Status**: {workflow.status}")
    md_lines.append(f"- **Created**: {workflow.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
    md_lines.append(f"- **Updated**: {workflow.updated_at.strftime('%Y-%m-%d %H:%M:%S')}")

    if workflow.last_executed_at:
        md_lines.append(f"- **Last Executed**: {workflow.last_executed_at.strftime('%Y-%m-%d %H:%M:%S')}")

    if workflow.folder:
        md_lines.append(f"- **Folder**: {workflow.folder.name}")

    if workflow.tags:
        tags_str = ", ".join([tag.name for tag in workflow.tags])
        md_lines.append(f"- **Tags**: {tags_str}")

    if workflow.integrity_hash:
        md_lines.append(f"- **Integrity Hash**: `{workflow.integrity_hash}`")

    md_lines.append(f"- **Nodes**: {len(workflow.nodes)}")
    md_lines.append(f"- **Edges**: {len(workflow.edges)}")

    # Version history
    if workflow.versions:
        md_lines.append("\n## Version History\n")
        md_lines.append(f"Total versions: {len(workflow.versions)}\n")
        md_lines.append("| Version | Date | Description |")
        md_lines.append("|---------|------|-------------|")
        for version in workflow.versions:
            date_str = version.created_at.strftime("%Y-%m-%d %H:%M")
            desc = version.change_description or "No description"
            md_lines.append(f"| {version.version_number} | {date_str} | {desc} |")

    # Workflow notes
    if workflow.notes:
        md_lines.append("\n## Workflow Notes\n")
        md_lines.append(workflow.notes)

    # Nodes
    md_lines.append("\n## Workflow Nodes\n")
    md_lines.append(f"Total nodes: {len(workflow.nodes)}\n")

    # Group nodes by type
    nodes_by_type: dict[str, list] = {}
    for node in workflow.nodes:
        node_category = node.node_type.split(".")[0]  # e.g., "model" from "model.pca"
        if node_category not in nodes_by_type:
            nodes_by_type[node_category] = []
        nodes_by_type[node_category].append(node)

    for category, nodes in sorted(nodes_by_type.items()):
        md_lines.append(f"### {category.capitalize()} Nodes\n")

        for node in nodes:
            label = node.label or node.node_type
            md_lines.append(f"#### {label}\n")
            md_lines.append(f"- **Type**: `{node.node_type}`")
            md_lines.append(f"- **ID**: `{node.node_id}`")
            md_lines.append(f"- **Status**: {node.status}")

            if node.parameters:
                md_lines.append("- **Parameters**:")
                for key, value in node.parameters.items():
                    md_lines.append(f"  - `{key}`: {value}")

            if node.annotation:
                md_lines.append(f"\n**Annotation**:\n{node.annotation}\n")

            md_lines.append("")  # Blank line

    # Edges (connections)
    if workflow.edges:
        md_lines.append("\n## Workflow Connections\n")
        md_lines.append(f"Total connections: {len(workflow.edges)}\n")
        md_lines.append("| From | To | Ports |")
        md_lines.append("|------|-----|-------|")

        for edge in workflow.edges:
            from_label = next(
                (n.label or n.node_type for n in workflow.nodes if n.node_id == edge.from_node_id),
                edge.from_node_id,
            )
            to_label = next(
                (n.label or n.node_type for n in workflow.nodes if n.node_id == edge.to_node_id),
                edge.to_node_id,
            )
            ports = f"{edge.from_output} → {edge.to_input}"
            md_lines.append(f"| {from_label} | {to_label} | {ports} |")

    # Footer
    md_lines.append("\n---\n")
    md_lines.append(f"*Exported from Workflow Builder on {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC*")

    return "\n".join(md_lines)


@router.get("/{workflow_id}/export/report-data")
async def get_report_data(
    workflow_id: int,
    run_ids: str | None = Query(None, description="Comma-separated run IDs"),
    include_row_level_plots: bool = Query(
        False, description="Opt in to exporting reference, prediction and residual values"
    ),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    Structural data for provenance report.

    Returns workflow metadata, topologically sorted nodes with parameters,
    edges, and integrity hash. Optionally includes execution run data and
    comparison metrics when ``run_ids`` are provided.
    """
    if not await check_export_allowed(current_user):
        raise HTTPException(status_code=403, detail="Export not permitted for this user")

    # Parse comma-separated run IDs
    parsed_run_ids: list[int] | None = None
    if run_ids:
        try:
            parsed_run_ids = [int(x.strip()) for x in run_ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(status_code=422, detail="run_ids must be comma-separated integers")
        if not parsed_run_ids or len(parsed_run_ids) > 10 or any(value < 1 for value in parsed_run_ids):
            raise HTTPException(status_code=422, detail="Select between 1 and 10 positive run IDs")

    user_id = current_user.id

    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id)
        .where(Workflow.user_id == user_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.primary_data_source),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()

    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Topological sort via Kahn's algorithm
    deps: dict[str, list[str]] = {n.node_id: [] for n in workflow.nodes}
    for edge in workflow.edges:
        if edge.to_node_id in deps:
            deps[edge.to_node_id].append(edge.from_node_id)

    in_degree = {nid: len(d) for nid, d in deps.items()}
    reverse_deps: dict[str, list[str]] = {nid: [] for nid in deps}
    for nid, dep_list in deps.items():
        for dep in dep_list:
            if dep in reverse_deps:
                reverse_deps[dep].append(nid)

    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    sorted_ids: list[str] = []
    while queue:
        nid = queue.pop(0)
        sorted_ids.append(nid)
        for dependent in reverse_deps.get(nid, []):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    node_map = {n.node_id: n for n in workflow.nodes}
    sorted_nodes = [
        {
            "node_id": node_map[nid].node_id,
            "node_type": node_map[nid].node_type,
            "label": node_map[nid].label or node_map[nid].node_type,
            "parameters": node_map[nid].parameters or {},
            "position_x": node_map[nid].position_x,
            "position_y": node_map[nid].position_y,
        }
        for nid in sorted_ids
        if nid in node_map
    ]

    response: dict[str, Any] = {
        "workflow_id": workflow.id,
        "name": workflow.name,
        "description": workflow.description,
        "purpose": workflow.purpose,
        "technique": getattr(workflow, "technique", None),
        "sample_type": getattr(workflow, "sample_type", None),
        "integrity_hash": workflow.integrity_hash,
        "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
        "updated_at": workflow.updated_at.isoformat() if workflow.updated_at else None,
        "nodes": sorted_nodes,
        "edges": [
            {
                "from_node_id": e.from_node_id,
                "to_node_id": e.to_node_id,
                "from_output": e.from_output,
                "to_input": e.to_input,
            }
            for e in workflow.edges
        ],
        "workflow_identity": _workflow_identity(workflow),
    }

    # Optionally include execution run data
    if parsed_run_ids:
        run_query = (
            select(ExecutionRun)
            .where(
                ExecutionRun.workflow_id == workflow_id,
                ExecutionRun.user_id == user_id,
                ExecutionRun.id.in_(parsed_run_ids),
            )
            .order_by(ExecutionRun.id)
        )
        run_result = await session.execute(run_query)
        runs = list(run_result.scalars().all())
        if len(runs) != len(set(parsed_run_ids)):
            raise HTTPException(status_code=404, detail="One or more selected runs are unavailable in this workflow")

        saved_definitions = await to_thread(lambda: [_saved_report_definition(run) for run in runs])
        from spectra_sherpa.app.services.run_validation_summary import validation_summary

        validation_summaries = await to_thread(
            lambda: [
                validation_summary(run, definition, include_row_level_plots=include_row_level_plots is True)
                for run, definition in zip(runs, saved_definitions)
            ]
        )
        # Never attach the current edited canvas to historical measurements.
        common_definition = saved_definitions[0] if saved_definitions else None
        if common_definition is None or any(value != common_definition for value in saved_definitions):
            common_definition = None
        response.update(
            name=common_definition.get("name", runs[0].name) if common_definition else "Selected saved runs",
            description=None,
            purpose=None,
            technique=None,
            sample_type=None,
            created_at=None,
            updated_at=None,
            integrity_hash=runs[0].integrity_hash if common_definition else None,
            nodes=common_definition.get("nodes", []) if common_definition else [],
            edges=common_definition.get("edges", []) if common_definition else [],
            workflow_identity=_workflow_identity(workflow, definition=common_definition),
        )

        response["runs"] = [
            {
                "id": r.id,
                "name": r.name,
                "status": r.status,
                "executed_at": r.executed_at.isoformat() if r.executed_at else None,
                "results_summary": r.results_summary or {},
                "diagnostics": r.diagnostics,
                "params_snapshot": r.params_snapshot or {},
                "node_statuses": r.node_statuses,
                "integrity_hash": r.integrity_hash,
                "labels": r.labels,
                "selection_provenance": {
                    "schema_version": 1,
                    "state": ("exact" if (r.source_metadata or {}).get("data_selection_revisions") else "unavailable"),
                    "reason": (
                        None
                        if (r.source_metadata or {}).get("data_selection_revisions")
                        else "This run predates sheet-specific data-selection revisions."
                    ),
                    "revisions": (r.source_metadata or {}).get("data_selection_revisions", []),
                    "scientific_receipts": (r.source_metadata or {}).get("dataset_scientific_receipts", []),
                    "executor_user_id": r.user_id,
                    "workflow_version_id": r.workflow_version_id,
                },
                "saved_definition": definition,
                "validation_summary": summary,
                "workflow_identity": _workflow_identity(workflow, definition=definition),
                "evidence_gaps": [item.model_dump() for item in _run_evidence_gaps(r)],
                "evidence_notice": (
                    (
                        "Saved run has incomplete durable evidence. Review the named node outputs and recovery actions."
                        if _run_evidence_gaps(r)
                        else (
                            "Saved summary, not the complete live session. "
                            "No retained output gaps are declared for this run."
                        )
                    )
                    if definition is not None
                    else (
                        "Saved workflow evidence is unavailable or unverified. "
                        "Current workflow details were not substituted."
                    )
                ),
            }
            for r, definition, summary in zip(runs, saved_definitions, validation_summaries)
        ]

        # Compute comparison diff when 2+ runs
        if len(runs) >= 2:
            response["comparison"] = await to_thread(_build_comparison, runs)
        else:
            response["comparison"] = None

    return response


def _workflow_identity(workflow: Workflow, *, definition: dict | None = None) -> dict[str, Any]:
    """Return the stable sheet and source identity shown in reports and exports."""

    source_name = workflow.primary_data_source.display_name if workflow.primary_data_source is not None else None
    source_origin = workflow.data_origin
    source_node_id = None
    if definition is not None:
        context = definition.get("data_context") if isinstance(definition.get("data_context"), dict) else {}
        source_name = context.get("source_name") or source_name
        source_origin = context.get("source_origin") if context.get("source_origin") is not None else source_origin
        for node in definition.get("nodes", []):
            if node.get("node_type") not in {"data.file_load", "data.collection_load"}:
                continue
            source_node_id = node.get("node_id")
            break
    return {
        "schema_version": 1,
        "project_id": workflow.project_id,
        "workflow_id": workflow.id,
        "workflow_name": definition.get("name", workflow.name) if definition is not None else workflow.name,
        "template_name": workflow.created_from_template_name,
        "template_version": workflow.created_from_template_version,
        "source_name": source_name,
        "source_origin": source_origin if source_origin in {"current", "example"} else None,
        "source_node_id": source_node_id,
    }


def _build_comparison(runs: list[ExecutionRun]) -> dict[str, Any]:
    from spectra_sherpa.app.services.run_metrics import comparison_response

    return comparison_response(runs).model_dump()


def _run_evidence_gaps(run: ExecutionRun) -> list[EvidenceGap]:
    """Project supported retained evidence without trusting legacy JSON."""

    try:
        return RunEvidence.model_validate(run.evidence_completeness or {}).gaps()
    except (ValueError, TypeError):
        return [
            EvidenceGap(
                node_id="__workflow__",
                output="retention",
                state="unverified",
                category="unverified",
                reason="Historical evidence completeness is unavailable or unsupported.",
                recovery="Rerun this workflow to create a qualified durable record.",
            )
        ]


def _saved_report_definition(run: ExecutionRun) -> dict | None:
    from spectra_sherpa.app.services.run_output_retention import read_output

    try:
        evidence = RunEvidence.model_validate(run.evidence_completeness)
        item = evidence.outputs.get("__workflow__", {}).get("definition")
        if evidence.qualification != "qualified" or item is None or item.state != "exact":
            return None
        if item.byte_count is None or item.byte_count > 2 * 1024 * 1024:
            return None
        definition = read_output(run.user_id, item)
        if not isinstance(definition, dict) or definition.get("schema_version") != 1:
            return None
        return canonicalize_serialized_workflow(definition)
    except (ValueError, OSError, TypeError):
        return None
