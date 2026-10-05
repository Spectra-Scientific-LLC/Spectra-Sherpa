"""
Batch prediction engine — shared by Experiments batch runs and Deploy folder watches.

Discovers spectral files in a folder, executes each through a workflow DAG,
and stores per-file results as BatchPrediction rows under a parent ExecutionRun.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.core.path_security import resolve_existing_directory_path
from spectra_sherpa.app.models.batch_prediction import BatchPrediction
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.workflow import Workflow

logger = logging.getLogger(__name__)

# Directory discovery is an operational input boundary, not an invitation to
# materialize an arbitrarily large server directory. These deliberately
# generous ceilings cover ordinary laboratory drop folders while keeping both
# enumeration time and the in-memory result list finite.
MAX_DIRECTORY_ENTRIES = 10_000
MAX_DISCOVERED_FILES = 1_000


@dataclass(frozen=True)
class WorkflowDatasetExecution:
    """Completed per-dataset execution projected outside its worker thread."""

    executor: Any
    results: dict[str, Any]
    serialized_exit_results: dict[str, Any]


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


async def validate_user_folder_path(session: AsyncSession, folder_path: str, user_id: int) -> Path:
    """Validate a folder path and, in multi-user modes, bind it to the user.

    Server-side folder watches and batch predictions can read every file in the
    configured folder. In multi-user deployments, accepting any path under the
    shared DATA_DIR would let one tenant ingest another tenant's experiment
    files if they guessed the directory. Require the folder to live under one
    of the requesting user's experiment directories.
    """
    folder = validate_folder_path(folder_path)

    from spectra_sherpa.app.core.mode_policy import is_multi_user
    from spectra_sherpa.app.services.experiments import experiment_dir

    if not is_multi_user():
        return folder

    result = await session.execute(select(Experiment.id).where(Experiment.user_id == user_id))
    for experiment_id in result.scalars().all():
        root = experiment_dir(int(experiment_id)).resolve()
        try:
            folder.relative_to(root)
            return folder
        except ValueError:
            continue

    raise ValueError("Folder must be under one of your experiment directories")


def discover_files(
    folder_path: str,
    file_pattern: str = "*",
    *,
    exclude_names: set[str] | None = None,
    settle_time_seconds: int = 2,
    max_directory_entries: int = MAX_DIRECTORY_ENTRIES,
    max_discovered_files: int = MAX_DISCOVERED_FILES,
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

    entries_seen = 0
    for f in folder.iterdir():
        entries_seen += 1
        if entries_seen > max_directory_entries:
            raise ValueError(
                f"Folder contains more than {max_directory_entries:,} entries. "
                "Move the intended spectra into a smaller batch folder."
            )
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
        if len(matched) > max_discovered_files:
            raise ValueError(
                f"Folder contains more than {max_discovered_files:,} matching files. "
                "Process the spectra in smaller batches."
            )

    matched.sort(key=lambda p: p.name.lower())
    return matched


def load_single_file(file_path: Path, *, asset_id: str | None = None) -> Any:
    """
    Load a single spectral file into a SherpaDataset.

    Uses the frozen structural ingestion registry and requires one explicit
    asset; multi-asset sources are never flattened for prediction.

    Returns:
        SherpaDataset with shape (n_samples, n_features).

    Raises:
        ValueError: If the extension is unsupported or reading fails.
    """
    from spectra_sherpa.app.lib.reference_materialization import materialize_reference_member
    from spectra_sherpa.app.lib.registered_reference_storage import read_registered_reference_sidecar
    from spectra_sherpa.io import ingest, select_asset

    registered_reference = read_registered_reference_sidecar(file_path)
    if registered_reference is not None:
        projection_id = str(registered_reference["projection_id"])
        if asset_id is not None and asset_id != projection_id:
            raise ValueError("requested asset differs from the registered reference projection")
        materialized = materialize_reference_member(file_path, projection_id)
        if dict(materialized.portable_reference) != dict(registered_reference):
            raise ValueError("registered reference identity changed during prediction admission")
        return materialized.dataset

    result = ingest(file_path)
    return select_asset(result, asset_id=asset_id).dataset


def build_executor_from_workflow(
    workflow: Workflow, *, canonical_read_grant: Any = None, uncertainty_provider: Any = None
) -> Any:
    """
    Build a DAGExecutor from a saved workflow's nodes and edges.

    Mirrors predict.py:152-179.

    Returns:
        A DAGExecutor ready for inject_result() + execute().
    """
    from spectra_sherpa.app.services.dag import DAGExecutor
    from spectra_sherpa.app.services.dag import WorkflowEdge as DAGEdge
    from spectra_sherpa.app.services.dag import WorkflowNode as DAGNode
    from spectra_sherpa.app.services.execution_runtime import build_application_execution_runtime

    executor = DAGExecutor(
        runtime=replace(
            build_application_execution_runtime(canonical_artifact_read_grant=canonical_read_grant),
            prediction_uncertainty=uncertainty_provider,
        )
    )

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


def _execute_workflow_dataset_blocking(
    workflow: Workflow,
    dataset: Any,
    *,
    owner_user_id: int,
    canonical_read_grant: Any = None,
    uncertainty_provider: Any = None,
) -> WorkflowDatasetExecution:
    """Execute and serialize one dataset in a worker thread.

    A DAG may contain a deliberately in-process node. Running its private
    asyncio loop in this worker keeps CPU-bound or blocking node code from
    starving the application loop, which owns operational heartbeats and
    database sessions.
    """
    from spectra_sherpa.app.services.serialization import serialize_result

    executor = build_executor_from_workflow(
        workflow, canonical_read_grant=canonical_read_grant, uncertainty_provider=uncertainty_provider
    )
    entry_nodes = executor.find_prediction_entry_nodes()
    for node_id in entry_nodes:
        node = executor.nodes[node_id]
        if node.metadata is not None and node.metadata.node_type == "deploy.input":
            stream_name = str(node.parameters.get("stream_name", "sample"))
            executor.inject_deployment_input(node_id, dataset, stream_name=stream_name)
        else:
            executor.inject_result(node_id, dataset)

    results = asyncio.run(executor.execute())
    serialized: dict[str, Any] = {}
    for node_id in executor.find_exit_nodes():
        if node_id not in results:
            continue
        try:
            serialized[node_id] = serialize_result(results[node_id], owner_user_id=owner_user_id)
        except Exception:
            serialized[node_id] = {"error": "serialization_failed"}

    return WorkflowDatasetExecution(
        executor=executor,
        results=results,
        serialized_exit_results=serialized,
    )


async def execute_workflow_dataset(
    workflow: Workflow,
    dataset: Any,
    *,
    owner_user_id: int,
    canonical_read_grant: Any = None,
    uncertainty_provider: Any = None,
) -> WorkflowDatasetExecution:
    """Execute one injected dataset without blocking the service event loop.

    Thread work cannot be force-cancelled safely. If the caller is cancelled,
    drain the already-accepted execution before propagating cancellation so a
    folder-watch lease is not released while that execution still has side
    effects in the background.
    """
    worker = asyncio.create_task(
        asyncio.to_thread(
            _execute_workflow_dataset_blocking,
            workflow,
            dataset,
            owner_user_id=owner_user_id,
            canonical_read_grant=canonical_read_grant,
            uncertainty_provider=uncertainty_provider,
        )
    )
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        await asyncio.shield(worker)
        raise


async def run_batch_prediction(
    session: AsyncSession,
    job_id: int,
    run: ExecutionRun,
    workflow: Workflow,
    files: list[Path],
    asset_id: str | None = None,
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
    from spectra_sherpa.app.api.deps import check_demo_capability
    from spectra_sherpa.app.services.deployment_binding import resolve_deployment_binding
    from spectra_sherpa.app.services.deployment_evidence import (
        append_deployment_evidence,
        begin_deployment_evidence,
        finalize_deployment_evidence,
    )
    from spectra_sherpa.app.services.job_manager import job_manager
    from spectra_sherpa.app.services.workflow_access import validate_workflow_execution_access

    total = len(files)
    success_count = 0
    error_count = 0
    all_model_ids: set[str] = set()

    # Background invocation is a second admission boundary.  The HTTP route
    # carries the same guard, but a queued/direct service call must not ingest
    # arbitrary filesystem data after a deployment changes to the trial tier.
    private_upload = bool((run.source_metadata or {}).get("private_prediction_input"))

    try:
        if private_upload:
            from spectra_sherpa.app.contracts.prediction_access import require_private_prediction

            await require_private_prediction(session, run.user_id)
        else:
            check_demo_capability("external_prediction_input")
        if len(run.attempted_artifact_uids or []) != 1 or run.workflow_version_id is None:
            raise ValueError("Operational batch prediction requires one exact artifact and workflow version")
        binding = await resolve_deployment_binding(
            session,
            user_id=run.user_id,
            workflow_id=run.workflow_id,
            artifact_uid=run.attempted_artifact_uids[0],
            expected_version_id=run.workflow_version_id,
        )
        workflow = binding.workflow
        await validate_workflow_execution_access(
            # This graph is constructed by the verified artifact binding, not
            # supplied by the client. Private input custody replaces trial
            # dataset admission only for its one injected deployment input.
            [node for node in workflow.nodes if not (private_upload and node.node_type == "deploy.input")],
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

    await begin_deployment_evidence(run, workflow, files)
    await session.commit()
    for idx, file_path in enumerate(files):
        start_ms = time.monotonic()
        executor = None
        dataset = None

        try:
            if private_upload:
                from spectra_sherpa.app.contracts.prediction_access import require_private_prediction
                from spectra_sherpa.app.services.prediction_upload import verify_prediction_file

                await require_private_prediction(session, run.user_id)
                await asyncio.to_thread(verify_prediction_file, run.user_id, file_path, run.source_metadata)
            binding = await resolve_deployment_binding(
                session,
                user_id=run.user_id,
                workflow_id=run.workflow_id,
                artifact_uid=run.attempted_artifact_uids[0],
                expected_version_id=run.workflow_version_id,
            )
            workflow = binding.workflow
            dataset = await asyncio.to_thread(load_single_file, file_path, asset_id=asset_id)
            execution = await execute_workflow_dataset(workflow, dataset, owner_user_id=run.user_id)
            executor = execution.executor
            results = execution.results
            serialized = execution.serialized_exit_results
            await append_deployment_evidence(run, workflow, idx, execution=execution)

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
            await session.refresh(run)
            await append_deployment_evidence(run, workflow, idx, error=exc, dataset=dataset)

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
    run.status = "completed" if error_count == 0 else ("partial" if success_count else "error")
    run.results_summary = {
        "__batch__": {
            "total_files": total,
            "success_count": success_count,
            "error_count": error_count,
        }
    }
    run.succeeded_artifact_uids = sorted(all_model_ids) if success_count else []
    run.model_ids = list(run.succeeded_artifact_uids)
    await finalize_deployment_evidence(run)
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
