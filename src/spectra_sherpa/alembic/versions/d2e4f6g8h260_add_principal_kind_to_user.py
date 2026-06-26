"""Add principal_kind to user principals

Revision ID: d2e4f6g8h260
Revises: c1d3e5f7g149
Create Date: 2026-06-25 10:05:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d2e4f6g8h260"
down_revision = "c1d3e5f7g149"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(col["name"] == column_name for col in sa.inspect(op.get_bind()).get_columns(table_name))


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(index.get("name") == index_name for index in sa.inspect(op.get_bind()).get_indexes(table_name))


def upgrade() -> None:
    if not _table_exists("user"):
        return

    if not _column_exists("user", "principal_kind"):
        op.add_column(
            "user",
            sa.Column(
                "principal_kind",
                sa.String(length=32),
                nullable=False,
                server_default="human",
            ),
        )

    if not _index_exists("user", "ix_user_principal_kind"):
        op.create_index("ix_user_principal_kind", "user", ["principal_kind"])


def downgrade() -> None:
    if not _table_exists("user"):
        return
    if _index_exists("user", "ix_user_principal_kind"):
        op.drop_index("ix_user_principal_kind", table_name="user")
    if _column_exists("user", "principal_kind"):
        op.drop_column("user", "principal_kind")
