"""Add last_active column to user table

Revision ID: n4i6j8k0l693
Revises: m3h5i7j9k582
Create Date: 2026-03-02 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "n4i6j8k0l693"
down_revision = "m3h5i7j9k582"
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
    if not _table_exists("user"):
        return
    if not _column_exists("user", "last_active"):
        op.add_column(
            "user",
            sa.Column("last_active", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("user", "last_active")
