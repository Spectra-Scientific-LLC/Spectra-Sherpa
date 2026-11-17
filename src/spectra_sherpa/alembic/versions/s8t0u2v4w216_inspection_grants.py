"""Persist scoped inspection credentials without storing bearer secrets."""

import sqlalchemy as sa
from alembic import op

revision = "s8t0u2v4w216"
down_revision = "r7s9t1u3v105"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("inspection_grant"):
        return
    op.create_table(
        "inspection_grant",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_label", sa.String(80), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False, unique=True),
        sa.Column("disclosures", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_inspection_grant_user_id", "inspection_grant", ["user_id"])
    op.create_index("ix_inspection_grant_project_id", "inspection_grant", ["project_id"])


def downgrade():
    if not sa.inspect(op.get_bind()).has_table("inspection_grant"):
        return
    if op.get_bind().scalar(sa.text("SELECT 1 FROM inspection_grant LIMIT 1")):
        raise RuntimeError("Inspection credentials must be reconciled before removing their records")
    op.drop_table("inspection_grant")
