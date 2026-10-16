"""Bind optional laboratory reference-value context to a sample-table version."""

import sqlalchemy as sa
from alembic import op

revision = "l1m3n5o7p659"
down_revision = "k0l2m4n6o658"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("dataset_analysis_binding"):
        return
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("dataset_analysis_binding")}
    if "reference_declaration" not in columns:
        op.add_column("dataset_analysis_binding", sa.Column("reference_declaration", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("dataset_analysis_binding", "reference_declaration")
