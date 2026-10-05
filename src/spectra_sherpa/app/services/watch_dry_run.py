"""Ordinary saved-model watch rehearsal, retained as a run without marking files processed."""

from __future__ import annotations

import hashlib
import json
from asyncio import CancelledError, to_thread
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update

from spectra_sherpa.app.core.mode_policy import is_local
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.folder_watch import FolderWatch
from spectra_sherpa.app.services.batch_predict import discover_files, execute_workflow_dataset, load_single_file
from spectra_sherpa.app.services.deployment_binding import resolve_deployment_binding
from spectra_sherpa.app.services.deployment_evidence import (
    append_deployment_evidence,
    begin_deployment_evidence,
    finalize_deployment_evidence,
)

FIELDS = (
    "id",
    "user_id",
    "workflow_id",
    "artifact_uid",
    "workflow_version_id",
    "configuration_generation",
    "folder_path",
    "file_pattern",
    "asset_id",
    "settle_time_seconds",
    "poll_interval_sec",
)


def configuration(watch, overrides=None):
    overrides = overrides or {}
    values = {key: overrides.get(key, getattr(watch, key)) for key in FIELDS}
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def mutation_snapshot(watch):
    if not is_local():
        return None
    return {key: getattr(watch, key) for key in (*FIELDS, "canonical_artifact_id", "is_enabled")}


async def lock_unchanged_watch(session, snapshot):
    """Compare and acquire a write lock through commit, including on SQLite.

    Both configuration edits and activation participate, preventing an edit that
    started while disabled from committing after concurrent activation.
    """
    if snapshot is None:
        return
    with session.no_autoflush:
        result = await session.execute(
            update(FolderWatch)
            .where(*(getattr(FolderWatch, key) == value for key, value in snapshot.items()))
            .values(is_enabled=snapshot["is_enabled"])
            .execution_options(synchronize_session=False)
        )
    if result.rowcount != 1:
        raise ValueError("Watch changed while saving. Reload it and retry.")


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            if size > 256 * 1024 * 1024:
                raise ValueError("Dry-run input exceeds the 256 MiB file limit.")
            digest.update(chunk)
    return digest.hexdigest()


def _representative(watch, name: str) -> Path:
    if not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError("Choose a file name inside this watch's folder.")
    files = discover_files(Path(watch.folder_path), watch.file_pattern, settle_time_seconds=watch.settle_time_seconds)
    choices = [path for path in files if path.name == name]
    if len(choices) != 1 or choices[0].resolve().parent != Path(watch.folder_path).resolve():
        raise ValueError("Choose a settled file inside this folder that matches the watch pattern.")
    return choices[0]


async def _receipt_run(session, watch):
    return await session.scalar(
        select(ExecutionRun)
        .where(
            ExecutionRun.user_id == watch.user_id,
            ExecutionRun.workflow_id == watch.workflow_id,
            ExecutionRun.source_type == "watch_dry_run",
            ExecutionRun.source_metadata["watch_id"].as_integer() == watch.id,
        )
        .order_by(ExecutionRun.id.desc())
        .limit(1)
    )


async def latest_receipt(session, watch):
    row = await _receipt_run(session, watch)
    receipt = (row.source_metadata or {}).get("dry_run_receipt") if row else None
    if receipt:
        return {**receipt, "matches_current_settings": receipt.get("configuration") == configuration(watch)}
    return None


async def run_dry_run(session, watch, file_name: str):
    if not is_local() or watch.canonical_artifact_id is not None:
        raise ValueError("This dry run is for a local, ordinary saved-model watch.")
    path = await to_thread(_representative, watch, file_name)
    signature = configuration(watch)
    file_sha = await to_thread(file_digest, path)
    binding = await resolve_deployment_binding(
        session,
        user_id=watch.user_id,
        workflow_id=watch.workflow_id,
        artifact_uid=watch.artifact_uid,
        expected_version_id=watch.workflow_version_id,
        uncertainty_record=watch.uncertainty_record,
        uncertainty_population=watch.uncertainty_population,
    )
    model_sha = binding.artifact.integrity_hash
    run = ExecutionRun(
        user_id=watch.user_id,
        project_id=binding.workflow.project_id,
        workflow_id=watch.workflow_id,
        workflow_version_id=watch.workflow_version_id,
        name=f"Dry run: {watch.name}"[:255],
        status="running",
        run_kind="batch_inference",
        source_type="watch_dry_run",
        executed_at=datetime.now(timezone.utc),
        params_snapshot={n.node_id: n.parameters for n in binding.workflow.nodes},
        results_summary={},
        attempted_artifact_uids=[watch.artifact_uid],
        source_metadata={"watch_id": watch.id, "asset_id": watch.asset_id},
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    receipt = {
        "schema_version": "spectrasherpa-watch-dry-run/1",
        "run_id": run.id,
        "watch_id": watch.id,
        "watch_name": watch.name,
        "folder": watch.folder_path,
        "pattern": watch.file_pattern,
        "artifact_uid": watch.artifact_uid,
        "workflow_version_id": watch.workflow_version_id,
        "configuration": signature,
        "file_name": file_name,
        "file_sha256": file_sha,
        "model_sha256": model_sha,
        "checked_at": run.executed_at.isoformat(),
        "environment": run.environment_snapshot,
        "status": "failed",
    }
    dataset = None
    evidence_started = False
    execution_retained = False
    try:
        await begin_deployment_evidence(run, binding.workflow, [path])
        evidence_started = True
        dataset = await to_thread(load_single_file, path, asset_id=watch.asset_id)
        execution = await execute_workflow_dataset(
            binding.workflow, dataset, owner_user_id=watch.user_id, uncertainty_provider=binding.uncertainty_provider
        )
        await append_deployment_evidence(run, binding.workflow, 0, execution=execution)
        await finalize_deployment_evidence(run)
        execution_retained = True
        await session.refresh(watch)
        if configuration(watch) != signature or await to_thread(file_digest, path) != file_sha:
            raise ValueError("Watch settings or input changed during the dry run. Repeat with stable input.")
        checked = await resolve_deployment_binding(
            session,
            user_id=watch.user_id,
            workflow_id=watch.workflow_id,
            artifact_uid=watch.artifact_uid,
            expected_version_id=watch.workflow_version_id,
            uncertainty_record=watch.uncertainty_record,
            uncertainty_population=watch.uncertainty_population,
        )
        if checked.artifact.integrity_hash != model_sha:
            raise ValueError("Model changed during the dry run. Repeat the check.")
        receipt["input_shape"] = list(dataset.shape)
        encoded = json.dumps(execution.serialized_exit_results, default=str)
        receipt["result_preview"] = (
            execution.serialized_exit_results
            if len(encoded) <= 64_000
            else {"notice": "Result exceeds the 64,000-character preview; inspect the retained run outputs."}
        )
        receipt["status"] = run.status = "completed"
        run.succeeded_artifact_uids = [watch.artifact_uid] if watch.artifact_uid else []
    except (Exception, CancelledError) as exc:
        if evidence_started and not execution_retained:
            await append_deployment_evidence(run, binding.workflow, 0, error=exc, dataset=dataset)
            await finalize_deployment_evidence(run)
        run.status = "failed"
        run.error = "Dry run interrupted. Repeat the check." if isinstance(exc, CancelledError) else str(exc)
        receipt["error"] = run.error
        if isinstance(exc, CancelledError):
            run.source_metadata = {**(run.source_metadata or {}), "dry_run_receipt": receipt}
            await session.commit()
            raise
    run.source_metadata = {**(run.source_metadata or {}), "dry_run_receipt": receipt}
    await session.commit()
    return receipt
