"""Add audit-event subsystem (ISO 17025 readiness — Phase 1)

Creates three tables that together implement the audit-trail substrate:

  * ``audit_event`` — raw events, written in the same SQLAlchemy
    transaction as the business mutation that triggered them.
    Append-only.
  * ``audit_event_chain`` — chain rows, written post-commit by the
    proprietary server-side chainer. Append-only. Empty in OSS-only
    deployments.
  * ``audit_chain_head`` — per-tenant chain cursor, maintained by the
    chainer under ``SELECT ... FOR UPDATE``.

This migration creates the tables and their indexes on both SQLite (OSS
Local) and Postgres (hosted). Postgres-specific concerns (RANGE
partitioning on ``ts_db_utc``, role grants for ``app_audit_writer`` and
``app_audit_chainer``) are intentionally deferred to a follow-up
migration: partitioning matters at volume, role grants matter for
production. Neither is required for Phase 1 smoke tests.

See ``packages/spectra-server/docs/dev/audit/phase0-design.md`` for
locked design decisions and ``minimum-reproducibility-record.md`` for
the field-level reproducibility contract.

Revision ID: a17025aud001
Revises: 44c09f7e75ef
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a17025aud001"
down_revision = "44c09f7e75ef"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if not _table_exists("audit_event"):
        op.create_table(
            "audit_event",
            sa.Column(
                "id",
                sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
                primary_key=True,
                autoincrement=True,
            ),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column(
                "actor_id",
                sa.Integer,
                sa.ForeignKey("user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("actor_kind", sa.String(length=16), nullable=False),
            sa.Column("action", sa.String(length=64), nullable=False),
            sa.Column("target_type", sa.String(length=64), nullable=False),
            sa.Column("target_id", sa.String(length=64), nullable=False),
            sa.Column("before_state", sa.JSON, nullable=True),
            sa.Column("after_state", sa.JSON, nullable=True),
            sa.Column("context", sa.JSON, nullable=True),
            sa.Column("request_id", sa.String(length=36), nullable=False),
            sa.Column("ts_app_utc", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "ts_db_utc",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column("app_monotonic_ns", sa.BigInteger, nullable=False),
            sa.Column("process_boot_id", sa.String(length=36), nullable=False),
        )

        op.create_index(
            "ix_audit_event_tenant_ts",
            "audit_event",
            ["tenant_id", "ts_db_utc"],
        )
        op.create_index(
            "ix_audit_event_tenant_action",
            "audit_event",
            ["tenant_id", "action"],
        )
        op.create_index(
            "ix_audit_event_tenant_target",
            "audit_event",
            ["tenant_id", "target_type", "target_id"],
        )
        op.create_index("ix_audit_event_actor", "audit_event", ["actor_id"])
        op.create_index("ix_audit_event_request", "audit_event", ["request_id"])

    if not _table_exists("audit_event_chain"):
        op.create_table(
            "audit_event_chain",
            sa.Column(
                "event_id",
                sa.BigInteger,
                sa.ForeignKey("audit_event.id"),
                primary_key=True,
            ),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("tenant_sequence", sa.BigInteger, nullable=False),
            sa.Column("prev_hash", sa.LargeBinary(32), nullable=True),
            sa.Column("event_hmac", sa.LargeBinary(32), nullable=False),
            sa.Column("chain_key_id", sa.String(length=32), nullable=False),
            sa.Column(
                "chained_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

        # Strict per-tenant ordering — verification walks the chain in
        # this order. UNIQUE catches the (rare but real) chainer bug
        # where the same sequence gets assigned twice.
        op.create_index(
            "uq_audit_chain_tenant_sequence",
            "audit_event_chain",
            ["tenant_id", "tenant_sequence"],
            unique=True,
        )

    if not _table_exists("audit_chain_head"):
        op.create_table(
            "audit_chain_head",
            sa.Column("tenant_id", sa.String(length=64), primary_key=True),
            sa.Column(
                "latest_sequence",
                sa.BigInteger,
                nullable=False,
                server_default="0",
            ),
            sa.Column("latest_hash", sa.LargeBinary(32), nullable=True),
            sa.Column("active_key_id", sa.String(length=32), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )


def downgrade() -> None:
    # Order: drop in reverse-FK order. audit_event_chain.event_id → audit_event.id
    for index_name in ("uq_audit_chain_tenant_sequence",):
        try:
            op.drop_index(index_name, table_name="audit_event_chain")
        except Exception:
            pass
    op.drop_table("audit_chain_head")
    op.drop_table("audit_event_chain")

    for index_name in (
        "ix_audit_event_request",
        "ix_audit_event_actor",
        "ix_audit_event_tenant_target",
        "ix_audit_event_tenant_action",
        "ix_audit_event_tenant_ts",
    ):
        try:
            op.drop_index(index_name, table_name="audit_event")
        except Exception:
            pass
    op.drop_table("audit_event")
