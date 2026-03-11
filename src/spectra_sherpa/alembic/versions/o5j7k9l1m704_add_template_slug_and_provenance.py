"""Add template slug and workflow provenance fields

Revision ID: o5j7k9l1m704
Revises: n4i6j8k0l693
Create Date: 2026-03-08 10:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "o5j7k9l1m704"
down_revision = "n4i6j8k0l693"
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
    # Add slug to workflow_template
    if _table_exists("workflow_template") and not _column_exists("workflow_template", "slug"):
        op.add_column(
            "workflow_template",
            sa.Column("slug", sa.String(length=100), nullable=True),
        )
        # Backfill slug from name. Use a Python loop so ensure_workflow_templates()
        # can match by slug on next startup and update rather than duplicate.
        conn = op.get_bind()
        import re

        rows = conn.execute(sa.text("SELECT id, name FROM workflow_template WHERE slug IS NULL")).fetchall()
        for row_id, name in rows:
            # Produce a compact slug: lowercase, strip non-alpha, collapse to underscores
            slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
            conn.execute(
                sa.text("UPDATE workflow_template SET slug = :slug WHERE id = :id"),
                {"slug": slug, "id": row_id},
            )
        # Now make it NOT NULL and unique
        with op.batch_alter_table("workflow_template") as batch_op:
            batch_op.alter_column("slug", nullable=False)
            batch_op.create_unique_constraint("uq_workflow_template_slug", ["slug"])
            batch_op.create_index("ix_workflow_template_slug", ["slug"], unique=True)

    # Add provenance fields to workflow (use batch mode for SQLite compatibility)
    if _table_exists("workflow"):
        needs_template_id = not _column_exists("workflow", "source_template_id")
        needs_template_slug = not _column_exists("workflow", "source_template_slug")
        if needs_template_id or needs_template_slug:
            with op.batch_alter_table("workflow") as batch_op:
                if needs_template_id:
                    batch_op.add_column(
                        sa.Column(
                            "source_template_id",
                            sa.Integer(),
                            sa.ForeignKey(
                                "workflow_template.id",
                                name="fk_workflow_source_template_id",
                                ondelete="SET NULL",
                            ),
                            nullable=True,
                        ),
                    )
                if needs_template_slug:
                    batch_op.add_column(
                        sa.Column("source_template_slug", sa.String(length=100), nullable=True),
                    )
            if needs_template_id:
                op.create_index(
                    "ix_workflow_source_template_id",
                    "workflow",
                    ["source_template_id"],
                )


def downgrade() -> None:
    if _table_exists("workflow"):
        has_slug = _column_exists("workflow", "source_template_slug")
        has_id = _column_exists("workflow", "source_template_id")
        if has_id:
            op.drop_index("ix_workflow_source_template_id", table_name="workflow")
        if has_slug or has_id:
            with op.batch_alter_table("workflow") as batch_op:
                if has_slug:
                    batch_op.drop_column("source_template_slug")
                if has_id:
                    batch_op.drop_column("source_template_id")
    if _table_exists("workflow_template") and _column_exists("workflow_template", "slug"):
        with op.batch_alter_table("workflow_template") as batch_op:
            batch_op.drop_index("ix_workflow_template_slug")
            batch_op.drop_constraint("uq_workflow_template_slug")
        op.drop_column("workflow_template", "slug")
