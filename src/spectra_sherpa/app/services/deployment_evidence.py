"""Incremental operational evidence using the same saved-run retention authority."""

from asyncio import to_thread
from pathlib import Path

from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.services.run_output_retention import retain_run_outputs


def file_node(index: int, node_id: str) -> str:
    return f"file_{index}::{node_id}"


async def begin_deployment_evidence(run: ExecutionRun, workflow: Workflow, files: list[Path]) -> None:
    run.source_metadata = {
        **(run.source_metadata or {}),
        "retained_file_nodes": {
            str(path): [file_node(index, node.node_id) for node in workflow.nodes] for index, path in enumerate(files)
        },
    }
    definition = {
        "schema_version": 1,
        "name": run.name,
        "nodes": [
            {
                "node_id": file_node(index, node.node_id),
                "node_type": node.node_type,
                "label": f"{path.name}: {node.label or node.node_type}",
                "parameters": dict(node.parameters or {}),
                "position_x": node.position_x,
                "position_y": node.position_y,
            }
            for index, path in enumerate(files)
            for node in workflow.nodes
        ],
        "edges": [
            {
                "from_node_id": file_node(index, edge.from_node_id),
                "to_node_id": file_node(index, edge.to_node_id),
                "from_output": edge.from_output,
                "to_input": edge.to_input,
            }
            for index, _ in enumerate(files)
            for edge in workflow.edges
        ],
    }
    run.evidence_completeness = await to_thread(
        retain_run_outputs,
        run.user_id,
        {
            "__workflow__": {"definition": definition},
            "__application__": {
                "selection": {
                    "artifact_uids": run.attempted_artifact_uids,
                    "workflow_version_id": run.workflow_version_id,
                    "canonical_artifact_id": (run.source_metadata or {}).get("canonical_artifact_id"),
                    "canonical_artifact_digest": (run.source_metadata or {}).get("canonical_artifact_digest"),
                    "canonical_plan_digest": (run.source_metadata or {}).get("canonical_plan_digest"),
                    "canonical_application_plan": (run.source_metadata or {}).get("canonical_application_plan"),
                    "files": [str(path) for path in files],
                    "asset_id": (run.source_metadata or {}).get("asset_id"),
                }
            },
        },
        {},
    )
    run.node_statuses = {node["node_id"]: "pending" for node in definition["nodes"]}
    run.diagnostics = {"_scientific_values": {}, "_scientific_presentations": {}}


def _describe_execution(execution, index):
    from spectra_sherpa.app.services.dag.presentation_contract import describe_executed_presentations
    from spectra_sherpa.app.services.dag.scientific_values import describe_node_outputs

    descriptors = {
        key: describe_node_outputs(execution.executor.nodes[key].metadata, value)
        for key, value in execution.results.items()
    }
    return {
        "_scientific_values": {file_node(index, key): value for key, value in descriptors.items()},
        "_scientific_presentations": {
            file_node(index, key): describe_executed_presentations(execution.executor.nodes[key].metadata, value)
            for key, value in descriptors.items()
        },
        **{file_node(index, key): value for key, value in execution.executor.diagnostics.items()},
    }


async def append_deployment_evidence(
    run: ExecutionRun, workflow: Workflow, index: int, execution=None, error=None, dataset=None
) -> None:
    statuses = dict(run.node_statuses or {})
    results = (
        execution.results
        if execution is not None
        else {
            node.node_id: {"default": dataset}
            for node in workflow.nodes
            if dataset is not None and node.node_type == "deploy.input"
        }
    )
    diagnostics = {
        file_node(index, node.node_id): {"error": str(error)}
        for node in workflow.nodes
        if error is not None and node.node_id not in results
    }
    if results or diagnostics:
        run.evidence_completeness = await to_thread(
            retain_run_outputs,
            run.user_id,
            {file_node(index, node_id): output for node_id, output in results.items()},
            diagnostics,
            previous=run.evidence_completeness,
        )
    for node in workflow.nodes:
        actual = execution.executor.nodes.get(node.node_id) if execution is not None else None
        statuses[file_node(index, node.node_id)] = (
            actual.status.value
            if actual is not None
            else ("completed" if node.node_id in results else "error" if error is not None else "pending")
        )
    run.node_statuses = statuses
    if execution is not None:
        diagnostics = dict(run.diagnostics or {})
        for key, value in (await to_thread(_describe_execution, execution, index)).items():
            diagnostics[key] = {**diagnostics.get(key, {}), **value} if key.startswith("_scientific_") else value
        run.diagnostics = diagnostics


async def finalize_deployment_evidence(run: ExecutionRun) -> None:
    run.evidence_completeness = await to_thread(
        retain_run_outputs,
        run.user_id,
        {},
        run.diagnostics or {},
        previous=run.evidence_completeness,
    )
