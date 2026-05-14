"""Phase 1d — hot-path overhead benchmark.

Phase 0 design budget: hot-path overhead per audited mutation **< 2 %**.

This benchmark exercises ``_auto_persist_run`` with audit_enabled
toggled between False and True, runs each N times, and asserts that
the enabled path is not catastrophically slower than the disabled
path. The numbers are noisy on shared CI hardware, so the assertion is
generous (audit_enabled run no more than 5x the audit_disabled run);
the budget itself is captured as a printed observation in the test
output for human review at PR time.

Phase 6 will re-run this benchmark on dev hardware with the tighter
2% budget once the chainer is in place. The Phase 1d version exists
mainly to catch *catastrophic* regressions (a 100x overhead from a
botched index, a global lock, etc.).
"""

from __future__ import annotations

import time
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.db.base import Base
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.audit import (
    AuditContext,
    install_audit_flush_listener,
    reset_audit_context,
    set_audit_context,
)
from spectra_sherpa.app.services.audit.boot import _reset_process_boot_id_for_tests


@pytest_asyncio.fixture
async def async_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    install_audit_flush_listener()
    _reset_process_boot_id_for_tests()
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        session.add(User(username="alice"))
        await session.commit()
    yield factory
    await engine.dispose()


@pytest.fixture
def alice_context():
    ctx = AuditContext(
        tenant_id="acme",
        actor_id=1,
        actor_kind="user",
        request_id=str(uuid.uuid4()),
    )
    token = set_audit_context(ctx)
    yield ctx
    reset_audit_context(token)


async def _run_n_persists(factory, *, n: int) -> float:
    """Run ``_auto_persist_run`` N times in fresh sessions; return wall time."""
    from spectra_sherpa.app.api.v1.routes.workflows._helpers import _auto_persist_run

    start = time.perf_counter()
    for i in range(n):
        async with factory() as session:
            await _auto_persist_run(
                session,
                workflow_id=42,
                user_id=1,
                wf_version_id=7,
                serialized_results={"node-1": {"X": [1, 2, 3]}},
                diagnostics_serialized={},
                node_statuses={"node-1": "completed"},
                final_status="completed",
                error_msg=None,
                integrity_hash=f"hash-{i}",
                model_ids=None,
                params_snapshot={"i": i},
            )
    return time.perf_counter() - start


async def test_audit_hot_path_not_catastrophic(async_session_factory, alice_context, capsys, monkeypatch):
    """Audit enabled should not be more than 5x slower than disabled.

    A 5x ceiling is generous; the design budget is 2%. The looser
    bound here catches catastrophic regressions on shared CI hardware
    where the strict budget would be noise-bound. Real numbers are
    printed for review.
    """
    iterations = 30

    # Warm-up — populate SQLAlchemy's compile cache so the first
    # iteration's overhead isn't counted in the timed loop.
    monkeypatch.setattr(app_config, "audit_enabled", False)
    await _run_n_persists(async_session_factory, n=2)

    monkeypatch.setattr(app_config, "audit_enabled", False)
    disabled_seconds = await _run_n_persists(async_session_factory, n=iterations)

    monkeypatch.setattr(app_config, "audit_enabled", True)
    enabled_seconds = await _run_n_persists(async_session_factory, n=iterations)

    ratio = enabled_seconds / max(disabled_seconds, 1e-6)
    overhead_pct = (ratio - 1.0) * 100

    # Stable observation printed for the PR reviewer / future Phase 6
    # benchmark. captured via -s or shown on failure.
    print(
        f"\n[audit hot-path benchmark]"
        f"\n  iterations:           {iterations}"
        f"\n  disabled total (s):   {disabled_seconds:.4f}"
        f"\n  enabled total  (s):   {enabled_seconds:.4f}"
        f"\n  per-op disabled (ms): {disabled_seconds / iterations * 1000:.3f}"
        f"\n  per-op enabled  (ms): {enabled_seconds / iterations * 1000:.3f}"
        f"\n  overhead:             {overhead_pct:+.1f}%"
    )

    # Catastrophic-regression assertion. Re-tighten in Phase 6 on dev
    # hardware with controlled noise.
    assert ratio < 5.0, (
        f"Audit enabled hot path is {ratio:.2f}x disabled — far above the "
        f"Phase 6 2% target. Investigate before promoting Phase 1d."
    )
