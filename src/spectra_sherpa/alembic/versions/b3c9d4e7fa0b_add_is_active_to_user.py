"""Add is_active column to user table

Revision ID: b3c9d4e7fa0b
Revises: a2b8c3d6ef9a
Create Date: 2026-02-07 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b3c9d4e7fa0b"
down_revision = "a2b8c3d6ef9a"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    columns = sa.inspect(op.get_bind()).get_columns(table_name)
    return any(col["name"] == column_name for col in columns)


def upgrade() -> None:
    if _table_exists("user") and not _column_exists("user", "is_active"):
        op.add_column(
            "user",
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        )


def downgrade() -> None:
    op.drop_column("user", "is_active")
