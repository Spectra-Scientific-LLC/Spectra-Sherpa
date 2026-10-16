"""Persist append-only PCA sample review decisions."""

import sqlalchemy as sa
from alembic import op

revision = "k0l2m4n6o658"
down_revision = "j9k1l3m5n657"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("sample_review_revision"):
        return
    op.create_table(
        "sample_review_revision",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("workflow.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pca_node_id", sa.String(255), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("execution_run.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("sample_ids", sa.JSON(), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("graph_digest", sa.String(64), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.UniqueConstraint("workflow_id", "pca_node_id", "revision", name="uq_sample_review_revision"),
    )
    op.create_index("ix_sample_review_revision_workflow_id", "sample_review_revision", ["workflow_id"])


def downgrade():
    op.drop_index("ix_sample_review_revision_workflow_id", table_name="sample_review_revision")
    op.drop_table("sample_review_revision")
