"""Pydantic schemas for the audit query API.

Phase 4 C2 — wire schema for ``GET /api/v1/audit/events``. Per
``packages/spectra-server/docs/dev/audit/phase0-design.md §3``:

    audit.basic | Any deployment with SHERPA_AUDIT_ENABLED=true
    (incl. OSS Local) | GET /api/v1/audit/events paginated query
    restricted to caller's own tenant

The OSS handler owns this contract. Server-side admin/cross-tenant
query (Phase 4 follow-up) will reuse the same response envelope so
frontend code paths don't fork.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditEventOut(BaseModel):
    """One audit-event row, projected for the query API.

    Excluded from the projection (intentional):

      * ``app_monotonic_ns`` and ``process_boot_id`` — forensic
        ordering metadata used by the chainer; not useful in the
        query response and could leak infra timing detail.

    Included (per design §4.1): the full identity + state-snapshot
    payload so a forensic reader can reconstruct what happened
    without a second round-trip.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: str
    actor_id: int | None = None
    actor_kind: str
    action: str
    target_type: str
    target_id: str
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    request_id: str
    ts_app_utc: datetime
    ts_db_utc: datetime


class AuditEventQueryResponse(BaseModel):
    """Paginated response envelope.

    ``next_cursor`` is the integer ``id`` of the last returned row
    when ``has_more`` is True, serialised as a string for forward
    compatibility (a future opaque-cursor format can swap in without
    breaking clients that already treat the value as opaque).

    Caller pages by passing the returned ``next_cursor`` back as the
    ``cursor`` query param on the next request — yields events with
    ``id < cursor`` in descending-id order.
    """

    events: list[AuditEventOut] = Field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False
