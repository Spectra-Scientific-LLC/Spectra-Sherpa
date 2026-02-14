"""Add workflow technique and sample_type columns

Revision ID: d4a2f7b9e103
Revises: c6d1e9f2ab45
Create Date: 2026-02-11 20:00:00.000000

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d4a2f7b9e103"
down_revision = "c6d1e9f2ab45"
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
    if not _column_exists("workflow", "technique"):
        op.add_column("workflow", sa.Column("technique", sa.String(50), nullable=True))
    if not _column_exists("workflow", "sample_type"):
        op.add_column("workflow", sa.Column("sample_type", sa.String(100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workflow") as batch_op:
        batch_op.drop_column("sample_type")
        batch_op.drop_column("technique")
