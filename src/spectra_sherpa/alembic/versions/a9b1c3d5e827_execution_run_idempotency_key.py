"""Add idempotency_key + lookup index to execution_run

Revision ID: a9b1c3d5e827
Revises: z8a0b2c4d716
Create Date: 2026-05-21 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a9b1c3d5e827"
down_revision = "z8a0b2c4d716"
branch_labels = None
depends_on = None

IDEMPOTENCY_INDEX_NAME = "ix_execution_run_idempotency_lookup"


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(col["name"] == column_name for col in sa.inspect(op.get_bind()).get_columns(table_name))


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(idx["name"] == index_name for idx in sa.inspect(op.get_bind()).get_indexes(table_name))


def upgrade() -> None:
    if not _table_exists("execution_run"):
        return

    if not _column_exists("execution_run", "idempotency_key"):
        with op.batch_alter_table("execution_run") as batch_op:
            batch_op.add_column(sa.Column("idempotency_key", sa.String(length=64), nullable=True))

    if not _index_exists("execution_run", IDEMPOTENCY_INDEX_NAME):
        op.create_index(
            IDEMPOTENCY_INDEX_NAME,
            "execution_run",
            ["user_id", "workflow_id", "idempotency_key"],
            unique=False,
        )


def downgrade() -> None:
    if _index_exists("execution_run", IDEMPOTENCY_INDEX_NAME):
        op.drop_index(IDEMPOTENCY_INDEX_NAME, table_name="execution_run")
    if _column_exists("execution_run", "idempotency_key"):
        with op.batch_alter_table("execution_run") as batch_op:
            batch_op.drop_column("idempotency_key")
