"""Add exact scientific asset identity to folder watches.

Revision ID: i8j0k2l4m826
Revises: h6e0f4c2a735
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "i8j0k2l4m826"
down_revision = "h6e0f4c2a735"
branch_labels = None
depends_on = None


def _has_folder_watch_column(column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("folder_watch"):
        return False
    return any(column["name"] == column_name for column in inspector.get_columns("folder_watch"))


def upgrade() -> None:
    # Sparse historical bootstrap fixtures can legitimately reach this head
    # without the optional deploy tables. A current create_all database already
    # has the column; only alter a retained historical table that needs it.
    if not sa.inspect(op.get_bind()).has_table("folder_watch"):
        return
    if _has_folder_watch_column("asset_id"):
        return
    with op.batch_alter_table("folder_watch") as batch_op:
        batch_op.add_column(sa.Column("asset_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    if not _has_folder_watch_column("asset_id"):
        return
    with op.batch_alter_table("folder_watch") as batch_op:
        batch_op.drop_column("asset_id")
