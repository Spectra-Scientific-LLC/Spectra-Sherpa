"""Audit-event models for ISO 17025 readiness.

Three tables:
  * ``audit_event`` — raw events, written in the same transaction as the
    business mutation that triggered them (fail-closed when audit is
    enabled). Append-only.
  * ``audit_event_chain`` — one chain row per event, written post-commit
    by the server-side chainer. Carries the HMAC chain field, the
    ``tenant_sequence`` forensic ordering primitive, and the active key
    id. Append-only.
  * ``audit_chain_head`` — per-tenant cursor maintained by the chainer.
    Holds the latest sequence and hash for chain advancement under
    ``SELECT ... FOR UPDATE``.

OSS deployments write to ``audit_event`` only. The chain tables exist in
the schema so the contract is published, but they are written exclusively
by the proprietary chainer process in ``spectra-server``.

See ``the audit-subsystem design specification`` for the
locked design decisions.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from spectra_sherpa.app.db.base import Base


class AuditEvent(Base):
    """One audit-event row.

    Written in the same SQLAlchemy session as the business mutation
    that triggered it. ``AuditEmitter.emit()`` constructs the model and
    calls ``session.add(event)`` directly, so the audit row commits or
    rolls back with the business mutation (fail-closed, design doc
    decision #9). Phase 1b explicitly does **not** use the
    staging-then-flush-listener pattern sketched in v0 of the design —
    ``before_flush`` does not fire when no objects need flushing, which
    silently dropped events. The Phase 3 attribute-history listener
    will reintroduce a listener for auto-tracking, with a deterministic
    idempotency key.

    The row carries NO chain fields. ``tenant_sequence``, ``prev_hash``,
    and ``event_hmac`` live on ``audit_event_chain`` and are populated
    post-commit by the server-side chainer. OSS-only deployments leave
    those tables empty; the OSS query API surfaces ``audit_event`` rows
    directly without joining the chain.
    """

    __tablename__ = "audit_event"

    # Auto-increment PK with strict insertion order. On SQLite (OSS
    # Local) we use the dialect's INTEGER PRIMARY KEY semantics so
    # ROWID-style autoincrement kicks in; on Postgres we keep the full
    # 64-bit BIGINT range. See design doc §4.1 for why UUID7 was
    # rejected for this codebase.
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )

    # Tenant scope. Single-tenant-per-droplet today = one value
    # (``default`` for OSS Local, the deployment-key id for hosted). The
    # schema supports multi-tenancy from day one even though the runtime
    # is single-tenant.
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # Actor: FK to user.id when actor_kind == 'user'. NULL for system
    # actions, paired with actor_kind='system' and a ``system_actor``
    # string in ``context``.
    actor_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)

    # Action and target. Examples:
    #   action='workflow.run.completed', target_type='Workflow', target_id='42'
    #   action='audit.export',           target_type='AuditExport', target_id='17'
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # State snapshots (nullable for created/deleted boundary actions).
    before_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Free-form context per action class. For workflow.run.*, carries the
    # full reproducibility record (see
    # docs/audit/minimum-reproducibility-record.md).
    context: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Request correlation. UUID-as-string for SQLite portability.
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)

    # Two wall-clock UTC timestamps + a monotonic-ns pair. Renaming and
    # the monotonic/boot-id fields are v0.5 corrections — see design doc
    # decision #4.
    ts_app_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ts_db_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    app_monotonic_ns: Mapped[int] = mapped_column(BigInteger, nullable=False)
    process_boot_id: Mapped[str] = mapped_column(String(36), nullable=False)

    __table_args__ = (
        # Tenant-scoped query path: list events for one tenant by time.
        Index("ix_audit_event_tenant_ts", "tenant_id", "ts_db_utc"),
        # Filter by action class within a tenant.
        Index("ix_audit_event_tenant_action", "tenant_id", "action"),
        # Filter by target within a tenant — common in detail-page links.
        Index("ix_audit_event_tenant_target", "tenant_id", "target_type", "target_id"),
        # Actor-scoped audit queries.
        Index("ix_audit_event_actor", "actor_id"),
        # Request correlation.
        Index("ix_audit_event_request", "request_id"),
    )


class AuditEventChain(Base):
    """One chain row per ``AuditEvent``.

    Written post-commit by the server-side chainer (see
    ``spectrasherpa_server.audit.chainer``). OSS deployments never insert
    here — the table exists in the schema so the contract is published
    and verification tooling can rely on a stable shape.

    The chain links via ``prev_hash``; verification walks rows in
    ``(tenant_id, tenant_sequence)`` order and confirms each
    ``event_hmac`` matches.

    See design doc §4.2 and §4.4 for the canonical-JSON HMAC formula.
    """

    __tablename__ = "audit_event_chain"

    event_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("audit_event.id"),
        primary_key=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # Strict per-tenant forensic ordering. Assigned by the chainer under
    # SELECT ... FOR UPDATE on audit_chain_head. This is NOT the
    # user-perceived commit order — see design doc §5.2 invariants.
    tenant_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Chain link. NULL on the first chain row per tenant.
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)

    # HMAC-SHA256 over prev_hash || canonical_json(event_payload). The
    # canonical-JSON payload includes ``id``, ``tenant_id``,
    # ``tenant_sequence``, plus the event's content fields. Including
    # ``id`` and ``tenant_sequence`` defeats id-swap and resequence
    # attacks.
    event_hmac: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False)

    # Identifies which HMAC key was active when this row was chained —
    # required for verification after key rotation.
    chain_key_id: Mapped[str] = mapped_column(String(32), nullable=False)

    chained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        # Verification walks the chain in (tenant_id, tenant_sequence) order.
        Index(
            "uq_audit_chain_tenant_sequence",
            "tenant_id",
            "tenant_sequence",
            unique=True,
        ),
    )


class AuditChainHead(Base):
    """Per-tenant chain cursor.

    The chainer holds ``SELECT ... FOR UPDATE`` on the relevant row while
    advancing the chain. Bounded batches and ``FOR UPDATE SKIP LOCKED``
    ensure replicas do not starve each other; see design doc §5.2
    invariants.
    """

    __tablename__ = "audit_chain_head"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    latest_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    latest_hash: Mapped[bytes | None] = mapped_column(LargeBinary(32), nullable=True)
    active_key_id: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
