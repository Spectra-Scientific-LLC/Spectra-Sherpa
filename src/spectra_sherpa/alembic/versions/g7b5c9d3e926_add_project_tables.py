"""Add project and project_version tables, add project_id FK to experiment and workflow.

Revision ID: g7b5c9d3e926
Revises: f6a4b7c2d815
Create Date: 2026-02-12 12:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "g7b5c9d3e926"
down_revision = "f6a4b7c2d815"
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


def _ensure_experiment_table() -> None:
    """Bootstrap experiment table if it doesn't exist yet.

    Handles existing DBs where the root migration was applied before
    the experiment bootstrap was added.
    """
    if _table_exists("experiment"):
        return
    op.create_table(
        "experiment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata_path", sa.String(length=500), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def upgrade() -> None:
    # Ensure experiment table exists (may be missing on DBs where
    # root migration ran before the bootstrap was expanded).
    _ensure_experiment_table()

    # 1. Create project table (guard for DBs where create_all() already ran)
    if not _table_exists("project"):
        op.create_table(
            "project",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "user_id", sa.Integer(), sa.ForeignKey("user.id"), nullable=False, index=True
            ),
            sa.Column(
                "parent_id",
                sa.Integer(),
                sa.ForeignKey("project.id", ondelete="CASCADE"),
                nullable=True,
                index=True,
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.Column("technique", sa.String(50), nullable=True),
            sa.Column("sample_type", sa.String(100), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                index=True,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
        )

    # 2. Create project_version table
    if not _table_exists("project_version"):
        op.create_table(
            "project_version",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "project_id",
                sa.Integer(),
                sa.ForeignKey("project.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                index=True,
            ),
            sa.Column(
                "created_by",
                sa.Integer(),
                sa.ForeignKey("user.id"),
                nullable=False,
                index=True,
            ),
            sa.Column("change_description", sa.Text(), nullable=True),
            sa.Column("snapshot", sa.JSON(), nullable=False),
            sa.Column("include_raw_data", sa.Boolean(), nullable=False, server_default="0"),
        )

    # 3. Add project_id column to experiment
    # (plain add_column — FK enforced by ORM, not DB constraint on SQLite)
    if not _column_exists("experiment", "project_id"):
        op.add_column(
            "experiment",
            sa.Column("project_id", sa.Integer(), nullable=True),
        )
    if not _index_exists("experiment", "ix_experiment_project_id"):
        op.create_index("ix_experiment_project_id", "experiment", ["project_id"])

    # 4. Add project_id column to workflow
    if not _column_exists("workflow", "project_id"):
        op.add_column(
            "workflow",
            sa.Column("project_id", sa.Integer(), nullable=True),
        )
    if not _index_exists("workflow", "ix_workflow_project_id"):
        op.create_index("ix_workflow_project_id", "workflow", ["project_id"])


def downgrade() -> None:
    if _index_exists("workflow", "ix_workflow_project_id"):
        op.drop_index("ix_workflow_project_id", "workflow")
    if _column_exists("workflow", "project_id"):
        op.drop_column("workflow", "project_id")
    if _index_exists("experiment", "ix_experiment_project_id"):
        op.drop_index("ix_experiment_project_id", "experiment")
    if _column_exists("experiment", "project_id"):
        op.drop_column("experiment", "project_id")
    if _table_exists("project_version"):
        op.drop_table("project_version")
    if _table_exists("project"):
        op.drop_table("project")
