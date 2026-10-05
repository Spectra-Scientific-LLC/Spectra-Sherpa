"""Add the closed workflow-purpose execution boundary.

Revision ID: h6e0f4c2a735
Revises: g5d9e3b1f624
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "h6e0f4c2a735"
down_revision = "g5d9e3b1f624"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return inspector.has_table(table_name) and any(
        column["name"] == column_name for column in inspector.get_columns(table_name)
    )


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if not _table_exists("workflow"):
        return
    if not _column_exists("workflow", "purpose"):
        op.add_column(
            "workflow",
            sa.Column("purpose", sa.String(length=50), nullable=True),
        )
        op.execute(sa.text("UPDATE workflow SET purpose = 'analysis'"))
        with op.batch_alter_table("workflow") as batch_op:
            batch_op.alter_column(
                "purpose",
                existing_type=sa.String(length=50),
                nullable=False,
            )
            batch_op.create_check_constraint(
                "ck_workflow_purpose",
                "purpose IN ('analysis', 'managed_candidate_authority')",
            )
            batch_op.create_index("ix_workflow_purpose", ["purpose"], unique=False)


def downgrade() -> None:
    if not _table_exists("workflow"):
        return
    if _column_exists("workflow", "purpose"):
        with op.batch_alter_table("workflow") as batch_op:
            batch_op.drop_index("ix_workflow_purpose")
            batch_op.drop_constraint("ck_workflow_purpose", type_="check")
            batch_op.drop_column("purpose")
