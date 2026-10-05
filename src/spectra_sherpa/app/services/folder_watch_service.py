"""
Folder watch polling service — monitors configured folders for new spectral files.

Follows the NetworkHealthService singleton pattern. Runs as a background asyncio
task that checks all enabled FolderWatch records on a fixed tick interval.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.db.session import async_session
from spectra_sherpa.app.models.batch_prediction import BatchPrediction
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.folder_watch import FolderWatch
from spectra_sherpa.app.services.batch_predict import (
    execute_workflow_dataset,
    load_single_file,
)
from spectra_sherpa.app.services.run_artifact_roles import attempted_artifact_fields
from spectra_sherpa.app.services.run_params import build_effective_params_snapshot
from spectra_sherpa.app.services.watch_discovery import WatchDiscovery

logger = logging.getLogger(__name__)

POLL_LEASE_TTL = timedelta(minutes=5)
POLL_LEASE_HEARTBEAT_SECONDS = 30


async def _write_watch_state_if_current(
    session: AsyncSession,
    *,
    watch_id: int,
    claimed_asset_id: str | None,
    claimed_generation: int,
    claim_token: str,
    values: dict,
) -> bool:
    """Write operational state only while the claimed watch identity is current.

    The dedicated generation advances only when scientific source identity
    actually changes. Pairing it with the exact asset and active lease token
    makes the final write a database-level compare-and-swap; a
    disable/edit/re-enable sequence cannot be overwritten by a poll that
    started under the previous configuration, while a cosmetic rename does not
    discard legitimate processing history.
    """

    statement = (
        update(FolderWatch)
        .where(FolderWatch.id == watch_id)
        .where(
            FolderWatch.asset_id == claimed_asset_id if claimed_asset_id is not None else FolderWatch.asset_id.is_(None)
        )
        .where(FolderWatch.configuration_generation == claimed_generation)
        .where(FolderWatch.active_poll_token == claim_token)
        .values(**values, active_poll_token=None, active_poll_claimed_at=None)
        .execution_options(synchronize_session=False)
    )
    result = await session.execute(statement)
    return (result.rowcount or 0) == 1


async def _claim_watch_if_current(session: AsyncSession, watch: FolderWatch) -> str | None:
    """Acquire the single active-poll lease for the observed configuration."""

    token = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    claim = await session.execute(
        update(FolderWatch)
        .where(FolderWatch.id == watch.id)
        .where(FolderWatch.is_enabled == True)  # noqa: E712
        .where(
            or_(
                and_(FolderWatch.artifact_uid.is_not(None), FolderWatch.workflow_version_id.is_not(None)),
                and_(FolderWatch.canonical_artifact_id.is_not(None), FolderWatch.canonical_plan_digest.is_not(None)),
            )
        )
        .where(FolderWatch.active_poll_token.is_(None))
        .where(FolderWatch.configuration_generation == watch.configuration_generation)
        .where(
            FolderWatch.last_poll_at == watch.last_poll_at
            if watch.last_poll_at is not None
            else FolderWatch.last_poll_at.is_(None)
        )
        .values(active_poll_token=token, active_poll_claimed_at=now, last_poll_at=now)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    return token if (claim.rowcount or 0) == 1 else None


async def _refresh_poll_lease(watch_id: int, claimed_generation: int, claim_token: str) -> bool:
    """Refresh one live lease; return false after invalidation or replacement."""

    async with async_session() as session:
        result = await session.execute(
            update(FolderWatch)
            .where(FolderWatch.id == watch_id)
            .where(FolderWatch.configuration_generation == claimed_generation)
            .where(FolderWatch.active_poll_token == claim_token)
            .values(active_poll_claimed_at=datetime.now(timezone.utc))
            .execution_options(synchronize_session=False)
        )
        await session.commit()
        return (result.rowcount or 0) == 1


async def _heartbeat_poll_lease(watch_id: int, claimed_generation: int, claim_token: str) -> None:
    """Keep a live poll distinct from a crashed worker's recoverable lease."""

    try:
        while True:
            await asyncio.sleep(POLL_LEASE_HEARTBEAT_SECONDS)
            refresh_task = asyncio.create_task(_refresh_poll_lease(watch_id, claimed_generation, claim_token))
            try:
                current = await asyncio.shield(refresh_task)
            except asyncio.CancelledError:
                # Do not interrupt accepted database I/O halfway through its
                # transaction.  Apart from leaving connection state ambiguous,
                # cancellation can invalidate the sole connection used by an
                # in-memory SQLite deployment/test database.  Drain the exact
                # refresh before heartbeat shutdown, matching the execution and
                # lease-release boundaries below.
                await asyncio.shield(refresh_task)
                return
            if not current:
                return
    except asyncio.CancelledError:
        return


