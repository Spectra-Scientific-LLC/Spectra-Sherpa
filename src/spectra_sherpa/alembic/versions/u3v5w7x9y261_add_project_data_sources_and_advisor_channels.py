"""Add project data sources and advisor channels

Revision ID: u3v5w7x9y261
Revises: t2u4v6w8x150
Create Date: 2026-05-06 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "u3v5w7x9y261"
down_revision = "t2u4v6w8x150"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    columns = sa.inspect(op.get_bind()).get_columns(table_name)
    return any(col["name"] == column_name for col in columns)


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    indexes = sa.inspect(op.get_bind()).get_indexes(table_name)
    return any(index["name"] == index_name for index in indexes)


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    if not _table_exists("project"):
        return

    if not _table_exists("project_data_source"):
        op.create_table(
            "project_data_source",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("display_name", sa.String(length=255), nullable=False),
            sa.Column("source_type", sa.String(length=50), nullable=False, server_default="external"),
            sa.Column("source_ref", sa.Text(), nullable=True),
            sa.Column("fingerprint", sa.String(length=255), nullable=True),
            sa.Column("color", sa.String(length=7), nullable=False, server_default="#3b82f6"),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", "fingerprint", name="uq_project_data_source_fingerprint"),
        )
    if not _index_exists("project_data_source", "ix_project_data_source_project_id"):
        op.create_index("ix_project_data_source_project_id", "project_data_source", ["project_id"])
    if not _index_exists("project_data_source", "ix_project_data_source_source_type"):
        op.create_index("ix_project_data_source_source_type", "project_data_source", ["source_type"])
    if not _index_exists("project_data_source", "ix_project_data_source_created_at"):
        op.create_index("ix_project_data_source_created_at", "project_data_source", ["created_at"])

    if not _table_exists("workflow"):
        return

    workflow_columns = [
        ("primary_data_source_id", sa.Column("primary_data_source_id", sa.Integer(), nullable=True)),
        ("tab_color_override", sa.Column("tab_color_override", sa.String(length=7), nullable=True)),
        ("color_source", sa.Column("color_source", sa.String(length=20), nullable=True)),
        ("created_from_template_id", sa.Column("created_from_template_id", sa.Integer(), nullable=True)),
        ("created_from_template_name", sa.Column("created_from_template_name", sa.String(length=255), nullable=True)),
        (
            "created_from_template_version",
            sa.Column("created_from_template_version", sa.String(length=100), nullable=True),
        ),
    ]
    for column_name, column in workflow_columns:
        if not _column_exists("workflow", column_name):
            op.add_column("workflow", column)

    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE workflow "
            "SET tab_color_override = tab_color "
            "WHERE tab_color IS NOT NULL AND tab_color_override IS NULL"
        )
    )
    conn.execute(
        sa.text(
            "UPDATE workflow "
            "SET color_source = CASE WHEN tab_color_override IS NOT NULL THEN 'manual' ELSE 'blank' END "
            "WHERE color_source IS NULL"
        )
    )
    if _is_sqlite():
        with op.batch_alter_table("workflow", recreate="always") as batch_op:
            batch_op.alter_column("color_source", existing_type=sa.String(length=20), nullable=False)
    else:
        op.alter_column("workflow", "color_source", existing_type=sa.String(length=20), nullable=False)
        op.create_foreign_key(
            "fk_workflow_primary_data_source_id_project_data_source",
            "workflow",
            "project_data_source",
            ["primary_data_source_id"],
            ["id"],
            ondelete="SET NULL",
        )

    if not _index_exists("workflow", "ix_workflow_primary_data_source_id"):
        op.create_index("ix_workflow_primary_data_source_id", "workflow", ["primary_data_source_id"])

    if not _table_exists("workflow_data_source"):
        op.create_table(
            "workflow_data_source",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("workflow_id", sa.Integer(), nullable=False),
            sa.Column("data_source_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=20), nullable=False, server_default="secondary"),
            sa.Column("first_seen_node_id", sa.String(length=255), nullable=True),
            sa.Column("source_node_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(["data_source_id"], ["project_data_source.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_node_id"], ["workflow_node.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("workflow_id", "data_source_id", name="uq_workflow_data_source"),
        )
    if not _index_exists("workflow_data_source", "ix_workflow_data_source_workflow_id"):
        op.create_index("ix_workflow_data_source_workflow_id", "workflow_data_source", ["workflow_id"])
    if not _index_exists("workflow_data_source", "ix_workflow_data_source_data_source_id"):
        op.create_index("ix_workflow_data_source_data_source_id", "workflow_data_source", ["data_source_id"])

    if not _table_exists("advisor_channel"):
        op.create_table(
            "advisor_channel",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("workflow_id", sa.Integer(), nullable=True),
            sa.Column("channel_type", sa.String(length=20), nullable=False, server_default="project"),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("color", sa.String(length=7), nullable=True),
            sa.Column("conversation_id", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", "workflow_id", "channel_type", name="uq_advisor_channel_scope"),
        )
    if not _index_exists("advisor_channel", "ix_advisor_channel_project_id"):
        op.create_index("ix_advisor_channel_project_id", "advisor_channel", ["project_id"])
    if not _index_exists("advisor_channel", "ix_advisor_channel_workflow_id"):
        op.create_index("ix_advisor_channel_workflow_id", "advisor_channel", ["workflow_id"])
    if not _index_exists("advisor_channel", "ix_advisor_channel_channel_type"):
        op.create_index("ix_advisor_channel_channel_type", "advisor_channel", ["channel_type"])
    if not _index_exists("advisor_channel", "ix_advisor_channel_created_at"):
        op.create_index("ix_advisor_channel_created_at", "advisor_channel", ["created_at"])


def downgrade() -> None:
    if _table_exists("advisor_channel"):
        op.drop_table("advisor_channel")
    if _table_exists("workflow_data_source"):
        op.drop_table("workflow_data_source")
    if _table_exists("workflow"):
        for index_name in ("ix_workflow_primary_data_source_id",):
            if _index_exists("workflow", index_name):
                op.drop_index(index_name, table_name="workflow")
        for column_name in (
            "created_from_template_version",
            "created_from_template_name",
            "created_from_template_id",
            "color_source",
            "tab_color_override",
            "primary_data_source_id",
        ):
            if _column_exists("workflow", column_name):
                op.drop_column("workflow", column_name)
    if _table_exists("project_data_source"):
        op.drop_table("project_data_source")
