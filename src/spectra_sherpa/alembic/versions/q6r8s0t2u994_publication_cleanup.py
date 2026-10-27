"""Record terminal temporary-publication cleanup independently of age."""

import sqlalchemy as sa
from alembic import op

revision = "q6r8s0t2u994"
down_revision = "p5q7r9s1t883"
branch_labels = None
depends_on = None


def upgrade():
    # Fresh installations create the current ORM schema before Alembic runs.
    if "cleanup_requested" not in {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns("model_publication")
    }:
        op.add_column(
            "model_publication", sa.Column("cleanup_requested", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade():
    op.drop_column("model_publication", "cleanup_requested")
