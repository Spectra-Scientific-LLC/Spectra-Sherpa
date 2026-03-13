"""Add allow_llm_chat to user egress defaults

Revision ID: r8s0t2u4v037
Revises: q7r9s1t3u926
Create Date: 2026-03-13 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "r8s0t2u4v037"
down_revision = "q7r9s1t3u926"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    columns = sa.inspect(op.get_bind()).get_columns(table_name)
    return any(col["name"] == column_name for col in columns)


def upgrade() -> None:
    if not _column_exists("user_egress_defaults", "allow_llm_chat"):
        op.add_column(
            "user_egress_defaults",
            sa.Column("allow_llm_chat", sa.Boolean(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    if _column_exists("user_egress_defaults", "allow_llm_chat"):
        op.drop_column("user_egress_defaults", "allow_llm_chat")
