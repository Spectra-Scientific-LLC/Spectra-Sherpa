"""Phase 4 C2 — ``GET /api/v1/audit/events`` paginated query.

Per ``packages/spectra-server/docs/dev/audit/phase0-design.md §3``,
this is the OSS-side query handler gated by ``audit.basic`` (which
the design treats as a deployment capability, not a plan
entitlement: granted whenever ``SHERPA_AUDIT_ENABLED=true``).

Scope:

  * Restricted to the caller's own tenant. Cross-tenant scope is a
    separate ``audit.full`` server-side feature wired in a follow-up
    Phase 4 commit.
  * Returns 403 when ``app_config.audit_enabled`` is False — same
    posture as the design's "no deployment capability" rule.
  * Reads of audit events are NOT themselves audited (per §6
    "audit-event read queries themselves are explicitly excluded —
    would create a feedback loop"); only exports get audit rows.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.contracts.auth_resolver import is_admin_user
from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.models.audit_event import AuditEvent
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.schemas.audit import AuditEventOut, AuditEventQueryResponse
from spectra_sherpa.app.services.audit.context import get_audit_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit")

# Pagination caps. ``limit=500`` matches the existing OSS conventions
# (jobs.py, models.py); keeping the upper bound shared avoids
# surprise-budget tuning per route.
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 500

# Allowed actor_kind values (mirrors AuditEvent.actor_kind enum from
# design §4.1). Pinning here so a typo in a query param fails fast
# with a clear 422 instead of silently returning empty.
_ALLOWED_ACTOR_KINDS = {"user", "system", "api_key", "webhook"}


def _resolve_query_tenant() -> str:
    """Return the tenant_id the current request is scoped to.

    The audit middleware binds ``AuditContext.tenant_id`` for every
    HTTP request when audit is enabled. Falling back to
    ``app_config.site_profile`` mirrors the middleware's resolution
    so the route works under unusual middleware-ordering bugs (e.g.
    a future test harness that emits events without the middleware).
    """
    ctx = get_audit_context()
    if ctx is not None and ctx.tenant_id:
        return ctx.tenant_id
    if app_config.site_profile:
        return app_config.site_profile
    return "default"


@router.get("/events", response_model=AuditEventQueryResponse)
async def list_audit_events(
    cursor: str | None = Query(
        default=None,
        description=(
            "Opaque cursor from a previous response's ``next_cursor``. "
            "Returns events with ``id < cursor`` in descending order."
        ),
    ),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    action: str | None = Query(default=None, description="Exact match on dotted action verb."),
    target_type: str | None = Query(default=None, description="Exact match on target_type (e.g. 'Workflow')."),
    target_id: str | None = Query(default=None, description="Exact match on target_id (string)."),
    actor_id: int | None = Query(default=None, description="Filter by actor user id."),
    actor_kind: str | None = Query(
        default=None,
        description="One of: user, system, api_key, webhook.",
    ),
    request_id: str | None = Query(default=None, description="Correlate events from one request."),
    since: datetime | None = Query(
        default=None,
        description="Inclusive lower bound on ts_app_utc (ISO 8601).",
    ),
    until: datetime | None = Query(
        default=None,
        description="Exclusive upper bound on ts_app_utc (ISO 8601).",
    ),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> AuditEventQueryResponse:
    """Paginated, tenant-scoped query over ``audit_event``.

    Pagination is cursor-based on the monotonic ``id`` PK
    (descending). The query reads ``limit + 1`` rows so the response
    can declare ``has_more`` without a second round-trip.

    Within-tenant scope:
      * Non-admin callers see ONLY events whose ``actor_id`` matches
        their own user id. Catches the multi-user OSS / Team-tier
        privacy gap a Phase 4 review flagged: tenant-wide reads
        without role checks would let any authenticated user read
        every other user's project / workflow / model audit history
        (including before/after state snapshots).
      * Admin callers bypass the actor filter and see everything in
        the tenant. Cross-tenant scope remains the moat for the future
        ``audit.full`` server-side admin route.

    Admin status is resolved through the OSS auth-resolver contract:
    the ``is_superuser`` flag lives on ``ManagedUserAccount`` in
    server-side deployments (per the v0.4.1 monorepo split), not on
    the OSS ``User`` model. Without a server-registered resolver the
    helper returns False, which is the correct OSS fail-closed default.
    """
    if not app_config.audit_enabled:
        # Per design §3 line 82: "OSS handler checks audit.basic
        # directly and 403s if the deployment has audit_enabled=false".
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Audit is not enabled on this deployment (set SHERPA_AUDIT_ENABLED=true).",
        )

    if actor_kind is not None and actor_kind not in _ALLOWED_ACTOR_KINDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"actor_kind must be one of {sorted(_ALLOWED_ACTOR_KINDS)}",
        )

    cursor_id: int | None = None
    if cursor is not None:
        try:
            cursor_id = int(cursor)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="cursor must be an integer event id (use the value returned in next_cursor).",
            ) from None

    if since is not None and until is not None and since >= until:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="since must be earlier than until.",
        )

    tenant = _resolve_query_tenant()

    q = select(AuditEvent).where(AuditEvent.tenant_id == tenant)

    # Within-tenant actor scope. See route docstring above for the
    # threat model. Pinned by tests in test_query_endpoint.py.
    if not await is_admin_user(current_user):
        q = q.where(AuditEvent.actor_id == current_user.id)

    if cursor_id is not None:
        q = q.where(AuditEvent.id < cursor_id)
    if action is not None:
        q = q.where(AuditEvent.action == action)
    if target_type is not None:
        q = q.where(AuditEvent.target_type == target_type)
    if target_id is not None:
        q = q.where(AuditEvent.target_id == target_id)
    if actor_id is not None:
        q = q.where(AuditEvent.actor_id == actor_id)
    if actor_kind is not None:
        q = q.where(AuditEvent.actor_kind == actor_kind)
    if request_id is not None:
        q = q.where(AuditEvent.request_id == request_id)
    if since is not None:
        q = q.where(AuditEvent.ts_app_utc >= since)
    if until is not None:
        q = q.where(AuditEvent.ts_app_utc < until)

    # Read limit+1 to detect has_more without a count query.
    q = q.order_by(AuditEvent.id.desc()).limit(limit + 1)

    rows = list((await session.execute(q)).scalars())
    has_more = len(rows) > limit
    rows = rows[:limit]

    next_cursor = str(rows[-1].id) if has_more and rows else None
    return AuditEventQueryResponse(
        events=[AuditEventOut.model_validate(r) for r in rows],
        next_cursor=next_cursor,
        has_more=has_more,
    )
