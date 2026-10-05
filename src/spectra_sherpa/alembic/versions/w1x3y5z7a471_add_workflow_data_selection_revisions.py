"""Add append-only workflow data-selection revisions.

Revision ID: w1x3y5z7a471
Revises: v0w2x4y6z360
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "w1x3y5z7a471"
down_revision = "v0w2x4y6z360"
branch_labels = None
depends_on = None


def _table_exists() -> bool:
    return sa.inspect(op.get_bind()).has_table("workflow_data_selection_revision")


def upgrade() -> None:
    # Fresh installations create Base.metadata before Alembic stamps the
    # migration chain. Tracked databases reach this revision without the table.
    if _table_exists():
        return
    op.create_table(
        "workflow_data_selection_revision",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("workflow.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_node_id", sa.String(255), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column(
            "parent_revision_id",
            sa.Integer(),
            sa.ForeignKey("workflow_data_selection_revision.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("selection", sa.JSON(), nullable=False),
        sa.Column("graph_digest", sa.String(64), nullable=False),
        sa.UniqueConstraint(
            "workflow_id", "source_node_id", "revision_number", name="uq_workflow_data_selection_revision"
        ),
        sa.UniqueConstraint(
            "workflow_id", "source_node_id", "idempotency_key", name="uq_workflow_data_selection_idempotency"
        ),
    )
    op.create_index(
        "ix_workflow_data_selection_revision_workflow_id",
        "workflow_data_selection_revision",
        ["workflow_id"],
    )
    op.create_index(
        "ix_workflow_data_selection_revision_source_node_id",
        "workflow_data_selection_revision",
        ["source_node_id"],
    )
    op.create_index(
        "ix_workflow_data_selection_revision_created_by",
        "workflow_data_selection_revision",
        ["created_by"],
    )
    op.create_index(
        "ix_workflow_data_selection_revision_graph_digest",
        "workflow_data_selection_revision",
        ["graph_digest"],
    )


def downgrade() -> None:
    if not _table_exists():
        return
    op.drop_table("workflow_data_selection_revision")
