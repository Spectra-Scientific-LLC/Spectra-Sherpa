"""Retain instrument QC observations and maintenance history."""

import sqlalchemy as sa
from alembic import op

revision = "e4f6g8h0i232"
down_revision = "d3e5f7g9h131"
branch_labels = None
depends_on = None


def upgrade():
    # create_all already installs this table and its indexes for fresh and
    # untracked profiles. Preserve any retained records on that path.
    if sa.inspect(op.get_bind()).has_table("instrument_qc_record"):
        return
    op.create_table(
        "instrument_qc_record",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("watch_id", sa.Integer(), sa.ForeignKey("folder_watch.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("watch_id", "sequence", name="uq_watch_qc_sequence"),
        sa.UniqueConstraint("watch_id", "event_id", name="uq_watch_qc_event"),
    )
    op.create_index("ix_instrument_qc_record_watch_id", "instrument_qc_record", ["watch_id"])
    op.create_index("ix_instrument_qc_record_user_id", "instrument_qc_record", ["user_id"])


def downgrade():
    op.drop_table("instrument_qc_record")
