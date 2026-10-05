"""Add explicit project archive and permanent-removal lifecycle markers.

Revision ID: v0w2x4y6z360
Revises: u0v2w4x6y359
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v0w2x4y6z360"
down_revision = "u0v2w4x6y359"
branch_labels = None
depends_on = None


def _project_schema() -> tuple[set[str], set[str]] | None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("project"):
        return None
    columns = {column["name"] for column in inspector.get_columns("project")}
    indexes = {index["name"] for index in inspector.get_indexes("project")}
    return columns, indexes


def upgrade() -> None:
    schema = _project_schema()
    if schema is None:
        return  # Reduced legacy databases may not contain projects.
    columns, indexes = schema
    if "archived_at" not in columns:
        op.add_column("project", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    if "deleted_at" not in columns:
        op.add_column("project", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    if "ix_project_archived_at" not in indexes:
        op.create_index("ix_project_archived_at", "project", ["archived_at"])
    if "ix_project_deleted_at" not in indexes:
        op.create_index("ix_project_deleted_at", "project", ["deleted_at"])


def downgrade() -> None:
    schema = _project_schema()
    if schema is None:
        return
    columns, indexes = schema
    if "archived_at" not in columns and "deleted_at" not in columns:
        return
    active_columns = [column for column in ("archived_at", "deleted_at") if column in columns]
    project = sa.table("project", *(sa.column(column) for column in active_columns))
    predicate = sa.or_(*(project.c[column].is_not(None) for column in active_columns))
    remaining = op.get_bind().execute(sa.select(sa.func.count()).select_from(project).where(predicate)).scalar_one()
    if remaining:
        raise RuntimeError("Export archived and permanently removed projects before downgrading")
    if "ix_project_deleted_at" in indexes:
        op.drop_index("ix_project_deleted_at", table_name="project")
    if "ix_project_archived_at" in indexes:
        op.drop_index("ix_project_archived_at", table_name="project")
    if "deleted_at" in columns:
        op.drop_column("project", "deleted_at")
    if "archived_at" in columns:
        op.drop_column("project", "archived_at")
