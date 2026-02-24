"""Add custom_algo table for user-defined algorithm nodes.

Revision ID: k1f9g3h7i360
Revises: j0e8f2g6h259
Create Date: 2026-02-24 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "k1f9g3h7i360"
down_revision = "j0e8f2g6h259"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _table_exists("custom_algo"):
        op.create_table(
            "custom_algo",
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
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("slug", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("code", sa.Text(), nullable=False),
            sa.Column("mode", sa.String(20), nullable=False, server_default="simple"),
            sa.Column("icon", sa.String(10), nullable=False, server_default="\U0001f9ea"),
            sa.Column("node_type", sa.String(255), nullable=False, unique=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
        )


def downgrade() -> None:
    if _table_exists("custom_algo"):
        op.drop_table("custom_algo")
