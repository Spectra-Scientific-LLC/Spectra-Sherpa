"""Bind explicitly selected uncertainty evidence to a folder watch."""

import sqlalchemy as sa
from alembic import op

revision = "c2d4e6f8g030"
down_revision = "b1c3d5e7f929"
branch_labels = None
depends_on = None


def upgrade():
    # Fresh/untracked profiles are bootstrapped from the current ORM before
    # Alembic runs. Add only columns absent from older tracked profiles.
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("folder_watch"):
        return
    existing = {column["name"] for column in inspector.get_columns("folder_watch")}
    if "uncertainty_record" not in existing:
        op.add_column("folder_watch", sa.Column("uncertainty_record", sa.JSON(), nullable=True))
    if "uncertainty_population" not in existing:
        op.add_column("folder_watch", sa.Column("uncertainty_population", sa.String(2000), nullable=True))


def downgrade():
    op.drop_column("folder_watch", "uncertainty_population")
    op.drop_column("folder_watch", "uncertainty_record")
