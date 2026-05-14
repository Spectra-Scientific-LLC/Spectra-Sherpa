"""SQLAlchemy event hooks for the audit subsystem.

Phase 1b uses direct ``session.add(AuditEvent(...))`` in
:meth:`AuditEmitter.emit`, so no flush-time listener is required: the
audit row commits with the same transaction as the business mutation
out of the box.

This module is kept as a stable public surface — service code and the
FastAPI lifespan call :func:`install_audit_flush_listener` whether or
not the listener does work today. Phase 3 will reintroduce real
listeners here when:

  * automatic attribute-history capture is added (hook into
    ``before_flush`` to walk ``session.dirty`` and emit ``state.changed``
    events for audited models that callers forgot to instrument), and
  * the CI coverage-guard test re-uses the same hook to fail builds
    when a state-changing path lacks an emit call.

For now the function is idempotent and intentionally cheap.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_installed = False


def install_audit_flush_listener() -> None:
    """Phase 1b: no-op stub.

    Idempotent. Safe to call from lifespan startup, from tests, and from
    other modules during initialisation. The real listener implementation
    lands in Phase 3 (automatic attribute-history capture + coverage
    guard).
    """
    global _installed
    if _installed:
        return
    _installed = True
    logger.debug(
        "Audit: install_audit_flush_listener — Phase 1b stub; "
        "real listeners arrive with Phase 3 attribute-history hooks."
    )
