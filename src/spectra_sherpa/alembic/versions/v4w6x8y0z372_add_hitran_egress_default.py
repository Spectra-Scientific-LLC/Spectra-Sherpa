"""Add HITRAN egress default

Revision ID: v4w6x8y0z372
Revises: a17025aud001
Create Date: 2026-05-18 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "v4w6x8y0z372"
down_revision = "a17025aud001"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    columns = sa.inspect(op.get_bind()).get_columns(table_name)
    return any(col["name"] == column_name for col in columns)


def upgrade() -> None:
    if not _table_exists("user_egress_defaults"):
        return
    if not _column_exists("user_egress_defaults", "allow_hitran_queries"):
        op.add_column(
            "user_egress_defaults",
            sa.Column("allow_hitran_queries", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        if op.get_bind().dialect.name != "sqlite":
            op.alter_column("user_egress_defaults", "allow_hitran_queries", server_default=None)


def downgrade() -> None:
    if _column_exists("user_egress_defaults", "allow_hitran_queries"):
        op.drop_column("user_egress_defaults", "allow_hitran_queries")
