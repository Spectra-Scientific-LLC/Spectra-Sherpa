"""Keep retained result access separately consented and off for existing grants."""

import sqlalchemy as sa
from alembic import op

revision = "v1w3x5y7z549"
down_revision = "u0v2w4x6y438"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("inspection_grant")}
    if "retained_results" not in columns:
        op.add_column(
            "inspection_grant", sa.Column("retained_results", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT 1 FROM inspection_grant LIMIT 1")):
        raise RuntimeError("Inspection consent history requires reconciliation before downgrade")
    op.drop_column("inspection_grant", "retained_results")
