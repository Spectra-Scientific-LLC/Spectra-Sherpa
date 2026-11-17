"""Require explicit project-summary consent; existing grants remain catalog-only."""

import sqlalchemy as sa
from alembic import op

revision = "u0v2w4x6y438"
down_revision = "t9u1v3w5x327"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("inspection_grant")}
    if "project_summaries" not in columns:
        op.add_column(
            "inspection_grant",
            sa.Column("project_summaries", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade():
    # Dropping this field loses the scope of previously issued credentials.
    if op.get_bind().scalar(sa.text("SELECT 1 FROM inspection_grant LIMIT 1")):
        raise RuntimeError("Inspection consent history requires reconciliation before downgrade")
    op.drop_column("inspection_grant", "project_summaries")
