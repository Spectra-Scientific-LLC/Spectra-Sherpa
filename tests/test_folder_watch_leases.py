"""Concurrency and crash-recovery proofs for folder-watch poll leases."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from spectra_sherpa.app.models.folder_watch import FolderWatch
from spectra_sherpa.app.models.model_artifact import ModelArtifact
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_version import WorkflowVersion
from spectra_sherpa.app.services import folder_watch_service as service_module
from spectra_sherpa.app.services.folder_watch_service import (
    POLL_LEASE_TTL,
    FolderWatchService,
    _claim_watch_if_current,
    _heartbeat_poll_lease,
    _recover_expired_poll_leases,
    _release_poll_lease,
    _write_watch_state_if_current,
)


@pytest.mark.asyncio
async def test_watch_backlog_drains_in_bounded_runs(test_session, test_user, monkeypatch, tmp_path):
    from dataclasses import replace

    from sqlalchemy import select

    from spectra_sherpa.app.contracts import demo_policy
    from spectra_sherpa.app.models.execution_run import ExecutionRun
    from spectra_sherpa.app.services import deployment_binding, run_output_retention, workflow_access

    monkeypatch.setattr(run_output_retention, "settings", replace(run_output_retention.settings, data_dir=tmp_path))

    watch = await _watch(test_session, test_user.id)
    factory = sessionmaker(test_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(service_module, "async_session", factory)
    sources = [tmp_path / f"sample-{i:03}.spa" for i in range(35)]
    for source in sources:
        source.write_bytes(b"synthetic")
    watch.folder_path = str(tmp_path)
    watch.file_pattern = "*.spa"
    watch.settle_time_seconds = 0
    await test_session.commit()
    workflow = Workflow(id=watch.workflow_id, user_id=test_user.id, name="bounded", nodes=[], edges=[])
    monkeypatch.setattr(
        deployment_binding,
        "resolve_deployment_binding",
        AsyncMock(return_value=deployment_binding.DeploymentBinding(workflow=workflow, artifact=None)),
    )
    monkeypatch.setattr(workflow_access, "validate_workflow_execution_access", AsyncMock())
    monkeypatch.setattr(demo_policy, "consume_demo_execution_quota", lambda user_id: (True, 1))

    def reject_file(*args, **kwargs):
        raise ValueError("Deliberate per-file admission failure")

    monkeypatch.setattr(service_module, "load_single_file", reject_file)
    service = FolderWatchService()
    for expected in (16, 32, 35):
        await service._process_watch(watch)
        await test_session.refresh(watch)
        assert len(watch.processed_files) == expected
    runs = (await test_session.scalars(select(ExecutionRun).order_by(ExecutionRun.id))).all()
    assert [run.source_metadata["file_count"] for run in runs] == [16, 16, 3]
    assert [run.source_metadata["deferred_file_count"] for run in runs] == [None, None, None]
    assert [run.source_metadata["discovery_scan_complete"] for run in runs] == [False, False, True]
    await service.stop()


async def _watch(session: AsyncSession, user_id: int, *, enabled: bool = True) -> FolderWatch:
    workflow = Workflow(user_id=user_id, name="lease-workflow")
    session.add(workflow)
    await session.flush()
    version = WorkflowVersion(workflow_id=workflow.id, version_number=1, created_by=user_id, snapshot={})
    session.add(version)
    await session.flush()
    artifact = ModelArtifact(
        artifact_uid=f"lease-artifact-{workflow.id}",
        user_id=user_id,
        workflow_id=workflow.id,
        workflow_version_id=version.id,
        node_id="model",
        model_type="pls",
        n_features=2,
        name="Lease fixture",
        artifact_dir="fixture",
        integrity_hash="a" * 64,
        is_active=True,
        is_deploy_ready=True,
    )
    session.add(artifact)
    await session.flush()
    watch = FolderWatch(
        user_id=user_id,
        workflow_id=workflow.id,
        artifact_uid=artifact.artifact_uid,
        workflow_version_id=version.id,
        name="lease-watch",
        folder_path="/tmp/lease-watch",
        file_pattern="*.0",
        poll_interval_sec=60,
        asset_id="a",
        is_enabled=enabled,
        processed_files={},
    )
    session.add(watch)
    await session.commit()
    await session.refresh(watch)
    return watch


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["artifact_uid", "workflow_version_id"])
async def test_unbound_watch_cannot_be_polled_or_claimed(test_session, test_user, monkeypatch, missing):
    watch = await _watch(test_session, test_user.id)
    setattr(watch, missing, None)
    await test_session.commit()
    factory = sessionmaker(test_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(service_module, "async_session", factory)
    service = FolderWatchService()
    process = AsyncMock()
    monkeypatch.setattr(service, "_process_watch", process)
    await service._check_all_watches()
    process.assert_not_awaited()
    assert await _claim_watch_if_current(test_session, watch) is None


@pytest.mark.asyncio
async def test_repeated_poll_accepts_sqlite_utc_timestamps(test_session, test_user, monkeypatch):
    watch = await _watch(test_session, test_user.id)
    watch.last_poll_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    await test_session.commit()
    factory = sessionmaker(test_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(service_module, "async_session", factory)
    service = FolderWatchService()
    process = AsyncMock()
    monkeypatch.setattr(service, "_process_watch", process)
    await service._check_all_watches()
    process.assert_awaited_once()
    watch.last_poll_at = datetime.now(timezone.utc)
    await test_session.commit()
    process.reset_mock()
    await service._check_all_watches()
    process.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_accepted_poll_can_record_history_and_release_lease(
    test_session: AsyncSession,
    test_user,
) -> None:
    watch = await _watch(test_session, test_user.id)
    token = await _claim_watch_if_current(test_session, watch)
    assert token is not None
    await test_session.refresh(watch)
    generation = watch.configuration_generation
    watch.is_enabled = False
    await test_session.commit()

    written = await _write_watch_state_if_current(
        test_session,
        watch_id=watch.id,
        claimed_asset_id="a",
        claimed_generation=generation,
        claim_token=token,
        values={"processed_files": {"/tmp/lease-watch/sample.0": "accepted-once"}},
    )
    await test_session.commit()
    assert written is True
    await test_session.refresh(watch)
    assert watch.is_enabled is False
    assert watch.processed_files == {"/tmp/lease-watch/sample.0": "accepted-once"}
    assert watch.active_poll_token is None
    assert watch.active_poll_claimed_at is None


@pytest.mark.asyncio
async def test_expired_orphan_lease_is_recovered_and_immediately_claimable(
    test_session: AsyncSession,
    test_user,
) -> None:
    watch = await _watch(test_session, test_user.id)
    live_token = await _claim_watch_if_current(test_session, watch)
    assert live_token is not None
    assert await _recover_expired_poll_leases(test_session) == 0
    await test_session.refresh(watch)
    assert watch.active_poll_token == live_token
    assert await _claim_watch_if_current(test_session, watch) is None

    watch.active_poll_token = "orphaned-worker"
    watch.active_poll_claimed_at = datetime.now(timezone.utc) - POLL_LEASE_TTL - timedelta(seconds=1)
    watch.last_poll_at = datetime.now(timezone.utc)
    await test_session.commit()

    recovered = await _recover_expired_poll_leases(test_session)
    assert recovered == 1
    await test_session.refresh(watch)
    assert watch.active_poll_token is None
    assert watch.active_poll_claimed_at is None
    assert watch.last_poll_at is None
    assert await _claim_watch_if_current(test_session, watch) is not None


@pytest.mark.asyncio
async def test_cancelling_process_watch_releases_exact_live_lease(
    test_session: AsyncSession,
    test_user,
    monkeypatch,
    tmp_path,
) -> None:
    watch = await _watch(test_session, test_user.id)
    worker_sessions = sessionmaker(test_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(service_module, "async_session", worker_sessions)
    source = tmp_path / "sample.0"
    source.write_bytes(b"fixture")
    watch.folder_path = str(tmp_path)
    watch.settle_time_seconds = 0
    await test_session.commit()

    from spectra_sherpa.app.contracts import demo_policy

    monkeypatch.setattr(demo_policy, "consume_demo_execution_quota", lambda user_id: (True, 1))
    entered = asyncio.Event()

    async def _block_after_claim(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    from spectra_sherpa.app.services import deployment_binding

    monkeypatch.setattr(deployment_binding, "resolve_deployment_binding", _block_after_claim)
    task = asyncio.create_task(FolderWatchService()._process_watch(watch))
    await asyncio.wait_for(entered.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # The shielded exact-token cleanup may finish one event-loop turn after
    # cancellation is delivered to the caller.
    await asyncio.sleep(0)
    await test_session.refresh(watch)
    assert watch.active_poll_token is None
    assert watch.active_poll_claimed_at is None


@pytest.mark.asyncio
async def test_disable_between_claim_and_reload_releases_lease(
    test_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    watch = await _watch(test_session, test_user.id)
    worker_sessions = sessionmaker(test_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(service_module, "async_session", worker_sessions)
    original_claim = service_module._claim_watch_if_current

    async def _claim_then_disable(session, observed_watch):
        token = await original_claim(session, observed_watch)
        async with worker_sessions() as editing_session:
            current = await editing_session.get(FolderWatch, observed_watch.id)
            current.is_enabled = False
            await editing_session.commit()
        return token

    monkeypatch.setattr(service_module, "_claim_watch_if_current", _claim_then_disable)
    await FolderWatchService()._process_watch(watch)
    await test_session.refresh(watch)
    assert watch.is_enabled is False
    assert watch.active_poll_token is None
    assert watch.active_poll_claimed_at is None


@pytest.mark.asyncio
async def test_blocking_work_outlives_ttl_without_live_lease_recovery(
    test_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    """A worker-thread computation cannot starve the service-loop heartbeat."""
    from spectra_sherpa.app.services import batch_predict as batch_module

    watch = await _watch(test_session, test_user.id)
    worker_sessions = sessionmaker(test_session.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(service_module, "async_session", worker_sessions)
    monkeypatch.setattr(service_module, "POLL_LEASE_TTL", timedelta(milliseconds=60))
    monkeypatch.setattr(service_module, "POLL_LEASE_HEARTBEAT_SECONDS", 0.01)

    token = await _claim_watch_if_current(test_session, watch)
    assert token is not None
    generation = watch.configuration_generation
    started = threading.Event()
    finish = threading.Event()
    outcome = batch_module.WorkflowDatasetExecution(executor=None, results={}, serialized_exit_results={})

    def _blocking_execution(*args, **kwargs):
        started.set()
        assert finish.wait(timeout=2)
        return outcome

    monkeypatch.setattr(batch_module, "_execute_workflow_dataset_blocking", _blocking_execution)
    heartbeat = asyncio.create_task(_heartbeat_poll_lease(watch.id, generation, token))
    execution = asyncio.create_task(batch_module.execute_workflow_dataset(None, None, owner_user_id=test_user.id))
    assert await asyncio.to_thread(started.wait, 1)

    # Several simulated lease lifetimes pass while a second worker checks.
    await asyncio.sleep(0.2)
    async with worker_sessions() as recovery_session:
        assert await _recover_expired_poll_leases(recovery_session) == 0
    await test_session.refresh(watch)
    assert watch.active_poll_token == token
    assert await _claim_watch_if_current(test_session, watch) is None

    finish.set()
    assert await execution == outcome
    heartbeat.cancel()
    await heartbeat
    await _release_poll_lease(watch.id, "a", generation, token)


@pytest.mark.asyncio
async def test_heartbeat_cancellation_drains_an_accepted_refresh(
    monkeypatch,
) -> None:
    """Shutdown cannot cancel a lease-refresh transaction mid-flight."""
    entered = asyncio.Event()
    finish = asyncio.Event()

    async def _controlled_refresh(*args, **kwargs):
        entered.set()
        await finish.wait()
        return True

    monkeypatch.setattr(service_module, "POLL_LEASE_HEARTBEAT_SECONDS", 0)
    monkeypatch.setattr(service_module, "_refresh_poll_lease", _controlled_refresh)
    heartbeat = asyncio.create_task(_heartbeat_poll_lease(1, 0, "lease-token"))
    await asyncio.wait_for(entered.wait(), timeout=1)

    heartbeat.cancel()
    await asyncio.sleep(0)
    assert not heartbeat.done()

    finish.set()
    await asyncio.wait_for(heartbeat, timeout=1)


@pytest.mark.asyncio
async def test_discovery_cursor_survives_other_worker_lease_and_closes_when_disabled(
    test_session, test_user, monkeypatch, tmp_path
):
    from spectra_sherpa.app.services.watch_discovery import WatchDiscovery

    watch = await _watch(test_session, test_user.id)
    monkeypatch.setattr(
        service_module,
        "async_session",
        sessionmaker(test_session.bind, class_=AsyncSession, expire_on_commit=False),
    )
    (tmp_path / "sample.csv").touch()
    scanner = WatchDiscovery()
    scanner.scan(str(tmp_path), "*.csv", generation=1, exclude_names=set(), settle_time_seconds=0, max_files=1)
    service = FolderWatchService()
    service._discovery[watch.id] = scanner
    watch.active_poll_token = "another-worker"
    watch.active_poll_claimed_at = datetime.now(timezone.utc)
    await test_session.commit()
    try:
        await service._check_all_watches()
        assert service._discovery[watch.id] is scanner
        assert scanner._iterator is not None
        watch.is_enabled = False
        await test_session.commit()
        await service._check_all_watches()
        assert service._discovery == {}
        assert scanner._iterator is None
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_empty_discovery_batch_exposes_unreadable_entry_warning(test_session, test_user, monkeypatch):
    from spectra_sherpa.app.services.watch_discovery import DiscoveryBatch, WatchDiscovery

    watch = await _watch(test_session, test_user.id)
    monkeypatch.setattr(
        service_module,
        "async_session",
        sessionmaker(test_session.bind, class_=AsyncSession, expire_on_commit=False),
    )
    monkeypatch.setattr(WatchDiscovery, "scan", lambda *args, **kwargs: DiscoveryBatch([], False, 1, 1, "denied.csv"))
    service = FolderWatchService()
    try:
        await service._process_watch(watch)
        await test_session.refresh(watch)
        assert "Skipped 1 unreadable entries" in watch.last_error
        assert "denied.csv" in watch.last_error
        assert watch.active_poll_token is None
        assert watch.processed_files == {}
    finally:
        await service.stop()