async def _release_poll_lease(
    watch_id: int,
    claimed_asset_id: str | None,
    claimed_generation: int,
    claim_token: str,
) -> None:
    """Best-effort exact-token release used by abort and cancellation paths."""

    async with async_session() as session:
        released = await _write_watch_state_if_current(
            session,
            watch_id=watch_id,
            claimed_asset_id=claimed_asset_id,
            claimed_generation=claimed_generation,
            claim_token=claim_token,
            values={},
        )
        await (session.commit() if released else session.rollback())


async def _recover_expired_poll_leases(session: AsyncSession, *, now: datetime | None = None) -> int:
    """Release persisted claims whose worker heartbeat has expired."""

    cutoff = (now or datetime.now(timezone.utc)) - POLL_LEASE_TTL
    result = await session.execute(
        update(FolderWatch)
        .where(FolderWatch.active_poll_token.is_not(None))
        .where((FolderWatch.active_poll_claimed_at.is_(None)) | (FolderWatch.active_poll_claimed_at < cutoff))
        .values(active_poll_token=None, active_poll_claimed_at=None, last_poll_at=None)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    return result.rowcount or 0


class FolderWatchService:
    """
    Background service that polls folders for new files.

    For each enabled FolderWatch, discovers new files (not in processed_files),
    executes the workflow on each, and stores results as BatchPrediction rows
    under a new ExecutionRun.
    """

    TICK_INTERVAL = 1  # One-second scheduling resolution; processing can delay a subsequent poll.

    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task | None = None
        self._discovery: dict[int, WatchDiscovery] = {}

    async def start(self) -> None:
        """Start the folder watch polling loop."""
        from spectra_sherpa.app.core.config import app_config

        if app_config.site_profile == "demo":
            logger.info("Folder watch service disabled for SITE_PROFILE=demo")
            return
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Folder watch service started (tick=%ds)", self.TICK_INTERVAL)

    async def stop(self) -> None:
        """Stop the folder watch polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        for scanner in self._discovery.values():
            await asyncio.to_thread(scanner.close)
        self._discovery.clear()
        logger.info("Folder watch service stopped")

    async def _poll_loop(self) -> None:
        """Main loop: check all watches every TICK_INTERVAL seconds."""
        try:
            while self._running:
                try:
                    await self._check_all_watches()
                except Exception:
                    logger.exception("Error in folder watch poll loop")
                await asyncio.sleep(self.TICK_INTERVAL)
        except asyncio.CancelledError:
            return

    async def _check_all_watches(self) -> None:
        """Load enabled watches and process any that are due for polling."""
        async with async_session() as session:
            recovered = await _recover_expired_poll_leases(session)
            if recovered:
                logger.warning("Recovered %d expired folder-watch poll lease(s)", recovered)
            query = select(FolderWatch).where(
                FolderWatch.is_enabled,
                or_(
                    and_(FolderWatch.artifact_uid.is_not(None), FolderWatch.workflow_version_id.is_not(None)),
                    and_(
                        FolderWatch.canonical_artifact_id.is_not(None), FolderWatch.canonical_plan_digest.is_not(None)
                    ),
                ),
            )
            result = await session.execute(query)
            watches = list(result.scalars().all())

        active_ids = {watch.id for watch in watches}
        for watch_id in set(self._discovery) - active_ids:
            await asyncio.to_thread(self._discovery.pop(watch_id).close)
        if not watches:
            return

        now = datetime.now(timezone.utc)
        for watch in watches:
            if watch.active_poll_token is not None:
                continue
            # Check if enough time has elapsed since last poll
            if watch.last_poll_at:
                last_poll = watch.last_poll_at
                if last_poll.tzinfo is None:
                    last_poll = last_poll.replace(tzinfo=timezone.utc)  # SQLite stores UTC without its offset.
                elapsed = (now - last_poll).total_seconds()
                if elapsed < watch.poll_interval_sec:
                    continue

            await self._process_watch(watch)

    async def _process_watch(self, watch: FolderWatch) -> None:
        """Check for new files in a watched folder and process them."""
        claimed_asset_id = watch.asset_id
        claimed_generation = watch.configuration_generation
        claim_token = ""
        heartbeat_task: asyncio.Task | None = None
        async with async_session() as session:
            try:
                claim_token = await _claim_watch_if_current(session, watch) or ""
                if not claim_token:
                    return  # Another worker already claimed it

                # Re-load watch in this session
                watch = await session.get(FolderWatch, watch.id)
                if watch is None:
                    return

                claimed_asset_id = watch.asset_id
                claimed_generation = watch.configuration_generation
                if not watch.is_enabled:
                    released = await _write_watch_state_if_current(
                        session,
                        watch_id=watch.id,
                        claimed_asset_id=claimed_asset_id,
                        claimed_generation=claimed_generation,
                        claim_token=claim_token,
                        values={},
                    )
                    await (session.commit() if released else session.rollback())
                    return

                heartbeat_task = asyncio.create_task(_heartbeat_poll_lease(watch.id, claimed_generation, claim_token))

                processed = dict(watch.processed_files or {})

                # Bound discovery itself, not just the later inference loop.
                from spectra_sherpa.app.core.config import settings

                scanner = self._discovery.setdefault(watch.id, WatchDiscovery())
                try:
                    discovery = await asyncio.to_thread(
                        scanner.scan,
                        watch.folder_path,
                        watch.file_pattern,
                        generation=claimed_generation,
                        exclude_names=set(processed.keys()),
                        settle_time_seconds=watch.settle_time_seconds,
                        max_files=settings.folder_watch_files_per_poll,
                    )
                    files = discovery.files
                    discovery_warning = (
                        f"Skipped {discovery.entry_error_count} unreadable entries in this scan batch: "
                        f"{discovery.first_entry_error}"
                        if discovery.entry_error_count
                        else None
                    )
                    if discovery_warning:
                        logger.warning("Watch '%s': %s", watch.name, discovery_warning)
                except ValueError as exc:
                    current = await _write_watch_state_if_current(
                        session,
                        watch_id=watch.id,
                        claimed_asset_id=claimed_asset_id,
                        claimed_generation=claimed_generation,
                        claim_token=claim_token,
                        values={
                            "last_error": str(exc),
                            "last_poll_at": datetime.now(timezone.utc),
                        },
                    )
                    await (session.commit() if current else session.rollback())
                    return

                if not files:
                    # No new files — just update poll timestamp, clear error
                    current = await _write_watch_state_if_current(
                        session,
                        watch_id=watch.id,
                        claimed_asset_id=claimed_asset_id,
                        claimed_generation=claimed_generation,
                        claim_token=claim_token,
                        values={
                            "last_poll_at": datetime.now(timezone.utc),
                            "last_error": discovery_warning,
                        },
                    )
                    await (session.commit() if current else session.rollback())
                    return

                # Audit Item 2: a folder-watch poll that has new files is
                # a workflow-execution trigger — enforce the per-session
                # demo quota (one slot per triggered run, consistent with
                # the batch-predict entrypoint).  Background service: no
                # HTTP to raise, so log + skip this run.  Files are NOT
                # marked processed, so they retry once quota frees up.
                from spectra_sherpa.app.contracts.demo_policy import (
                    consume_demo_execution_quota,
                )

                allowed, _remaining = consume_demo_execution_quota(watch.user_id)
                if not allowed:
                    logger.warning(
                        "Watch '%s': demo execution quota exhausted for user %s — skipping run",
                        watch.name,
                        watch.user_id,
                    )
                    current = await _write_watch_state_if_current(
                        session,
                        watch_id=watch.id,
                        claimed_asset_id=claimed_asset_id,
                        claimed_generation=claimed_generation,
                        claim_token=claim_token,
                        values={
                            "last_error": "Demo execution limit reached for this session.",
                            "last_poll_at": datetime.now(timezone.utc),
                        },
                    )
                    await (session.commit() if current else session.rollback())
                    return

                logger.info(
                    "Watch '%s': found %d new file(s) in %s",
                    watch.name,
                    len(files),
                    watch.folder_path,
                )

                # Load workflow with graph
                try:
                    from spectra_sherpa.app.services.deployment_binding import resolve_deployment_binding

                    binding = await resolve_deployment_binding(
                        session,
                        user_id=watch.user_id,
                        workflow_id=watch.workflow_id,
                        artifact_uid=watch.artifact_uid,
                        expected_version_id=watch.workflow_version_id,
                        canonical_artifact_id=watch.canonical_artifact_id,
                        expected_plan_digest=watch.canonical_plan_digest,
                        uncertainty_record=watch.uncertainty_record,
                        uncertainty_population=watch.uncertainty_population,
                    )
                    workflow = binding.workflow
                    from spectra_sherpa.app.services.workflow_access import validate_workflow_execution_access

                    await validate_workflow_execution_access(
                        workflow.nodes,
                        None,
                        watch.user_id,
                        workflow.project_id,
                        session,
                    )
                except Exception as exc:
                    current = await _write_watch_state_if_current(
                        session,
                        watch_id=watch.id,
                        claimed_asset_id=claimed_asset_id,
                        claimed_generation=claimed_generation,
                        claim_token=claim_token,
                        values={
                            "last_error": str(exc),
                            "is_enabled": False,
                            "last_poll_at": datetime.now(timezone.utc),
                        },
                    )
                    await (session.commit() if current else session.rollback())
                    return

                params_snapshot = build_effective_params_snapshot(workflow.nodes)
                artifact_attempts = attempted_artifact_fields([watch.artifact_uid] if watch.artifact_uid else [])

                # Freeze evidence known at batch start. New QC entries do not
                # rewrite this snapshot or interrupt report-only inference.
                from spectra_sherpa.app.services.instrument_qc import qc_snapshot

                qc_evidence = await qc_snapshot(session, watch, binding)

                # Create ExecutionRun for this batch
                run = ExecutionRun(
                    project_id=workflow.project_id,
                    workflow_id=watch.workflow_id,
                    workflow_version_id=watch.workflow_version_id,
                    produced_artifact_uids=[],
                    attempted_artifact_uids=artifact_attempts["attempted_artifact_uids"],
                    succeeded_artifact_uids=[],
                    applied_artifact_uids=artifact_attempts["applied_artifact_uids"],
                    user_id=watch.user_id,
                    name=f"Watch: {watch.name} ({len(files)} files)",
                    status="running",
                    params_snapshot=params_snapshot,
                    results_summary={},
                    executed_at=datetime.now(timezone.utc),
                    source_type="folder_watch",
                    run_kind="batch_inference",
                    source_metadata={
                        "instrument_qc": qc_evidence,
                        "canonical_application_plan": binding.canonical_application_plan,
                        "uncertainty_record_digest": (watch.uncertainty_record or {}).get("record_digest"),
                        "canonical_artifact_id": binding.canonical_artifact_id,
                        "canonical_plan_digest": binding.canonical_plan_digest,
                        "canonical_artifact_digest": (
                            binding.canonical_read_grant.artifact_digest if binding.canonical_read_grant else None
                        ),
                        "watch_id": watch.id,
                        "watch_name": watch.name,
                        "folder_path": watch.folder_path,
                        "file_count": len(files),
                        # A partial scan cannot truthfully report the total backlog.
                        "deferred_file_count": None,
                        "discovery_scan_complete": discovery.scan_complete,
                        "discovery_entries_examined": discovery.entries_examined,
                        "discovery_entry_error_count": discovery.entry_error_count,
                        "discovery_first_entry_error": discovery.first_entry_error,
                        "asset_id": watch.asset_id,
                    },
                    labels=[],
                )
                session.add(run)
                await session.flush()
                from spectra_sherpa.app.services.deployment_evidence import (
                    append_deployment_evidence,
                    begin_deployment_evidence,
                    finalize_deployment_evidence,
                )

                await begin_deployment_evidence(run, workflow, files)
                await session.commit()

                success_count = 0
                error_count = 0

                for file_index, file_path in enumerate(files):
                    import time

                    start_ms = time.monotonic()
                    dataset = None

                    try:
                        binding = await resolve_deployment_binding(
                            session,
                            user_id=run.user_id,
                            workflow_id=run.workflow_id,
                            artifact_uid=watch.artifact_uid,
                            expected_version_id=run.workflow_version_id,
                            canonical_artifact_id=watch.canonical_artifact_id,
                            expected_plan_digest=watch.canonical_plan_digest,
                            uncertainty_record=watch.uncertainty_record,
                            uncertainty_population=watch.uncertainty_population,
                        )
                        workflow = binding.workflow
                        dataset = await asyncio.to_thread(load_single_file, file_path, asset_id=watch.asset_id)
                        execution_options = (
                            {
                                "canonical_read_grant": binding.canonical_read_grant,
                                "uncertainty_provider": binding.uncertainty_provider,
                            }
                            if binding.canonical_read_grant is not None
                            else {}
                        )
                        execution = await execute_workflow_dataset(
                            workflow, dataset, owner_user_id=run.user_id, **execution_options
                        )
                        serialized = execution.serialized_exit_results
                        await append_deployment_evidence(run, workflow, file_index, execution=execution)

                        elapsed_ms = int((time.monotonic() - start_ms) * 1000)
                        prediction = BatchPrediction(
                            run_id=run.id,
                            file_name=file_path.name,
                            file_path=str(file_path),
                            status="completed",
                            results=serialized,
                            model_id=watch.artifact_uid,
                            processing_time_ms=elapsed_ms,
                        )
                        session.add(prediction)
                        success_count += 1

                    except Exception as exc:
                        await append_deployment_evidence(run, workflow, file_index, error=exc, dataset=dataset)
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
                        logger.warning(
                            "Watch '%s': failed to process %s: %s",
                            watch.name,
                            file_path.name,
                            exc,
                        )

                    # Mark file as processed (keyed by full path for uniqueness)
                    processed[str(file_path)] = datetime.now(timezone.utc).isoformat()

                    # Commit after each file to prevent transaction bloat and enable
                    # incremental progress (parity with batch_predict.py behavior).
                    # Wrap in try/except so a single poison-pill file (e.g. name
                    # exceeds DB column limit) cannot kill the entire watch loop.
                    try:
                        await session.commit()
                    except Exception as commit_exc:
                        logger.error(
                            "Watch '%s': DB commit failed for %s: %s — rolling back",
                            watch.name,
                            file_path.name,
                            commit_exc,
                        )
                        await session.rollback()
                        error_count += 1

                # Update run aggregates
                await finalize_deployment_evidence(run)
                run.status = "completed" if error_count == 0 else "partial" if success_count else "error"
                # Canonical applications have a sealed package identity, not a
                # ModelArtifact UID. Never persist [None] as a successful UID.
                run.succeeded_artifact_uids = [watch.artifact_uid] if success_count and watch.artifact_uid else []
                run.model_ids = list(run.succeeded_artifact_uids)
                run.results_summary = {
                    "__batch__": {
                        "total_files": len(files),
                        "success_count": success_count,
                        "error_count": error_count,
                    }
                }

                # Finalize the accurately attributed old-asset run, but attach
                # discovery history to the watch only if its scientific source
                # identity has not changed while this poll was in flight.
                current = await _write_watch_state_if_current(
                    session,
                    watch_id=watch.id,
                    claimed_asset_id=claimed_asset_id,
                    claimed_generation=claimed_generation,
                    claim_token=claim_token,
                    values={
                        "processed_files": processed,
                        "last_poll_at": datetime.now(timezone.utc),
                        "last_error": discovery_warning,
                    },
                )
                await session.commit()

                if not current:
                    logger.info(
                        "Watch '%s': discarded stale poll state after configuration changed (run_id=%d)",
                        watch.name,
                        run.id,
                    )
                    return

                logger.info(
                    "Watch '%s': processed %d/%d files (run_id=%d)",
                    watch.name,
                    success_count,
                    len(files),
                    run.id,
                )

            except Exception as exc:
                logger.exception("Watch '%s': unhandled error", watch.name)
                # Roll back the failed transaction before attempting error recovery
                try:
                    await session.rollback()
                except Exception:
                    pass
                try:
                    # Try to record the error on the watch in a fresh session
                    async with async_session() as err_session:
                        current = await _write_watch_state_if_current(
                            err_session,
                            watch_id=watch.id,
                            claimed_asset_id=claimed_asset_id,
                            claimed_generation=claimed_generation,
                            claim_token=claim_token,
                            values={
                                "last_error": str(exc),
                                "last_poll_at": datetime.now(timezone.utc),
                            },
                        )
                        if current:
                            await err_session.commit()
                        else:
                            await err_session.rollback()
                except Exception:
                    pass
            finally:
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass
                if claim_token:
                    release_task = asyncio.create_task(
                        _release_poll_lease(
                            watch.id,
                            claimed_asset_id,
                            claimed_generation,
                            claim_token,
                        )
                    )
                    try:
                        await asyncio.shield(release_task)
                    except asyncio.CancelledError:
                        # The shielded release continues even as the caller's
                        # cancellation propagates after this finally block.
                        pass


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_service: FolderWatchService | None = None


def get_folder_watch_service() -> FolderWatchService:
    """Get or create the folder watch service singleton."""
    global _service
    if _service is None:
        _service = FolderWatchService()
    return _service


async def start_folder_watch_service() -> None:
    """Start the folder watch service (call on app startup)."""
    service = get_folder_watch_service()
    await service.start()


async def stop_folder_watch_service() -> None:
    """Stop the folder watch service (call on app shutdown)."""
    global _service
    if _service:
        await _service.stop()
        _service = None
