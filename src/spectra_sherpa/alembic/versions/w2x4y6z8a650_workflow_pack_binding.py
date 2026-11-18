"""Retain exact workflow pack bindings without backfilling historical identities."""

import sqlalchemy as sa
from alembic import op

revision = "w2x4y6z8a650"
down_revision = "v1w3x5y7z549"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("workflow")}
    if "pack_binding" not in columns:
        op.add_column("workflow", sa.Column("pack_binding", sa.JSON(), nullable=True))


def downgrade() -> None:
    if op.get_bind().execute(sa.text("SELECT 1 FROM workflow WHERE pack_binding IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Cannot discard retained workflow pack bindings")
    with op.batch_alter_table("workflow") as batch:
        batch.drop_column("pack_binding")
