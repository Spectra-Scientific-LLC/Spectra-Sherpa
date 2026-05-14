"""Phase 1d — reproducibility-record builder tests.

Asserts that every workflow.run.* event carries a record matching the
Phase 1d minimum-required field set, and that the cached environment
snapshot is shaped per the v0.5 spec.
"""

from __future__ import annotations

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
    REQUIRED_REPRODUCIBILITY_FIELDS,
    AuditContext,
    assert_reproducibility_record_complete,
    build_reproducibility_record,
    get_environment_snapshot,
    install_audit_flush_listener,
    reset_audit_context,
    set_audit_context,
)
from spectra_sherpa.app.services.audit.boot import _reset_process_boot_id_for_tests
from spectra_sherpa.app.services.audit.reproducibility import (
    _reset_environment_snapshot_for_tests,
    compute_node_registry_hash,
)


@pytest_asyncio.fixture
async def async_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    install_audit_flush_listener()
    _reset_process_boot_id_for_tests()
    _reset_environment_snapshot_for_tests()
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        session.add(User(username="alice"))
        await session.commit()
        yield session
    await engine.dispose()


@pytest.fixture
def alice_context(monkeypatch):
    monkeypatch.setattr(app_config, "audit_enabled", True)
    ctx = AuditContext(
        tenant_id="acme",
        actor_id=1,
        actor_kind="user",
        request_id=str(uuid.uuid4()),
    )
    token = set_audit_context(ctx)
    yield ctx
    reset_audit_context(token)


def test_environment_snapshot_shape():
    """Cached snapshot exposes the v0.5 fields with the right types."""
    _reset_environment_snapshot_for_tests()
    env = get_environment_snapshot()
    assert isinstance(env.software_version, str) and env.software_version
    assert isinstance(env.python_runtime, str) and "Python " in env.python_runtime or "CPython" in env.python_runtime
    assert env.pid > 0
    # Optional fields may be None on some hosts — but the attribute must exist.
    for opt in (env.git_commit_sha, env.python_lockfile_hash, env.runtime_image, env.hostname, env.container_id):
        assert opt is None or isinstance(opt, str)


def test_build_reproducibility_record_minimum_fields():
    """The builder produces a record carrying every required field."""
    record = build_reproducibility_record(
        workflow_id=42,
        workflow_version_id=7,
        workflow_integrity_hash="abc123",
        parameter_set={"smoothing": "sg"},
        model_artifact_uids=["uid-pca-001"],
    )
    assert_reproducibility_record_complete(record)
    for key in REQUIRED_REPRODUCIBILITY_FIELDS:
        assert key in record, f"missing key {key!r}"
    assert record["workflow_id"] == 42
    assert record["workflow_version_id"] == 7
    assert record["workflow_integrity_hash"] == "abc123"
    assert record["parameter_set"] == {"smoothing": "sg"}
    assert record["model_artifact_uids"] == ["uid-pca-001"]


def test_assert_reproducibility_record_complete_raises_on_gaps():
    """The helper raises AssertionError listing missing keys."""
    incomplete = {"workflow_id": 1, "parameter_set": {}}
    with pytest.raises(AssertionError) as exc:
        assert_reproducibility_record_complete(incomplete)
    msg = str(exc.value)
    # Should call out fields that are missing
    for missing in ("workflow_integrity_hash", "software_version", "python_runtime", "hostname"):
        assert missing in msg


def test_node_registry_hash_is_stable_within_process():
    """compute_node_registry_hash returns the same digest on repeated calls."""
    h1 = compute_node_registry_hash()
    h2 = compute_node_registry_hash()
    # Either both None (no registry) or both equal
    assert h1 == h2


async def test_workflow_run_completed_event_carries_full_reproducibility_record(async_session, alice_context):
    """The Phase 1c hook now uses the Phase 1d builder — verify the audit
    event in a real flow carries all required fields."""
    from spectra_sherpa.app.api.v1.routes.workflows._helpers import _auto_persist_run

    await _auto_persist_run(
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

    rows = (await async_session.execute(select(AuditEvent))).scalars().all()
    assert len(rows) == 1
    event = rows[0]
    record = event.context["reproducibility_record"]
    # Use the same enforcement helper service-layer code can call.
    assert_reproducibility_record_complete(record)
    # Spot-check that the environment block actually landed
    assert record["software_version"]
    assert record["python_runtime"]
    assert record["pid"] > 0
    # And the per-run fields are correct
    assert record["workflow_id"] == 42
    assert record["workflow_version_id"] == 7
    assert record["workflow_integrity_hash"] == "abc123"
    assert record["parameter_set"] == {"baseline_correction": "snv"}
    assert record["model_artifact_uids"] == ["uid-pca-001"]
