"""agentic_workflow_generation

Revision ID: 44c09f7e75ef
Revises: u3v5w7x9y261
Create Date: 2026-05-06 18:29:47.858442

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "44c09f7e75ef"
down_revision = "u3v5w7x9y261"
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


def _unique_constraint_exists(table_name: str, constraint_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    constraints = sa.inspect(op.get_bind()).get_unique_constraints(table_name)
    return any(constraint["name"] == constraint_name for constraint in constraints)


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    if _table_exists("workflow") and not _column_exists("workflow", "created_from_workflow_id"):
        op.add_column("workflow", sa.Column("created_from_workflow_id", sa.Integer(), nullable=True))

    if _table_exists("workflow") and not _index_exists("workflow", "ix_workflow_created_from_workflow_id"):
        op.create_index(
            op.f("ix_workflow_created_from_workflow_id"),
            "workflow",
            ["created_from_workflow_id"],
            unique=False,
        )

    if _table_exists("workflow"):
        if _is_sqlite():
            with op.batch_alter_table("workflow", recreate="always") as batch_op:
                batch_op.create_foreign_key(
                    "fk_workflow_created_from_workflow_id",
                    "workflow",
                    ["created_from_workflow_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
        else:
            op.create_foreign_key(
                "fk_workflow_created_from_workflow_id",
                "workflow",
                "workflow",
                ["created_from_workflow_id"],
                ["id"],
                ondelete="SET NULL",
            )

    if _table_exists("advisor_channel") and not _unique_constraint_exists(
        "advisor_channel", "uq_advisor_channel_conversation_id"
    ):
        if _is_sqlite():
            with op.batch_alter_table("advisor_channel", recreate="always") as batch_op:
                batch_op.create_unique_constraint(
                    "uq_advisor_channel_conversation_id",
                    ["conversation_id"],
                )
        else:
            op.create_unique_constraint(
                "uq_advisor_channel_conversation_id",
                "advisor_channel",
                ["conversation_id"],
            )


def downgrade() -> None:
    if _table_exists("advisor_channel") and _unique_constraint_exists(
        "advisor_channel", "uq_advisor_channel_conversation_id"
    ):
        if _is_sqlite():
            with op.batch_alter_table("advisor_channel", recreate="always") as batch_op:
                batch_op.drop_constraint("uq_advisor_channel_conversation_id", type_="unique")
        else:
            op.drop_constraint("uq_advisor_channel_conversation_id", "advisor_channel", type_="unique")

    if _table_exists("workflow") and _column_exists("workflow", "created_from_workflow_id"):
        if _is_sqlite():
            if _index_exists("workflow", "ix_workflow_created_from_workflow_id"):
                op.drop_index(op.f("ix_workflow_created_from_workflow_id"), table_name="workflow")
            with op.batch_alter_table("workflow", recreate="always") as batch_op:
                batch_op.drop_constraint("fk_workflow_created_from_workflow_id", type_="foreignkey")
                batch_op.drop_column("created_from_workflow_id")
        else:
            op.drop_constraint("fk_workflow_created_from_workflow_id", "workflow", type_="foreignkey")
            if _index_exists("workflow", "ix_workflow_created_from_workflow_id"):
                op.drop_index(op.f("ix_workflow_created_from_workflow_id"), table_name="workflow")
            op.drop_column("workflow", "created_from_workflow_id")
