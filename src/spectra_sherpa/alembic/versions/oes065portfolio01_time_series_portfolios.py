"""v0.6.5 immutable OES portfolios."""

import sqlalchemy as sa
from alembic import op

revision = "oes065portfolio01"
down_revision = "n3o5p7q9r661"
branch_labels = None
depends_on = None


def upgrade():
    # Fresh installations create current model tables before upgrading Alembic.
    if sa.inspect(op.get_bind()).has_table("time_series_portfolio"):
        return
    op.create_table(
        "time_series_portfolio",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("name_key", sa.String(120), nullable=False),
        sa.Column("selection", sa.JSON(), nullable=False),
        sa.Column("selection_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "name_key", name="uq_time_series_portfolio_name"),
    )
    op.create_index("ix_time_series_portfolio_project_id", "time_series_portfolio", ["project_id"])


def downgrade():
    op.drop_table("time_series_portfolio")
