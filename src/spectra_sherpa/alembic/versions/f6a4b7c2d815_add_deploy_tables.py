"""Add deploy tables (folder_watch, batch_prediction) and labels/source columns on execution_run.

Revision ID: f6a4b7c2d815
Revises: e5b3c8d1f204
Create Date: 2026-02-11 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f6a4b7c2d815"
down_revision = "e5b3c8d1f204"
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
    # 1. Add columns to execution_run
    if not _column_exists("execution_run", "labels"):
        op.add_column(
            "execution_run",
            sa.Column("labels", sa.JSON(), nullable=True, server_default="[]"),
        )
    if not _column_exists("execution_run", "source_type"):
        op.add_column(
            "execution_run",
            sa.Column("source_type", sa.String(50), nullable=True, server_default="manual"),
        )
    if not _column_exists("execution_run", "source_metadata"):
        op.add_column(
            "execution_run",
            sa.Column("source_metadata", sa.JSON(), nullable=True),
        )

    # 2. Create folder_watch table
    if not _table_exists("folder_watch"):
        op.create_table(
            "folder_watch",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False, index=True),
            sa.Column(
                "workflow_id",
                sa.Integer(),
                sa.ForeignKey("workflow.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("folder_path", sa.String(1000), nullable=False),
            sa.Column("file_pattern", sa.String(255), nullable=False, server_default="*"),
            sa.Column("poll_interval_sec", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("processed_files", sa.JSON(), nullable=True),
            sa.Column("last_poll_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )

    # 3. Create batch_prediction table
    if not _table_exists("batch_prediction"):
        op.create_table(
            "batch_prediction",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "run_id",
                sa.Integer(),
                sa.ForeignKey("execution_run.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("file_name", sa.String(500), nullable=False),
            sa.Column("file_path", sa.String(1000), nullable=False),
            sa.Column("status", sa.String(50), nullable=False),
            sa.Column("results", sa.JSON(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("processing_time_ms", sa.Integer(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
        )


def downgrade() -> None:
    op.drop_table("batch_prediction")
    op.drop_table("folder_watch")
    op.drop_column("execution_run", "source_metadata")
    op.drop_column("execution_run", "source_type")
    op.drop_column("execution_run", "labels")
