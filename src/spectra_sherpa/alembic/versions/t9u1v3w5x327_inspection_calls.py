"""Retain local project inspection call outcomes without request/result payloads."""

import sqlalchemy as sa
from alembic import op

revision = "t9u1v3w5x327"
down_revision = "s8t0u2v4w216"
branch_labels = None
depends_on = None


def upgrade():
    if sa.inspect(op.get_bind()).has_table("inspection_call"):
        return
    op.create_table(
        "inspection_call",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("client_id", sa.String(36), sa.ForeignKey("inspection_grant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("response_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_inspection_call_client_id", "inspection_call", ["client_id"])
    op.create_index("ix_inspection_call_project_id", "inspection_call", ["project_id"])


def downgrade():
    if not sa.inspect(op.get_bind()).has_table("inspection_call"):
        return
    if op.get_bind().scalar(sa.text("SELECT 1 FROM inspection_call LIMIT 1")):
        raise RuntimeError("Inspection call history requires reconciliation before downgrade")
    op.drop_table("inspection_call")
