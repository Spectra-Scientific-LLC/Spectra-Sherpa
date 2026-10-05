"""Bind model rows to the complete training-dataset scientific identity.

Revision ID: m2n4o6p8q371
Revises: l1m3n5o7p159
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "m2n4o6p8q371"
down_revision = "l1m3n5o7p159"
branch_labels = None
depends_on = None


def _has_column(column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("model_artifact"):
        return False
    return any(column["name"] == column_name for column in inspector.get_columns("model_artifact"))


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("model_artifact") or _has_column("training_scientific_digest"):
        return
    with op.batch_alter_table("model_artifact") as batch_op:
        batch_op.add_column(sa.Column("training_scientific_digest", sa.String(length=64), nullable=True))


def downgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("model_artifact") or not _has_column("training_scientific_digest"):
        return
    with op.batch_alter_table("model_artifact") as batch_op:
        batch_op.drop_column("training_scientific_digest")
