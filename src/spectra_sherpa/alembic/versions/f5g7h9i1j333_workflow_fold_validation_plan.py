"""Retain a sheet's campaign cross-validation plan."""

import sqlalchemy as sa
from alembic import op

revision = "f5g7h9i1j333"
down_revision = "e4f6g8h0i232"
branch_labels = None
depends_on = None


def upgrade():
    # create_all already installs this column for fresh and untracked profiles.
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("workflow"):
        return
    columns = {column["name"] for column in inspector.get_columns("workflow")}
    if "fold_validation_plan" in columns:
        return
    with op.batch_alter_table("workflow") as batch:
        batch.add_column(sa.Column("fold_validation_plan", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("workflow") as batch:
        batch.drop_column("fold_validation_plan")
