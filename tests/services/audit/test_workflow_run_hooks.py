"""Phase 1c smoke tests — workflow.run.* and model_artifact.* hook coverage.

Calls the real persistence helpers (``_auto_persist_run``,
``persist_model_artifact_records``) and asserts that the corresponding
audit events appear in the same transaction. The tests don't spin up
the full FastAPI app — they wire the helpers against an in-memory
async SQLite session, which is enough to exercise the hook surface.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.db.base import Base
from spectra_sherpa.app.models.audit_event import AuditEvent
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.audit import (
    AuditContext,
    install_audit_flush_listener,
    reset_audit_context,
    set_audit_context,
)
from spectra_sherpa.app.services.audit.boot import _reset_process_boot_id_for_tests


@pytest_asyncio.fixture
async def async_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    install_audit_flush_listener()
    _reset_process_boot_id_for_tests()
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        # Seed a test user (FK target for actor_id)
        session.add(User(username="alice"))
        await session.commit()
        yield session
    await engine.dispose()


@pytest.fixture
def audit_on(monkeypatch):
    monkeypatch.setattr(app_config, "audit_enabled", True)


@pytest.fixture
def alice_context(audit_on):
    ctx = AuditContext(
        tenant_id="acme",
        actor_id=1,
        actor_kind="user",
        request_id=str(uuid.uuid4()),
        extra={"client_host": "127.0.0.1"},
    )
    token = set_audit_context(ctx)
    yield ctx
    reset_audit_context(token)


async def test_workflow_run_completed_emits_audit_event(async_session, alice_context):
    """A successful auto-persisted run produces a workflow.run.completed
    event with a reproducibility record attached."""
    from spectra_sherpa.app.api.v1.routes.workflows._helpers import _auto_persist_run

    persisted = await _auto_persist_run(
        async_session,
        workflow_id=42,
        user_id=1,
        wf_version_id=7,
        serialized_results={"node-1": {"X": [1, 2, 3]}},
        diagnostics_serialized={},
        node_statuses={"node-1": "completed"},
        final_status="completed",
        error_msg=None,
        integrity_hash="abc123",
        model_ids=["uid-pca-001"],
        params_snapshot={"baseline_correction": "snv"},
    )
    assert persisted is not None

    rows = (await async_session.execute(select(AuditEvent))).scalars().all()
    assert len(rows) == 1
    event = rows[0]
    assert event.action == "workflow.run.completed"
    assert event.target_type == "ExecutionRun"
    assert int(event.target_id) > 0
    assert event.actor_id == 1
    assert event.actor_kind == "user"
    assert event.tenant_id == "acme"
    assert event.after_state["status"] == "completed"
    assert event.after_state["workflow_id"] == 42
    assert event.after_state["model_artifact_count"] == 1
    # Reproducibility record attached
    repro = event.context["reproducibility_record"]
    assert repro["workflow_id"] == 42
    assert repro["workflow_version_id"] == 7
    assert repro["workflow_integrity_hash"] == "abc123"
    assert repro["parameter_set"] == {"baseline_correction": "snv"}
    assert repro["model_artifact_uids"] == ["uid-pca-001"]


async def test_workflow_run_failed_emits_audit_event(async_session, alice_context):
    """An auto-persisted partial/error run produces workflow.run.failed."""
    from spectra_sherpa.app.api.v1.routes.workflows._helpers import _auto_persist_run

    await _auto_persist_run(
        async_session,
        workflow_id=42,
        user_id=1,
        wf_version_id=None,
        serialized_results={},
        diagnostics_serialized={},
        node_statuses={"node-1": "failed"},
        final_status="error",
        error_msg="Out of memory",
        integrity_hash=None,
        model_ids=None,
        params_snapshot=None,
    )

    rows = (await async_session.execute(select(AuditEvent))).scalars().all()
    assert len(rows) == 1
    event = rows[0]
    assert event.action == "workflow.run.failed"
    assert event.after_state["status"] == "error"
    assert event.after_state["error"] == "Out of memory"


async def test_workflow_run_partial_maps_to_partial_action(async_session, alice_context):
    """Partial status maps to workflow.run.partial (not failed, not completed)."""
    from spectra_sherpa.app.api.v1.routes.workflows._helpers import _auto_persist_run

    await _auto_persist_run(
        async_session,
        workflow_id=42,
        user_id=1,
        wf_version_id=None,
        serialized_results={"node-1": {"X": [1]}},
        diagnostics_serialized={},
        node_statuses={"node-1": "completed", "node-2": "failed"},
        final_status="partial",
        error_msg="Node 2 failed",
        integrity_hash=None,
        model_ids=None,
        params_snapshot=None,
    )

    rows = (await async_session.execute(select(AuditEvent))).scalars().all()
    assert len(rows) == 1
    assert rows[0].action == "workflow.run.partial"


async def test_workflow_run_audit_is_noop_when_disabled(async_session):
    """audit_enabled=False produces no audit row for the run."""
    from spectra_sherpa.app.api.v1.routes.workflows._helpers import _auto_persist_run

    assert not app_config.audit_enabled
    await _auto_persist_run(
        async_session,
        workflow_id=42,
        user_id=1,
        wf_version_id=None,
        serialized_results={},
        diagnostics_serialized={},
        node_statuses={},
        final_status="completed",
        error_msg=None,
        integrity_hash=None,
        model_ids=None,
        params_snapshot=None,
    )
    rows = (await async_session.execute(select(AuditEvent))).scalars().all()
    assert rows == []


async def test_model_artifact_created_emits_audit_event(async_session, alice_context):
    """persist_model_artifact_records emits model_artifact.created per row."""
    from spectra_sherpa.app.services.model_store import persist_model_artifact_records

    rows_created = await persist_model_artifact_records(
        async_session,
        saved_artifacts=[
            {
                "artifact_uid": "uid-pca-001",
                "model_type": "pca",
                "artifact_dir": "/tmp/uid-pca-001",
                "integrity_hash": "deadbeef",
                "n_features": 50,
                "n_components": 5,
                "node_id": "pca-node-1",
            },
            {
                "artifact_uid": "uid-pls-002",
                "model_type": "pls",
                "artifact_dir": "/tmp/uid-pls-002",
                "integrity_hash": "cafef00d",
                "n_features": 50,
                "node_id": "pls-node-1",
            },
        ],
        user_id=1,
        workflow_id=42,
        workflow_version_id=7,
        project_id=3,
    )
    await async_session.commit()
    assert len(rows_created) == 2

    audit_rows = (await async_session.execute(select(AuditEvent).order_by(AuditEvent.id))).scalars().all()
    assert len(audit_rows) == 2

    by_uid = {r.target_id: r for r in audit_rows}
    pca = by_uid["uid-pca-001"]
    assert pca.action == "model_artifact.created"
    assert pca.target_type == "ModelArtifact"
    assert pca.after_state["model_type"] == "pca"
    assert pca.after_state["workflow_id"] == 42
    assert pca.after_state["project_id"] == 3
    assert pca.after_state["n_features"] == 50
    assert pca.after_state["n_components"] == 5
    pls = by_uid["uid-pls-002"]
    assert pls.after_state["model_type"] == "pls"
    assert pls.after_state["n_components"] is None


async def test_model_artifact_audit_skipped_for_duplicates(async_session, alice_context):
    """Re-running persist with an artifact_uid that already exists does
    not emit a second audit event (the artifact row itself is skipped,
    so the audit must be skipped too)."""
    from spectra_sherpa.app.services.model_store import persist_model_artifact_records

    art = {
        "artifact_uid": "uid-pca-dup",
        "model_type": "pca",
        "artifact_dir": "/tmp/uid-pca-dup",
        "integrity_hash": "deadbeef",
        "n_features": 10,
        "n_components": 2,
        "node_id": "pca-node-1",
    }

    await persist_model_artifact_records(async_session, [art], user_id=1, workflow_id=42)
    await async_session.commit()

    # Second call with the same uid is a no-op (existing_uids guard)
    await persist_model_artifact_records(async_session, [art], user_id=1, workflow_id=42)
    await async_session.commit()

    rows = (await async_session.execute(select(AuditEvent))).scalars().all()
    assert len(rows) == 1
    assert rows[0].target_id == "uid-pca-dup"


# Ensure pytest treats async tests as asyncio
os.environ.setdefault("PYTEST_ASYNCIO_MODE", "auto")
