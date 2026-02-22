"""
Batch prediction engine — shared by Experiments batch runs and Deploy folder watches.

Discovers spectral files in a folder, executes each through a workflow DAG,
and stores per-file results as BatchPrediction rows under a parent ExecutionRun.
"""

from __future__ import annotations

import fnmatch
import logging
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.models.batch_prediction import BatchPrediction
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.workflow import Workflow

logger = logging.getLogger(__name__)



def validate_folder_path(folder_path: str) -> Path:
    """Resolve and validate a user-supplied folder path.

    In multi-user modes (hybrid/demo), the resolved path must be under
    ``settings.data_dir`` to prevent arbitrary filesystem traversal.
    In local mode, any accessible path is allowed (single-user desktop).

    Returns the resolved Path on success; raises ValueError otherwise.
    """
    from spectra_sherpa.app.core.config import settings
    from spectra_sherpa.app.core.mode_policy import is_local

    resolved = Path(folder_path).expanduser().resolve()

    if not is_local():
        allowed_root = Path(settings.data_dir).resolve()
        try:
            resolved.relative_to(allowed_root)
        except ValueError:
            raise ValueError(f"Folder path must be under the data directory " f"({allowed_root}). Got: {resolved}")

    return resolved


def discover_files(
    folder_path: str,
    file_pattern: str = "*",
    *,
    exclude_names: set[str] | None = None,
    settle_time_seconds: int = 2,
) -> list[Path]:
    """
    Discover spectral files matching a glob pattern in a server folder.

    Mirrors LoadGroupNode logic: case-insensitive fnmatch, skip hidden files,
    sort alphabetically.  Skips files still being written (mtime < 5s ago).

    Args:
        folder_path: Absolute or user-expandable path to the folder.
        file_pattern: Glob pattern (e.g. ``"*.spa"``, ``"*"``).
        exclude_names: Optional set of full path strings or filenames to skip
            (already processed).  Both ``str(path)`` and ``path.name`` are
            checked for backward compatibility with existing watch state.

    Returns:
        Sorted list of Path objects for matched files.

    Raises:
        ValueError: If the folder does not exist or contains no matching files.
    """
    folder = validate_folder_path(folder_path)

    if not folder.exists():
        raise ValueError(f"Folder does not exist: {folder}")
    if not folder.is_dir():
        raise ValueError(f"Path is not a directory: {folder}")

    now = time.time()
    exclude = exclude_names or set()
    matched: list[Path] = []

    for f in folder.iterdir():
        if not f.is_file():
            continue
        # Skip hidden / system files
        if f.name.startswith((".", "__")):
            continue
        # Skip already-processed files (check both full path and filename
        # for backward compatibility with older processed_files dicts)
        if str(f) in exclude or f.name in exclude:
            continue
        # File stability check
        try:
            if (now - f.stat().st_mtime) < settle_time_seconds:
                continue
        except OSError:
            continue
        # Case-insensitive pattern match
        if file_pattern != "*":
            if not fnmatch.fnmatch(f.name.lower(), file_pattern.lower()):
                continue
        matched.append(f)

    matched.sort(key=lambda p: p.name.lower())
    return matched


def load_single_file(file_path: Path) -> Any:
    """
    Load a single spectral file into a SherpaDataset.

    Uses ``get_reader_for_extension()`` to pick the correct SpectroChemPy reader,
    then ensures the result is 2-D.

    Returns:
        SherpaDataset with shape (n_samples, n_features).

    Raises:
        ValueError: If the extension is unsupported or reading fails.
    """
    from spectra_sherpa.app.core.config import get_reader_for_extension
    from spectra_sherpa.app.lib.scp_compat import require_scp, scp

    require_scp("Batch prediction")

    ext = file_path.suffix
    reader_name = get_reader_for_extension(ext)
    reader_fn = getattr(scp, reader_name)
    dataset = reader_fn(str(file_path))

    # Ensure 2-D
    if dataset.ndim == 1:
        dataset = dataset.reshape(1, -1)

    return dataset


