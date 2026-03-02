"""Add login tracking columns to user table

Revision ID: m3h5i7j9k582
Revises: l2g4h6i8j471
Create Date: 2026-03-01 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "m3h5i7j9k582"
down_revision = "l2g4h6i8j471"
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
    if not _column_exists("user", "last_login_at"):
        op.add_column(
            "user",
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not _column_exists("user", "login_count"):
        op.add_column(
            "user",
            sa.Column("login_count", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    op.drop_column("user", "login_count")
    op.drop_column("user", "last_login_at")
