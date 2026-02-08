"""Add workflow integrity_hash column

Revision ID: a2b8c3d6ef9a
Revises: f1a7b2c5de8f
Create Date: 2026-02-05 14:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a2b8c3d6ef9a'
down_revision = 'f1a7b2c5de8f'
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    columns = sa.inspect(op.get_bind()).get_columns(table_name)
    return any(col["name"] == column_name for col in columns)


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    indexes = sa.inspect(op.get_bind()).get_indexes(table_name)
    return any(idx["name"] == index_name for idx in indexes)


def upgrade() -> None:
    if _table_exists("workflow") and not _column_exists("workflow", "integrity_hash"):
        op.add_column("workflow", sa.Column("integrity_hash", sa.String(64), nullable=True))
    if _table_exists("workflow") and not _index_exists("workflow", "ix_workflow_integrity_hash"):
        op.create_index("ix_workflow_integrity_hash", "workflow", ["integrity_hash"])


def downgrade() -> None:
    op.drop_index('ix_workflow_integrity_hash', table_name='workflow')
    op.drop_column('workflow', 'integrity_hash')