def build_executor_from_workflow(workflow: Workflow) -> Any:
    """
    Build a DAGExecutor from a saved workflow's nodes and edges.

    Mirrors predict.py:152-179.

    Returns:
        A DAGExecutor ready for inject_result() + execute().
    """
    from spectra_sherpa.app.services.dag import DAGExecutor
    from spectra_sherpa.app.services.dag import WorkflowEdge as DAGEdge
    from spectra_sherpa.app.services.dag import WorkflowNode as DAGNode

    executor = DAGExecutor()

    for node in workflow.nodes:
        dag_node = DAGNode(
            node_id=node.node_id,
            node_type=node.node_type,
            parameters=node.parameters,
            position=({"x": node.position_x, "y": node.position_y} if node.position_x and node.position_y else None),
        )
        executor.add_node(dag_node)

    for edge in workflow.edges:
        dag_edge = DAGEdge(
            from_node=edge.from_node_id,
            to_node=edge.to_node_id,
            from_output=edge.from_output,
            to_input=edge.to_input,
        )
        executor.add_edge(dag_edge)

    return executor


async def run_batch_prediction(
    session: AsyncSession,
    job_id: int,
    run: ExecutionRun,
    workflow: Workflow,
    files: list[Path],
) -> None:
    """
    Execute a workflow on each file and save per-file BatchPrediction rows.

    Progress is broadcast via the job manager's WebSocket system.

    Args:
        session: Active async DB session.
        job_id: BackgroundJob ID for progress updates.
        run: Parent ExecutionRun (already committed).
        workflow: Workflow with eagerly-loaded nodes + edges.
        files: List of file paths to process.
    """
    from spectra_sherpa.app.api.v1.routes.workflows import serialize_result
    from spectra_sherpa.app.services.job_manager import job_manager

    total = len(files)
    success_count = 0
    error_count = 0

    for idx, file_path in enumerate(files):
        start_ms = time.monotonic()

        try:
            dataset = load_single_file(file_path)

            # Fresh executor per file — no cache contamination
            executor = build_executor_from_workflow(workflow)

            entry_nodes = executor.find_entry_nodes()
            if not entry_nodes:
                raise ValueError("Workflow has no entry nodes")

            for node_id in entry_nodes:
                executor.inject_result(node_id, dataset)

            results = await executor.execute()

            # Collect exit-node results
            exit_nodes = executor.find_exit_nodes()
            serialized: dict[str, Any] = {}
            for node_id in exit_nodes:
                if node_id in results:
                    try:
                        serialized[node_id] = serialize_result(results[node_id])
                    except Exception:
                        serialized[node_id] = {"error": "serialization_failed"}

            elapsed_ms = int((time.monotonic() - start_ms) * 1000)

            prediction = BatchPrediction(
                run_id=run.id,
                file_name=file_path.name,
                file_path=str(file_path),
                status="completed",
                results=serialized,
                processing_time_ms=elapsed_ms,
            )
            session.add(prediction)
            success_count += 1

        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start_ms) * 1000)
            prediction = BatchPrediction(
                run_id=run.id,
                file_name=file_path.name,
                file_path=str(file_path),
                status="error",
                error_message=str(exc),
                processing_time_ms=elapsed_ms,
            )
            session.add(prediction)
            error_count += 1
            logger.warning("Batch predict failed for %s: %s", file_path.name, exc)

        # Commit each prediction and update progress
        await session.commit()

        progress = int(((idx + 1) / total) * 100)
        await job_manager.update_progress(
            session,
            job_id,
            progress,
            message=f"Processed {idx + 1}/{total}: {file_path.name}",
        )

    # Update parent ExecutionRun with aggregate metrics
    run.status = "completed" if error_count == 0 else "partial"
    run.results_summary = {
        "__batch__": {
            "total_files": total,
            "success_count": success_count,
            "error_count": error_count,
        }
    }
    await session.commit()
    logger.info(
        "Batch prediction complete: %d/%d succeeded for run %d",
        success_count,
        total,
        run.id,
    )


async def load_workflow_with_graph(session: AsyncSession, workflow_id: int, user_id: int) -> Workflow:
    """Load workflow with eagerly-loaded nodes and edges, with ownership check."""
    query = (
        select(Workflow)
        .where(Workflow.id == workflow_id, Workflow.user_id == user_id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.versions),
        )
    )
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise ValueError(f"Workflow {workflow_id} not found or not owned by user")
    return workflow
