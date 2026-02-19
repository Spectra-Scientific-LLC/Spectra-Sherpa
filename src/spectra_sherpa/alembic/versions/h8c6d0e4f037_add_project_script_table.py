"""Add project_script table.

Revision ID: h8c6d0e4f037
Revises: g7b5c9d3e926
Create Date: 2026-02-13 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "h8c6d0e4f037"
down_revision = "g7b5c9d3e926"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _table_exists("project_script"):
        op.create_table(
            "project_script",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "project_id",
                sa.Integer(),
                sa.ForeignKey("project.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("user.id"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "source_workflow_id",
                sa.Integer(),
                sa.ForeignKey("workflow.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("language", sa.String(20), nullable=False, server_default="python"),
            sa.Column("code", sa.Text(), nullable=False),
            sa.Column("priority", sa.Float(), nullable=False, server_default="50.0"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                index=True,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
        )


def downgrade() -> None:
    if _table_exists("project_script"):
        op.drop_table("project_script")
