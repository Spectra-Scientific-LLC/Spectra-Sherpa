"""Constrain execution_run.run_kind values

Revision ID: x6y8z0a2b594
Revises: w5x7y9z1a483
Create Date: 2026-05-20 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "x6y8z0a2b594"
down_revision = "w5x7y9z1a483"
branch_labels = None
depends_on = None

RUN_KIND_CHECK = "run_kind IN ('training', 'batch_inference', 'data', 'other')"
RUN_KIND_CHECK_NAME = "ck_execution_run_run_kind"


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(col["name"] == column_name for col in sa.inspect(op.get_bind()).get_columns(table_name))


def _check_exists(table_name: str, check_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(check.get("name") == check_name for check in sa.inspect(op.get_bind()).get_check_constraints(table_name))


def upgrade() -> None:
    if not _column_exists("execution_run", "run_kind"):
        return

    op.execute(
        "UPDATE execution_run "
        "SET run_kind = 'other' "
        "WHERE run_kind NOT IN ('training', 'batch_inference', 'data', 'other')"
    )
    if _check_exists("execution_run", RUN_KIND_CHECK_NAME):
        return

    with op.batch_alter_table("execution_run") as batch_op:
        batch_op.create_check_constraint(RUN_KIND_CHECK_NAME, RUN_KIND_CHECK)


def downgrade() -> None:
    if not _check_exists("execution_run", RUN_KIND_CHECK_NAME):
        return
    with op.batch_alter_table("execution_run") as batch_op:
        batch_op.drop_constraint(RUN_KIND_CHECK_NAME, type_="check")
