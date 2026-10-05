"""Bind canonical project custody to its admitted application graph.

Revision ID: f4c8d2a0e513
Revises: e3b7c1a9d402
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f4c8d2a0e513"
down_revision = "e3b7c1a9d402"
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
    # Existing e3b imports have no independently persisted application-graph
    # baseline.  The empty value deliberately blocks their execution rather
    # than retroactively trusting a graph that may already have been edited.
    # Re-importing the sealed package creates a complete custody record.
    if not _column_exists("canonical_project_artifact", "application_integrity_hash"):
        op.add_column(
            "canonical_project_artifact",
            sa.Column(
                "application_integrity_hash",
                sa.String(length=64),
                nullable=False,
                server_default="",
            ),
        )
        if op.get_bind().dialect.name != "sqlite":
            op.alter_column("canonical_project_artifact", "application_integrity_hash", server_default=None)


def downgrade() -> None:
    if _column_exists("canonical_project_artifact", "application_integrity_hash"):
        op.drop_column("canonical_project_artifact", "application_integrity_hash")
