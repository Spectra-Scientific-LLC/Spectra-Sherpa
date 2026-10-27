"""Fence expired execution-owned publications before reclaiming files."""

import sqlalchemy as sa
from alembic import op

revision = "r7s9t1u3v105"
down_revision = "q6r8s0t2u994"
branch_labels = None
depends_on = None


def upgrade():
    # Do not assign owners or lease deadlines to historical claims.
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("model_publication")}
    for column in (
        sa.Column("attempt_id", sa.String(36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reclaimed_at", sa.DateTime(timezone=True), nullable=True),
    ):
        if column.name not in columns:
            op.add_column("model_publication", column)
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("model_publication")}
    if "ix_model_publication_lease_expires_at" not in indexes:
        op.create_index("ix_model_publication_lease_expires_at", "model_publication", ["lease_expires_at"])


def downgrade():
    # Empty/unused upgrades remain reversible. Never discard a live execution
    # lease or tombstone to make a downgrade succeed.
    if op.get_bind().scalar(sa.text("SELECT 1 FROM model_publication WHERE attempt_id IS NOT NULL LIMIT 1")):
        raise RuntimeError("Publication ownership downgrade requires an offline custody reconciliation")
    with op.batch_alter_table("model_publication") as batch:
        batch.drop_index("ix_model_publication_lease_expires_at")
        batch.drop_column("reclaimed_at")
        batch.drop_column("lease_expires_at")
        batch.drop_column("attempt_id")
