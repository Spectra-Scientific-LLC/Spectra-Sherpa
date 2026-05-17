"""Audit-event subsystem (ISO 17025 readiness — Phase 1).

Public API:

    from spectra_sherpa.app.services.audit import (
        AuditContext, AuditEmitter, audit_emitter,
        get_audit_context, set_audit_context,
        get_process_boot_id, init_process_boot_id,
        install_audit_flush_listener,
        AuditMiddleware,
    )

Wiring at app startup (FastAPI lifespan):

    init_process_boot_id()              # mint a UUID stable for this process
    install_audit_flush_listener()      # SQLAlchemy before_flush hook

Wiring as middleware:

    app.add_middleware(AuditMiddleware)

Service-code call site (anywhere inside a session):

    audit_emitter.emit(
        session=session,
        action="workflow.run.completed",
        target_type="Workflow",
        target_id=workflow.id,
        before=...,
        after=...,
        context={"reproducibility_record": {...}},
    )

See ``the audit-subsystem design specification`` for the
locked design.
"""

from spectra_sherpa.app.services.audit.boot import (
    get_process_boot_id,
    init_process_boot_id,
)
from spectra_sherpa.app.services.audit.context import (
    AuditContext,
    get_audit_context,
    reset_audit_context,
    set_audit_context,
    use_audit_context,
)
from spectra_sherpa.app.services.audit.coverage import (
    AUDITED_MODELS,
    AuditedModel,
    audit_excluded,
    get_excluded_sites,
)
from spectra_sherpa.app.services.audit.emitter import AuditEmitter, audit_emitter
from spectra_sherpa.app.services.audit.listeners import install_audit_flush_listener
from spectra_sherpa.app.services.audit.middleware import AuditMiddleware
from spectra_sherpa.app.services.audit.reproducibility import (
    REQUIRED_REPRODUCIBILITY_FIELDS,
    assert_reproducibility_record_complete,
    build_reproducibility_record,
    compute_node_registry_hash,
    get_environment_snapshot,
)

__all__ = [
    "AUDITED_MODELS",
    "REQUIRED_REPRODUCIBILITY_FIELDS",
    "AuditContext",
    "AuditEmitter",
    "AuditMiddleware",
    "AuditedModel",
    "assert_reproducibility_record_complete",
    "audit_emitter",
    "audit_excluded",
    "build_reproducibility_record",
    "compute_node_registry_hash",
    "get_audit_context",
    "get_environment_snapshot",
    "get_excluded_sites",
    "get_process_boot_id",
    "init_process_boot_id",
    "install_audit_flush_listener",
    "reset_audit_context",
    "set_audit_context",
    "use_audit_context",
]
