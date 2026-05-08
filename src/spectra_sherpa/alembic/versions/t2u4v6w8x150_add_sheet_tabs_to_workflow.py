"""Add sheet tabs to workflow — tab_color, sheet_order columns

Revision ID: t2u4v6w8x150
Revises: s1t3u5v7w149
Create Date: 2026-07-14 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "t2u4v6w8x150"
down_revision = "s1t3u5v7w149"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    columns = sa.inspect(op.get_bind()).get_columns(table_name)
    return any(col["name"] == column_name for col in columns)


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    indexes = sa.inspect(op.get_bind()).get_indexes(table_name)
    return any(index["name"] == index_name for index in indexes)


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    if not _table_exists("workflow"):
        return

    # Add tab_color column for sheet tab accent color (6-swatch palette only)
    if not _column_exists("workflow", "tab_color"):
        op.add_column(
            "workflow",
            sa.Column("tab_color", sa.String(7), nullable=True),
        )

    # Add sheet_order column for workbook tab ordering within a project
    if not _column_exists("workflow", "sheet_order"):
        op.add_column(
            "workflow",
            sa.Column("sheet_order", sa.Integer(), nullable=True),
        )

    # Backfill sheet_order per user/project workbook (ordered by updated_at DESC).
    # Python loop is portable across SQLite and PostgreSQL — avoids
    # Postgres-specific window functions that fail on SQLite.
    conn = op.get_bind()
    from sqlalchemy import text

    scope_rows = conn.execute(text("SELECT DISTINCT user_id, project_id FROM workflow")).fetchall()

    for user_id, project_id in scope_rows:
        if project_id is None:
            wf_rows = conn.execute(
                text(
                    "SELECT id FROM workflow " "WHERE user_id = :uid AND project_id IS NULL " "ORDER BY updated_at DESC"
                ),
                {"uid": user_id},
            ).fetchall()
        else:
            wf_rows = conn.execute(
                text(
                    "SELECT id FROM workflow " "WHERE user_id = :uid AND project_id = :pid " "ORDER BY updated_at DESC"
                ),
                {"uid": user_id, "pid": project_id},
            ).fetchall()

        for idx, (wf_id,) in enumerate(wf_rows):
            conn.execute(
                text("UPDATE workflow SET sheet_order = :so WHERE id = :wid"),
                {"so": idx, "wid": wf_id},
            )

    # Ensure empty databases and any unusual legacy rows still satisfy NOT NULL.
    conn.execute(text("UPDATE workflow SET sheet_order = 0 WHERE sheet_order IS NULL"))

    if _is_sqlite():
        with op.batch_alter_table("workflow", recreate="always") as batch_op:
            batch_op.alter_column("sheet_order", existing_type=sa.Integer(), nullable=False)
    else:
        op.alter_column("workflow", "sheet_order", existing_type=sa.Integer(), nullable=False)

    # Composite index for efficient workbook-scoped queries
    if not _index_exists("workflow", "ix_workbook_project_order"):
        op.create_index(
            "ix_workbook_project_order",
            "workflow",
            ["project_id", "sheet_order"],
        )


def downgrade() -> None:
    if not _table_exists("workflow"):
        return

    if _column_exists("workflow", "sheet_order"):
        if _index_exists("workflow", "ix_workbook_project_order"):
            op.drop_index("ix_workbook_project_order", table_name="workflow")
        op.drop_column("workflow", "sheet_order")

    if _column_exists("workflow", "tab_color"):
        op.drop_column("workflow", "tab_color")
