"""Retain whether a workflow sheet uses current or bundled example data.

Revision ID: b1c3d5e7f929
Revises: a0b1c2d3e4f5
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b1c3d5e7f929"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None


def _table_exists() -> bool:
    return sa.inspect(op.get_bind()).has_table("workflow")


def _column_exists() -> bool:
    return _table_exists() and any(
        column["name"] == "data_origin" for column in sa.inspect(op.get_bind()).get_columns("workflow")
    )


def _constraint_exists() -> bool:
    return _table_exists() and any(
        constraint.get("name") == "ck_workflow_data_origin"
        for constraint in sa.inspect(op.get_bind()).get_check_constraints("workflow")
    )


def upgrade() -> None:
    if not _table_exists():
        return
    if not _column_exists():
        op.add_column("workflow", sa.Column("data_origin", sa.String(length=20), nullable=True))
    if not _constraint_exists():
        with op.batch_alter_table("workflow") as batch_op:
            batch_op.create_check_constraint(
                "ck_workflow_data_origin",
                "data_origin IS NULL OR data_origin IN ('current', 'example')",
            )


def downgrade() -> None:
    if not _column_exists():
        return
    if _constraint_exists():
        with op.batch_alter_table("workflow") as batch_op:
            batch_op.drop_constraint("ck_workflow_data_origin", type_="check")
    op.drop_column("workflow", "data_origin")
