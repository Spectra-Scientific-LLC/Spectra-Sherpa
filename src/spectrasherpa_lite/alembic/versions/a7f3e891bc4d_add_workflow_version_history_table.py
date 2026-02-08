"""Add workflow version history table

Revision ID: a7f3e891bc4d
Revises:
Create Date: 2026-01-15 10:30:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7f3e891bc4d'
down_revision = None
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    indexes = sa.inspect(op.get_bind()).get_indexes(table_name)
    return any(idx["name"] == index_name for idx in indexes)


def _ensure_user_table() -> None:
    if _table_exists("user"):
        return

    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("api_key_hash", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    if not _index_exists("user", "ix_user_username"):
        op.create_index("ix_user_username", "user", ["username"], unique=False)


def _ensure_workflow_table() -> None:
    if _table_exists("workflow"):
        return

    op.create_table(
        "workflow",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="draft"),
        sa.Column("canvas_state", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("last_executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    if not _index_exists("workflow", "ix_workflow_user_id"):
        op.create_index("ix_workflow_user_id", "workflow", ["user_id"], unique=False)
    if not _index_exists("workflow", "ix_workflow_status"):
        op.create_index("ix_workflow_status", "workflow", ["status"], unique=False)
    if not _index_exists("workflow", "ix_workflow_created_at"):
        op.create_index("ix_workflow_created_at", "workflow", ["created_at"], unique=False)


def _ensure_workflow_node_table() -> None:
    if _table_exists("workflow_node"):
        return

    op.create_table(
        "workflow_node",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("node_type", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("position_x", sa.Float(), nullable=True),
        sa.Column("position_y", sa.Float(), nullable=True),
        sa.Column("execution_order", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    if not _index_exists("workflow_node", "ix_workflow_node_workflow_id"):
        op.create_index(
            "ix_workflow_node_workflow_id", "workflow_node", ["workflow_id"], unique=False
        )
    if not _index_exists("workflow_node", "ix_workflow_node_node_type"):
        op.create_index(
            "ix_workflow_node_node_type", "workflow_node", ["node_type"], unique=False
        )


def upgrade() -> None:
    # Bootstraps core tables when migrating a fresh database with no prior schema.
    _ensure_user_table()
    _ensure_workflow_table()
    _ensure_workflow_node_table()

    if not _table_exists("workflow_version"):
        op.create_table(
            "workflow_version",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("workflow_id", sa.Integer(), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column("created_by", sa.Integer(), nullable=False),
            sa.Column("change_description", sa.Text(), nullable=True),
            sa.Column("snapshot", sa.JSON(), nullable=False),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"]),
            sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _index_exists("workflow_version", op.f("ix_workflow_version_created_at")):
        op.create_index(
            op.f("ix_workflow_version_created_at"),
            "workflow_version",
            ["created_at"],
            unique=False,
        )
    if not _index_exists("workflow_version", op.f("ix_workflow_version_created_by")):
        op.create_index(
            op.f("ix_workflow_version_created_by"),
            "workflow_version",
            ["created_by"],
            unique=False,
        )
    if not _index_exists("workflow_version", op.f("ix_workflow_version_workflow_id")):
        op.create_index(
            op.f("ix_workflow_version_workflow_id"),
            "workflow_version",
            ["workflow_id"],
            unique=False,
        )


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_workflow_version_workflow_id'), table_name='workflow_version')
    op.drop_index(op.f('ix_workflow_version_created_by'), table_name='workflow_version')
    op.drop_index(op.f('ix_workflow_version_created_at'), table_name='workflow_version')
    op.drop_table('workflow_version')
    # ### end Alembic commands ###
