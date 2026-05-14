"""AuditEmitter — same-transaction audit-event writer.

Design pattern (per phase0-design.md §1 + §5.1):

  * Service code calls ``audit_emitter.emit(session=..., action=...,
    target_type=..., target_id=..., ...)``.
  * The emitter captures the current AuditContext + timestamps +
    monotonic-ns + boot id and adds a real ``AuditEvent`` to the
    session. The event row commits **in the same transaction** as the
    business mutation that triggered it.

Phase 1b uses a direct ``session.add(AuditEvent(...))`` pattern.
SQLAlchemy's ``before_flush`` event does not fire when no objects need
flushing, so the staging-and-listener pattern described in the design
doc was over-engineered for the explicit-emit case; the listener pattern
will reappear in Phase 3 when auto-tracking attribute-history hooks
actually need the pending-list indirection (dedup, enrichment from
attribute history). For Phase 1b, explicit emit calls suffice.

Fail-open vs fail-closed (decision #9):

  * When ``app_config.audit_enabled == False``, ``emit()`` is a no-op.
  * When ``audit_enabled == True``, the audit row is added to the
    session and commits with the business mutation. If the audit row's
    insert fails (constraint violation, etc.), SQLAlchemy raises and
    the whole transaction rolls back. The user sees an error rather
    than a silent unaudited state change.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.models.audit_event import AuditEvent
from spectra_sherpa.app.services.audit.boot import get_process_boot_id
from spectra_sherpa.app.services.audit.context import AuditContext, get_audit_context

logger = logging.getLogger(__name__)


class AuditEmitter:
    """The single emitter instance applications and tests share.

    Most call sites use the module-level :data:`audit_emitter`. The
    class exists to support tests that need a clean per-fixture instance
    and any future per-tenant emitter sharding.
    """

    def emit(
        self,
        *,
        session: Session,
        action: str,
        target_type: str,
        target_id: str | int,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        tenant_id: str | None = None,
    ) -> None:
        """Stage a pending audit event on ``session``.

        No-op when ``audit_enabled`` is False (the cheap path that lets
        OSS-Local installs run with zero audit overhead).

        Parameters
        ----------
        session
            The active SQLAlchemy session in which the business
            mutation lives. The audit event is added to **this**
            session so it commits with the same transaction.
        action
            Dotted action identifier, e.g. ``"workflow.run.completed"``,
            ``"model_artifact.deleted"``, ``"audit.export"``.
        target_type
            Class name of the target entity (string), e.g. ``"Workflow"``.
        target_id
            Primary key of the target. Coerced to ``str`` — schema
            stores ``target_id`` as a string for cross-table portability.
        before, after
            Snapshot dicts of pre- and post-mutation state. Either may
            be ``None`` for the boundary actions (``created`` has no
            before; ``deleted`` has no after).
        context
            Free-form action-specific payload. For
            ``workflow.run.*`` events, must include the full
            reproducibility record per
            ``docs/audit/minimum-reproducibility-record.md``.
        tenant_id
            Override of the context tenant id. Almost always ``None`` —
            the request-bound context is the source of truth. Provided
            for the narrow background-task case where the tenant must
            be supplied explicitly.
        """
        if not app_config.audit_enabled:
            return

        ctx = get_audit_context()
        if ctx is None:
            ctx = _synthesize_system_context(tenant_id_override=tenant_id)
            logger.warning(
                "Audit: emit('%s') called without a bound AuditContext; "
                "synthesising system context. This is a wiring bug if it "
                "happens during a real HTTP request.",
                action,
            )

        effective_tenant = tenant_id or ctx.tenant_id
        merged_context = _merge_extra_into_context(context, ctx.extra)

        event = AuditEvent(
            tenant_id=effective_tenant,
            actor_id=ctx.actor_id,
            actor_kind=ctx.actor_kind,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            before_state=before,
            after_state=after,
            context=merged_context,
            request_id=ctx.request_id,
            ts_app_utc=datetime.now(timezone.utc),
            app_monotonic_ns=time.monotonic_ns(),
            process_boot_id=get_process_boot_id(),
        )
        session.add(event)


# Module-level singleton — service code imports this rather than
# constructing a fresh emitter.
audit_emitter = AuditEmitter()


def _merge_extra_into_context(context: dict[str, Any] | None, extra: dict[str, Any] | None) -> dict[str, Any] | None:
    """Fold AuditContext.extra (request-scoped metadata) into the event
    ``context`` field under a stable key.

    Keeping a stable shape — ``{"_request_extra": {...}}`` — gives audit
    consumers a predictable place to find IP, user-agent, API-key id,
    etc., without polluting the action-specific payload.
    """
    if not extra:
        return context
    merged = dict(context) if context else {}
    merged.setdefault("_request_extra", extra)
    return merged


def _synthesize_system_context(tenant_id_override: str | None = None) -> AuditContext:
    """Build a fallback context for emit calls outside a real request.

    Used when background tasks or ad-hoc scripts emit events. The
    resulting events are tagged as ``actor_kind='system'`` so audit
    consumers can distinguish them from user-initiated mutations.
    """
    import uuid

    return AuditContext(
        tenant_id=tenant_id_override or "default",
        actor_id=None,
        actor_kind="system",
        request_id=uuid.uuid4().hex,
        extra={"synthesised": True},
    )
