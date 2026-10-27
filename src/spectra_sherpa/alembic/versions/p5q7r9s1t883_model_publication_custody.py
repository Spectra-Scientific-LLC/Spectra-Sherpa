"""Retain ownership before model-file publication, including failed runs."""

import sqlalchemy as sa
from alembic import op

revision = "p5q7r9s1t883"
down_revision = "o4p6q8r0s772"
branch_labels = None
depends_on = None


def upgrade():
    if "model_publication" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "model_publication",
        sa.Column("artifact_uid", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("artifact_dir", sa.String(500), nullable=False),
    )
    op.create_index("ix_model_publication_user_id", "model_publication", ["user_id"])


def downgrade():
    # Never discard ownership of potentially private files on downgrade.
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM model_publication")).scalar()
    if count:
        raise RuntimeError("Resolve pending model publications before downgrading")
    op.drop_table("model_publication")
