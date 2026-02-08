"""Add workflow tags and folders

Revision ID: b8f4d9a2cd5e
Revises: a7f3e891bc4d
Create Date: 2026-01-15 11:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8f4d9a2cd5e'
down_revision = 'a7f3e891bc4d'
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


def _fk_exists(
    table_name: str,
    fk_name: str,
    constrained_columns: list[str] | None = None,
    referred_table: str | None = None,
) -> bool:
    if not _table_exists(table_name):
        return False
    fks = sa.inspect(op.get_bind()).get_foreign_keys(table_name)
    for fk in fks:
        if fk.get("name") == fk_name:
            return True
        if (
            constrained_columns is not None
            and referred_table is not None
            and fk.get("constrained_columns") == constrained_columns
            and fk.get("referred_table") == referred_table
        ):
            return True
    return False


def upgrade() -> None:
    if not _table_exists("workflow_folder"):
        op.create_table(
            "workflow_folder",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("parent_id", sa.Integer(), nullable=True),
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
            sa.ForeignKeyConstraint(["parent_id"], ["workflow_folder.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _index_exists("workflow_folder", op.f("ix_workflow_folder_parent_id")):
        op.create_index(
            op.f("ix_workflow_folder_parent_id"),
            "workflow_folder",
            ["parent_id"],
            unique=False,
        )
    if not _index_exists("workflow_folder", op.f("ix_workflow_folder_user_id")):
        op.create_index(
            op.f("ix_workflow_folder_user_id"),
            "workflow_folder",
            ["user_id"],
            unique=False,
        )

    if not _table_exists("workflow_tag"):
        op.create_table(
            "workflow_tag",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("color", sa.String(length=7), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    if not _index_exists("workflow_tag", op.f("ix_workflow_tag_user_id")):
        op.create_index(
            op.f("ix_workflow_tag_user_id"),
            "workflow_tag",
            ["user_id"],
            unique=False,
        )

    if not _table_exists("workflow_tag_association"):
        op.create_table(
            "workflow_tag_association",
            sa.Column("workflow_id", sa.Integer(), nullable=False),
            sa.Column("tag_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["tag_id"], ["workflow_tag.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("workflow_id", "tag_id"),
        )

    if _table_exists("workflow"):
        if not _column_exists("workflow", "folder_id"):
            op.add_column("workflow", sa.Column("folder_id", sa.Integer(), nullable=True))
        if not _index_exists("workflow", op.f("ix_workflow_folder_id")):
            op.create_index(
                op.f("ix_workflow_folder_id"),
                "workflow",
                ["folder_id"],
                unique=False,
            )
        if _table_exists("workflow_folder") and not _fk_exists(
            "workflow",
            "fk_workflow_folder_id",
            constrained_columns=["folder_id"],
            referred_table="workflow_folder",
        ):
            bind = op.get_bind()
            if bind.dialect.name == "sqlite":
                with op.batch_alter_table("workflow", recreate="auto") as batch_op:
                    batch_op.create_foreign_key(
                        "fk_workflow_folder_id",
                        "workflow_folder",
                        ["folder_id"],
                        ["id"],
                        ondelete="SET NULL",
                    )
            else:
                op.create_foreign_key(
                    "fk_workflow_folder_id",
                    "workflow",
                    "workflow_folder",
                    ["folder_id"],
                    ["id"],
                    ondelete="SET NULL",
                )


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint('fk_workflow_folder_id', 'workflow', type_='foreignkey')
    op.drop_index(op.f('ix_workflow_folder_id'), table_name='workflow')
    op.drop_column('workflow', 'folder_id')
    op.drop_table('workflow_tag_association')
    op.drop_index(op.f('ix_workflow_tag_user_id'), table_name='workflow_tag')
    op.drop_table('workflow_tag')
    op.drop_index(op.f('ix_workflow_folder_user_id'), table_name='workflow_folder')
    op.drop_index(op.f('ix_workflow_folder_parent_id'), table_name='workflow_folder')
    op.drop_table('workflow_folder')
    # ### end Alembic commands ###
