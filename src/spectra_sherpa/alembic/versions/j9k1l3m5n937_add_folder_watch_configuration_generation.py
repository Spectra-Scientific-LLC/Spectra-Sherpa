"""Add folder-watch polling configuration generation and active lease.

Revision ID: j9k1l3m5n937
Revises: i8j0k2l4m826
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "j9k1l3m5n937"
down_revision = "i8j0k2l4m826"
branch_labels = None
depends_on = None


def _has_folder_watch_column(column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("folder_watch"):
        return False
    return any(column["name"] == column_name for column in inspector.get_columns("folder_watch"))


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("folder_watch"):
        return
    with op.batch_alter_table("folder_watch") as batch_op:
        if not _has_folder_watch_column("configuration_generation"):
            batch_op.add_column(
                sa.Column(
                    "configuration_generation",
                    sa.Integer(),
                    nullable=False,
                    server_default="0",
                )
            )
        if not _has_folder_watch_column("active_poll_token"):
            batch_op.add_column(sa.Column("active_poll_token", sa.String(length=64), nullable=True))
        if not _has_folder_watch_column("active_poll_claimed_at"):
            batch_op.add_column(sa.Column("active_poll_claimed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("folder_watch"):
        return
    with op.batch_alter_table("folder_watch") as batch_op:
        if _has_folder_watch_column("active_poll_claimed_at"):
            batch_op.drop_column("active_poll_claimed_at")
        if _has_folder_watch_column("active_poll_token"):
            batch_op.drop_column("active_poll_token")
        if _has_folder_watch_column("configuration_generation"):
            batch_op.drop_column("configuration_generation")
