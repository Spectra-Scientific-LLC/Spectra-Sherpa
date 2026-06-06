"""Constrain execution_run.status values

Revision ID: z8a0b2c4d716
Revises: y7z9a1b3c605
Create Date: 2026-05-21 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "z8a0b2c4d716"
down_revision = "y7z9a1b3c605"
branch_labels = None
depends_on = None

STATUS_CHECK = "status IN ('completed', 'partial', 'error', 'failed', 'cancelled')"
STATUS_CHECK_NAME = "ck_execution_run_status"


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
    if not _column_exists("execution_run", "status"):
        return

    # Normalize any historical rows that escape the allowlist. ``success``
    # has appeared in older code paths; the rest of the allowlist already
    # matches existing callers (completed / partial / error / failed).
    # Anything else gets coerced to ``error`` so the constraint can apply
    # without dropping rows.
    op.execute("UPDATE execution_run SET status = 'completed' WHERE status = 'success'")
    op.execute(
        "UPDATE execution_run "
        "SET status = 'error' "
        "WHERE status NOT IN ('completed', 'partial', 'error', 'failed', 'cancelled')"
    )

    if _check_exists("execution_run", STATUS_CHECK_NAME):
        return

    with op.batch_alter_table("execution_run") as batch_op:
        batch_op.create_check_constraint(STATUS_CHECK_NAME, STATUS_CHECK)


def downgrade() -> None:
    if not _check_exists("execution_run", STATUS_CHECK_NAME):
        return
    with op.batch_alter_table("execution_run") as batch_op:
        batch_op.drop_constraint(STATUS_CHECK_NAME, type_="check")
