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

from spectra_sherpa.app.core.path_security import resolve_existing_directory_path
from spectra_sherpa.app.models.batch_prediction import BatchPrediction
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.workflow import Workflow

logger = logging.getLogger(__name__)


def validate_folder_path(folder_path: str) -> Path:
    """Resolve and validate a user-supplied folder path.

    In multi-user modes (enterprise/hybrid/demo), the resolved path must be under
    ``settings.data_dir`` to prevent arbitrary filesystem traversal.
    In local mode, any accessible path is allowed (desktop app).

    Returns the resolved Path on success; raises ValueError otherwise.
    """
    return resolve_existing_directory_path(
        folder_path,
        label="Folder",
        restrict_to_data_dir_in_multi_user=True,
    )


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
        # File stability check.  Filesystems whose mtime resolution lags
        # ``time.time()`` (notably NTFS on Windows) can briefly report
        # ``mtime > now`` immediately after a write, so clamp negative ages
        # to zero — otherwise a freshly-touched file with ``settle_time=0``
        # would be incorrectly rejected as "not settled yet".
        try:
            age = max(0.0, now - f.stat().st_mtime)
            if age < settle_time_seconds:
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
    from spectra_sherpa.app.services.job_manager import job_manager
    from spectra_sherpa.app.services.serialization import serialize_result
    from spectra_sherpa.app.services.workflow_access import validate_workflow_execution_access

    total = len(files)
    success_count = 0
    error_count = 0
    all_model_ids: set[str] = set()

    try:
        await validate_workflow_execution_access(
            workflow.nodes,
            None,
            run.user_id,
            workflow.project_id,
            session,
        )
    except Exception as exc:
        run.status = "error"
        run.error = str(exc)
        run.results_summary = {
            "__batch__": {
                "total_files": total,
                "success_count": 0,
                "error_count": total,
            }
        }
        await session.commit()
        raise

    for idx, file_path in enumerate(files):
        start_ms = time.monotonic()
        executor = None

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
                        serialized[node_id] = serialize_result(results[node_id], owner_user_id=run.user_id)
                    except Exception:
                        serialized[node_id] = {"error": "serialization_failed"}

            # Extract model_id from executor's saved_artifacts (authoritative source)
            # and also from results dict (for LoadApplyModelNode pass-through)
            file_model_id = None
            if getattr(executor, "saved_artifacts", None):
                from spectra_sherpa.app.services.model_store import persist_model_artifact_records

                await persist_model_artifact_records(
                    session,
                    executor.saved_artifacts,
                    user_id=run.user_id,
                    workflow_id=workflow.id,
                    project_id=getattr(workflow, "project_id", None),
                    source_run_id=run.id,
                )
                file_model_id = executor.saved_artifacts[-1]["artifact_uid"]
                all_model_ids.update(a["artifact_uid"] for a in executor.saved_artifacts)

            # Also check results for model_id from LoadApplyModelNode (uses existing artifact)
            for node_id, node_result in results.items():
                if isinstance(node_result, dict) and "model_id" in node_result:
                    mid = node_result["model_id"]
                    if mid:
                        if file_model_id is None:
                            file_model_id = mid
                        all_model_ids.add(mid)

            elapsed_ms = int((time.monotonic() - start_ms) * 1000)

            prediction = BatchPrediction(
                run_id=run.id,
                file_name=file_path.name,
                file_path=str(file_path),
                status="completed",
                results=serialized,
                processing_time_ms=elapsed_ms,
                model_id=file_model_id,
            )
            session.add(prediction)
            success_count += 1

        except Exception as exc:
            # Roll back any dirty session state before attempting artifact persist
            await session.rollback()

            # Persist any model artifacts saved to disk before the error
            # to avoid orphan files with no DB records.
            if executor is not None and getattr(executor, "saved_artifacts", None):
                try:
                    from spectra_sherpa.app.services.model_store import persist_model_artifact_records

                    await persist_model_artifact_records(
                        session,
                        executor.saved_artifacts,
                        user_id=run.user_id,
                        workflow_id=workflow.id,
                        project_id=getattr(workflow, "project_id", None),
                        source_run_id=run.id,
                    )
                    all_model_ids.update(a["artifact_uid"] for a in executor.saved_artifacts)
                except Exception as art_err:
                    logger.warning("Could not persist model artifacts from failed file %s: %s", file_path.name, art_err)

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

        # Commit each prediction and update progress.
        # Wrap in try/except so a single poison-pill file (e.g. name exceeds
        # DB column limit, unique constraint violation) cannot kill the entire
        # batch loop.  Roll back the failed transaction, log it, and continue.
        try:
            await session.commit()
        except Exception as commit_exc:
            logger.error(
                "Batch predict DB commit failed for %s: %s — rolling back and continuing",
                file_path.name,
                commit_exc,
            )
            await session.rollback()
            # Fix counts: if the prediction succeeded but commit failed,
            # move it from success to error.  If it already failed, the
            # error was already counted — don't double-count.
            if prediction.status == "completed":
                success_count -= 1
                error_count += 1

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
    if all_model_ids:
        run.model_ids = sorted(all_model_ids)
        run.applied_artifact_uids = sorted(all_model_ids)
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
