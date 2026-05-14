"""Phase 1b smoke tests — emitter + before_flush listener.

Covers the v0.5 contract that audit rows are inserted in the same
transaction as the business mutation, and that disabling the audit
subsystem (default state) is a zero-overhead no-op.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.db.base import Base
from spectra_sherpa.app.models.audit_event import AuditEvent
from spectra_sherpa.app.services.audit import (
    AuditContext,
    audit_emitter,
    install_audit_flush_listener,
    reset_audit_context,
    set_audit_context,
)
from spectra_sherpa.app.services.audit.boot import _reset_process_boot_id_for_tests


@pytest.fixture
def sync_session_factory():
    """Sync SQLite session bound to a fresh schema for each test.

    The audit listener uses sync ``Session`` events so this is the
    cleanest way to exercise it in isolation.
    """
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    install_audit_flush_listener()
    _reset_process_boot_id_for_tests()
    SessionFactory = sessionmaker(engine, expire_on_commit=False, future=True)
    yield SessionFactory


@pytest.fixture
def audit_enabled(monkeypatch):
    """Flip the audit feature flag on for the duration of the test."""
    monkeypatch.setattr(app_config, "audit_enabled", True)


@pytest.fixture
def audit_context_user_alice(audit_enabled):
    """Bind an AuditContext representing user 'alice' for the test."""
    ctx = AuditContext(
        tenant_id="acme",
        actor_id=42,
        actor_kind="user",
        request_id="reqalice0001",
        extra={"client_host": "127.0.0.1"},
    )
    token = set_audit_context(ctx)
    yield ctx
    reset_audit_context(token)


def test_emit_writes_audit_event_in_same_transaction(sync_session_factory, audit_context_user_alice):
    """When audit is enabled and a context is bound, ``emit()`` stages
    a row that commits with the business transaction.
    """
    with sync_session_factory() as session:
        audit_emitter.emit(
            session=session,
            action="workflow.run.completed",
            target_type="Workflow",
            target_id=123,
            before={"status": "running"},
            after={"status": "completed", "duration_ms": 1500},
            context={"reproducibility_record": {"workflow_id": "abc"}},
        )
        session.commit()

    with sync_session_factory() as session:
        rows = session.execute(select(AuditEvent)).scalars().all()
        assert len(rows) == 1
        event = rows[0]
        assert event.action == "workflow.run.completed"
        assert event.target_type == "Workflow"
        assert event.target_id == "123"
        assert event.actor_id == 42
        assert event.actor_kind == "user"
        assert event.tenant_id == "acme"
        assert event.request_id == "reqalice0001"
        assert event.before_state == {"status": "running"}
        assert event.after_state == {"status": "completed", "duration_ms": 1500}
        assert event.context is not None
        assert event.context["reproducibility_record"] == {"workflow_id": "abc"}
        # Request-scoped extras folded under a stable key
        assert event.context["_request_extra"] == {"client_host": "127.0.0.1"}
        # Process-boot id was minted lazily — canonical 36-char UUID
        # (str(uuid.uuid4()) with hyphens), matching the TEXT(36)
        # schema column shape.
        assert len(event.process_boot_id) == 36
        assert event.process_boot_id.count("-") == 4
        assert event.app_monotonic_ns > 0


def test_emit_is_noop_when_audit_disabled(sync_session_factory):
    """With ``audit_enabled=False`` (the default), ``emit()`` writes
    nothing — zero overhead for OSS Local.
    """
    assert not app_config.audit_enabled  # double-check the default
    ctx = AuditContext(
        tenant_id="acme",
        actor_id=42,
        actor_kind="user",
        request_id="reqdisabled1",
    )
    token = set_audit_context(ctx)
    try:
        with sync_session_factory() as session:
            audit_emitter.emit(
                session=session,
                action="workflow.run.completed",
                target_type="Workflow",
                target_id=123,
            )
            session.commit()
    finally:
        reset_audit_context(token)

    with sync_session_factory() as session:
        rows = session.execute(select(AuditEvent)).scalars().all()
        assert rows == []


def test_rollback_drops_pending_events(sync_session_factory, audit_context_user_alice):
    """A rolled-back transaction must not leak audit rows on a later
    commit that re-uses the same session."""
    with sync_session_factory() as session:
        audit_emitter.emit(
            session=session,
            action="workflow.run.failed",
            target_type="Workflow",
            target_id=99,
        )
        # No commit — explicit rollback.
        session.rollback()

        # Re-use the same session: emit a new event and commit.
        audit_emitter.emit(
            session=session,
            action="workflow.run.completed",
            target_type="Workflow",
            target_id=100,
        )
        session.commit()

    with sync_session_factory() as session:
        rows = session.execute(select(AuditEvent)).scalars().all()
        # Only the post-rollback commit should be persisted.
        assert len(rows) == 1
        assert rows[0].action == "workflow.run.completed"
        assert rows[0].target_id == "100"


def test_emit_without_context_synthesises_system_actor(sync_session_factory, audit_enabled):
    """An emit call with no bound context still produces a usable event
    (synthesised actor_kind='system') so background tasks do not crash
    the transaction."""
    with sync_session_factory() as session:
        audit_emitter.emit(
            session=session,
            action="folder_watch.tick",
            target_type="FolderWatch",
            target_id=7,
            tenant_id="acme",
        )
        session.commit()

    with sync_session_factory() as session:
        rows = session.execute(select(AuditEvent)).scalars().all()
        assert len(rows) == 1
        assert rows[0].actor_kind == "system"
        assert rows[0].actor_id is None
        assert rows[0].tenant_id == "acme"


def test_multiple_emits_one_transaction(sync_session_factory, audit_context_user_alice):
    """Many emit() calls in one transaction → that many event rows,
    all committed together."""
    with sync_session_factory() as session:
        for i in range(5):
            audit_emitter.emit(
                session=session,
                action="workflow.param.changed",
                target_type="WorkflowVersion",
                target_id=i,
                after={"param_index": i},
            )
        session.commit()

    with sync_session_factory() as session:
        rows = session.execute(select(AuditEvent).order_by(AuditEvent.id)).scalars().all()
        assert len(rows) == 5
        assert [int(r.target_id) for r in rows] == [0, 1, 2, 3, 4]
