"""AuditContext — per-request identity, actor, and request correlation.

A ``ContextVar`` bound by ``AuditMiddleware`` (HTTP) or by the WebSocket
dispatch loop (when audit on WS handlers lands in Phase 3). Service-code
emitter calls read this context to attribute each event.

Pattern mirrors ``spectra_sherpa.app.core.request_id`` — set on entry,
reset on exit via a token.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, Iterator


@dataclass(frozen=True)
class AuditContext:
    """Per-request identity carried with every emitted audit event.

    Bound at request entry (HTTP middleware / WebSocket dispatch) and
    consumed by ``AuditEmitter.emit()``. Frozen so that emitter code
    cannot mutate it mid-request.
    """

    tenant_id: str
    """Tenant scope. Single-tenant-per-droplet today = one value; the
    schema supports multi-tenancy from day one."""

    actor_id: int | None
    """FK to ``user.id`` when ``actor_kind == 'user'``; ``None`` for
    system / unauthenticated / API-key contexts (paired with
    ``actor_kind`` and an optional system-actor string in ``extra``)."""

    actor_kind: str
    """One of ``user``, ``system``, ``api_key``, ``webhook``."""

    request_id: str
    """UUID hex correlating events emitted during the same request."""

    extra: dict[str, Any] | None = None
    """Optional bag for action-class-specific context. Plain dict so
    callers can attach IP, user-agent, API-key id, etc."""


_audit_context: ContextVar[AuditContext | None] = ContextVar("audit_context", default=None)


def get_audit_context() -> AuditContext | None:
    """Return the current audit context, or ``None`` outside a request.

    A ``None`` return at emit time is a code-smell — the emitter
    synthesises a fallback "system" context and logs a warning so the
    missing wiring is visible.
    """
    return _audit_context.get()


def set_audit_context(ctx: AuditContext | None) -> Token[AuditContext | None]:
    """Bind ``ctx`` for the current async / thread context.

    Returns the reset token so the caller can release the binding
    deterministically (typically inside a ``finally``). Most call sites
    should prefer :func:`use_audit_context`.
    """
    return _audit_context.set(ctx)


def reset_audit_context(token: Token[AuditContext | None]) -> None:
    """Release a previously-bound context."""
    _audit_context.reset(token)


@contextmanager
def use_audit_context(ctx: AuditContext | None) -> Iterator[AuditContext | None]:
    """Bind ``ctx`` for the duration of a ``with`` block.

    Cleaner than the bare token API for service-code call sites that
    need to widen an existing context (e.g. background tasks that
    fabricate a system context).
    """
    token = _audit_context.set(ctx)
    try:
        yield ctx
    finally:
        _audit_context.reset(token)
