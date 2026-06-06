"""Relax execution_run.status CHECK to include lifecycle values

Revision ID: b0c2d4e6f938
Revises: a9b1c3d5e827
Create Date: 2026-05-21 00:00:00.000000

Hotfix: PR #158's status CHECK constraint (``ck_execution_run_status``)
narrowed the allowlist to terminal-only values. The batch route
(``deploy.py``) and the folder-watch service pre-create ExecutionRun
rows in ``status="running"`` then update them on completion — those
inserts now fail with IntegrityError on a freshly-migrated DB.

This migration drops the strict constraint and recreates it with the
lifecycle values (``pending`` / ``running``) included. Pre-existing
rows that may have been written under the old narrow constraint are
untouched.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b0c2d4e6f938"
down_revision = "a9b1c3d5e827"
branch_labels = None
depends_on = None

STATUS_CHECK_NAME = "ck_execution_run_status"
STATUS_CHECK_RELAXED = "status IN ('pending', 'running', 'completed', 'partial', " "'error', 'failed', 'cancelled')"
STATUS_CHECK_STRICT_PRIOR = "status IN ('completed', 'partial', 'error', 'failed', 'cancelled')"


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _check_exists(table_name: str, check_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(check.get("name") == check_name for check in sa.inspect(op.get_bind()).get_check_constraints(table_name))


def upgrade() -> None:
    if not _table_exists("execution_run"):
        return

    # Drop the strict constraint if present (it may not be present on
    # older databases that never ran z8a0b2c4d716, or on a freshly built
    # DB where the model now declares the relaxed form directly).
    if _check_exists("execution_run", STATUS_CHECK_NAME):
        with op.batch_alter_table("execution_run") as batch_op:
            batch_op.drop_constraint(STATUS_CHECK_NAME, type_="check")

    # Recreate with the relaxed allowlist.
    with op.batch_alter_table("execution_run") as batch_op:
        batch_op.create_check_constraint(STATUS_CHECK_NAME, STATUS_CHECK_RELAXED)


def downgrade() -> None:
    if not _table_exists("execution_run"):
        return
    if _check_exists("execution_run", STATUS_CHECK_NAME):
        with op.batch_alter_table("execution_run") as batch_op:
            batch_op.drop_constraint(STATUS_CHECK_NAME, type_="check")
    # Coerce any lifecycle rows that would violate the strict prior
    # constraint into a terminal status so the strict re-add succeeds.
    op.execute("UPDATE execution_run SET status = 'failed' WHERE status IN ('pending', 'running')")
    with op.batch_alter_table("execution_run") as batch_op:
        batch_op.create_check_constraint(STATUS_CHECK_NAME, STATUS_CHECK_STRICT_PRIOR)
