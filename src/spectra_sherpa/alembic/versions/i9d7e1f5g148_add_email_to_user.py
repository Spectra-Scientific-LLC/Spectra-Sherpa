"""Add email column to user table

Revision ID: i9d7e1f5g148
Revises: h8c6d0e4f037
Create Date: 2026-02-15 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "i9d7e1f5g148"
down_revision = "h8c6d0e4f037"
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
    if _table_exists("user") and not _column_exists("user", "email"):
        op.add_column(
            "user",
            sa.Column("email", sa.String(255), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("user", "email")
