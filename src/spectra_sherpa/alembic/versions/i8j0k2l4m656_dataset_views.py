"""Persist named My Dataset views separately from source experiments."""

import sqlalchemy as sa
from alembic import op

revision = "i8j0k2l4m656"
down_revision = "h7i9j1k3l545"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("dataset_view"):
        op.create_table(
            "dataset_view",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
            sa.Column(
                "experiment_id", sa.Integer(), sa.ForeignKey("experiment.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("name_key", sa.String(length=120), nullable=False),
            sa.Column("selection", sa.JSON(), nullable=False),
            sa.Column("selection_sha256", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("project_id", "experiment_id", "name_key", name="uq_dataset_view_name"),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("dataset_view")}
    if "ix_dataset_view_project_id" not in indexes:
        op.create_index("ix_dataset_view_project_id", "dataset_view", ["project_id"])
    if "ix_dataset_view_experiment_id" not in indexes:
        op.create_index("ix_dataset_view_experiment_id", "dataset_view", ["experiment_id"])


def downgrade():
    if not sa.inspect(op.get_bind()).has_table("dataset_view"):
        return
    op.drop_index("ix_dataset_view_experiment_id", table_name="dataset_view")
    op.drop_index("ix_dataset_view_project_id", table_name="dataset_view")
    op.drop_table("dataset_view")
