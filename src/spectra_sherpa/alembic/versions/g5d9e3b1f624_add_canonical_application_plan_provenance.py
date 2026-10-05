"""Retain sealed canonical application-plan provenance under project custody.

Revision ID: g5d9e3b1f624
Revises: f4c8d2a0e513
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "g5d9e3b1f624"
down_revision = "f4c8d2a0e513"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(col["name"] == column_name for col in sa.inspect(op.get_bind()).get_columns(table_name))


def upgrade() -> None:
    if not _table_exists("canonical_project_artifact"):
        return
    # Existing imports predate durable plan provenance.  An empty payload is
    # deliberately unreadable through the closed resolver, preserving the
    # fail-closed re-import requirement rather than inventing historic data.
    if not _column_exists("canonical_project_artifact", "application_plan_payload"):
        op.add_column(
            "canonical_project_artifact",
            sa.Column("application_plan_payload", sa.JSON(), nullable=False, server_default="{}"),
        )
        if op.get_bind().dialect.name != "sqlite":
            op.alter_column("canonical_project_artifact", "application_plan_payload", server_default=None)


def downgrade() -> None:
    if _column_exists("canonical_project_artifact", "application_plan_payload"):
        op.drop_column("canonical_project_artifact", "application_plan_payload")
