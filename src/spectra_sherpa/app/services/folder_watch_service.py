"""
Folder watch polling service — monitors configured folders for new spectral files.

Follows the NetworkHealthService singleton pattern. Runs as a background asyncio
task that checks all enabled FolderWatch records on a fixed tick interval.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, update

from spectra_sherpa.app.db.session import async_session
from spectra_sherpa.app.models.batch_prediction import BatchPrediction
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.folder_watch import FolderWatch
from spectra_sherpa.app.services.batch_predict import (
    build_executor_from_workflow,
    discover_files,
    load_single_file,
    load_workflow_with_graph,
)

logger = logging.getLogger(__name__)


class FolderWatchService:
    """
    Background service that polls folders for new files.

    For each enabled FolderWatch, discovers new files (not in processed_files),
    executes the workflow on each, and stores results as BatchPrediction rows
    under a new ExecutionRun.
    """

    TICK_INTERVAL = 10  # Main loop tick in seconds

    def __init__(self) -> None:
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the folder watch polling loop."""
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
            query = select(FolderWatch).where(FolderWatch.is_enabled == True)  # noqa: E712
            result = await session.execute(query)
            watches = list(result.scalars().all())

        if not watches:
            return

        now = datetime.now(timezone.utc)
        for watch in watches:
            # Check if enough time has elapsed since last poll
            if watch.last_poll_at:
                elapsed = (now - watch.last_poll_at).total_seconds()
                if elapsed < watch.poll_interval_sec:
                    continue

            await self._process_watch(watch)

    async def _process_watch(self, watch: FolderWatch) -> None:
        """Check for new files in a watched folder and process them."""
        async with async_session() as session:
            try:
                # Claim this watch with CAS on last_poll_at — prevents
                # concurrent workers from processing the same watch.
                now = datetime.now(timezone.utc)
                claim = await session.execute(
                    update(FolderWatch)
                    .where(FolderWatch.id == watch.id)
                    .where(FolderWatch.is_enabled == True)  # noqa: E712
                    .where(
                        FolderWatch.last_poll_at == watch.last_poll_at
                        if watch.last_poll_at is not None
                        else FolderWatch.last_poll_at.is_(None)
                    )
                    .values(last_poll_at=now)
                )
                await session.commit()
                if (claim.rowcount or 0) == 0:
                    return  # Another worker already claimed it

                # Re-load watch in this session
                watch = await session.get(FolderWatch, watch.id)
                if watch is None or not watch.is_enabled:
                    return

                processed = watch.processed_files or {}

                # Discover new files (skip already-processed)
                try:
                    files = discover_files(
                        watch.folder_path,
                        watch.file_pattern,
                        exclude_names=set(processed.keys()),
                        settle_time_seconds=watch.settle_time_seconds,
                    )
                except ValueError as exc:
                    watch.last_error = str(exc)
                    watch.last_poll_at = datetime.now(timezone.utc)
                    await session.commit()
                    return

                if not files:
                    # No new files — just update poll timestamp, clear error
                    watch.last_poll_at = datetime.now(timezone.utc)
                    watch.last_error = None
                    await session.commit()
                    return

                logger.info(
                    "Watch '%s': found %d new file(s) in %s",
                    watch.name,
                    len(files),
                    watch.folder_path,
                )

                # Load workflow with graph
                try:
                    workflow = await load_workflow_with_graph(session, watch.workflow_id, watch.user_id)
                except ValueError as exc:
                    watch.last_error = str(exc)
                    watch.last_poll_at = datetime.now(timezone.utc)
                    await session.commit()
                    return

                # Build params snapshot
                params_snapshot: dict = {}
                for node in workflow.nodes:
                    if node.parameters:
                        params_snapshot[node.node_id] = node.parameters

                # Create ExecutionRun for this batch
                run = ExecutionRun(
                    workflow_id=watch.workflow_id,
                    user_id=watch.user_id,
                    name=f"Watch: {watch.name} ({len(files)} files)",
                    status="running",
                    params_snapshot=params_snapshot,
                    results_summary={},
                    executed_at=datetime.now(timezone.utc),
                    source_type="folder_watch",
                    source_metadata={
                        "watch_id": watch.id,
                        "watch_name": watch.name,
                        "folder_path": watch.folder_path,
                        "file_count": len(files),
                    },
                    labels=[],
                )
                session.add(run)
                await session.flush()

                # Process each file
                from spectra_sherpa.app.api.v1.routes.workflows import serialize_result

                success_count = 0
                error_count = 0

                for file_path in files:
                    import time

                    start_ms = time.monotonic()

                    try:
                        dataset = load_single_file(file_path)
                        executor = build_executor_from_workflow(workflow)
                        entry_nodes = executor.find_entry_nodes()
                        if not entry_nodes:
                            raise ValueError("Workflow has no entry nodes")

                        for node_id in entry_nodes:
                            executor.inject_result(node_id, dataset)

                        results = await executor.execute()

                        exit_nodes = executor.find_exit_nodes()
                        serialized: dict = {}
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
                        logger.warning(
                            "Watch '%s': failed to process %s: %s",
                            watch.name,
                            file_path.name,
                            exc,
                        )

                    # Mark file as processed (keyed by full path for uniqueness)
                    processed[str(file_path)] = datetime.now(timezone.utc).isoformat()

                # Update run aggregates
                run.status = "completed" if error_count == 0 else "partial"
                run.results_summary = {
                    "__batch__": {
                        "total_files": len(files),
                        "success_count": success_count,
                        "error_count": error_count,
                    }
                }

                # Update watch state
                watch.processed_files = processed
                watch.last_poll_at = datetime.now(timezone.utc)
                watch.last_error = None
                await session.commit()

                logger.info(
                    "Watch '%s': processed %d/%d files (run_id=%d)",
                    watch.name,
                    success_count,
                    len(files),
                    run.id,
                )

            except Exception as exc:
                logger.exception("Watch '%s': unhandled error", watch.name)
                try:
                    # Try to record the error on the watch
                    async with async_session() as err_session:
                        w = await err_session.get(FolderWatch, watch.id)
                        if w:
                            w.last_error = str(exc)
                            w.last_poll_at = datetime.now(timezone.utc)
                            await err_session.commit()
                except Exception:
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
