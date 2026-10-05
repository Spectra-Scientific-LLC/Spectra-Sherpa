"""Retain every analytical qualification assessment and review decision."""

import sqlalchemy as sa
from alembic import op

revision = "d3e5f7g9h131"
down_revision = "c2d4e6f8g030"
branch_labels = None
depends_on = None


def upgrade():
    # create_all already installs this table and its indexes for fresh and
    # untracked profiles. Preserve any retained records on that path.
    if sa.inspect(op.get_bind()).has_table("analytical_qualification_record"):
        return
    op.create_table(
        "analytical_qualification_record",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("workflow.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "canonical_artifact_id",
            sa.Integer(),
            sa.ForeignKey("canonical_project_artifact.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("record_digest", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("parent_digest", sa.String(64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "workflow_id", "record_digest", name="uq_qualification_workflow_digest"),
    )
    op.create_index("ix_analytical_qualification_record_user_id", "analytical_qualification_record", ["user_id"])
    op.create_index(
        "ix_analytical_qualification_record_workflow_id", "analytical_qualification_record", ["workflow_id"]
    )


def downgrade():
    op.drop_table("analytical_qualification_record")
