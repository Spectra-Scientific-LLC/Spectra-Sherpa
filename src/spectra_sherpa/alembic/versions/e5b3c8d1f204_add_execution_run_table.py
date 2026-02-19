"""Add execution_run table

Revision ID: e5b3c8d1f204
Revises: d4a2f7b9e103
Create Date: 2026-02-11 23:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e5b3c8d1f204"
down_revision = "d4a2f7b9e103"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _table_exists("execution_run"):
        op.create_table(
            "execution_run",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column(
                "workflow_id",
                sa.Integer,
                sa.ForeignKey("workflow.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "workflow_version_id",
                sa.Integer,
                sa.ForeignKey("workflow_version.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "user_id",
                sa.Integer,
                sa.ForeignKey("user.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("status", sa.String(50), nullable=False),
            sa.Column("params_snapshot", sa.JSON, nullable=False),
            sa.Column("results_summary", sa.JSON, nullable=False),
            sa.Column("diagnostics", sa.JSON, nullable=True),
            sa.Column("node_statuses", sa.JSON, nullable=True),
            sa.Column("error", sa.Text, nullable=True),
            sa.Column("integrity_hash", sa.String(64), nullable=True),
            sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
            sa.Column("notes", sa.Text, nullable=True),
        )


def downgrade() -> None:
    op.drop_table("execution_run")
