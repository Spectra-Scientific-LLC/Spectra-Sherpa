"""Record current-project dataset and workflow choices without rewriting evidence."""

import sqlalchemy as sa
from alembic import op

revision = "j9k1l3m5n657"
down_revision = "i8j0k2l4m656"
branch_labels = None
depends_on = None


def upgrade():
    if not sa.inspect(op.get_bind()).has_table("project_choice_event"):
        op.create_table(
            "project_choice_event",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(length=16), nullable=False),
            sa.Column("experiment_id", sa.Integer(), sa.ForeignKey("experiment.id", ondelete="SET NULL")),
            sa.Column("dataset_view_id", sa.Integer(), sa.ForeignKey("dataset_view.id", ondelete="SET NULL")),
            sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("workflow.id", ondelete="SET NULL")),
            sa.Column("selected_experiment_id", sa.Integer()),
            sa.Column("selected_dataset_view_id", sa.Integer()),
            sa.Column("selected_workflow_id", sa.Integer()),
            sa.Column("selected_name", sa.String(length=255), nullable=False),
            sa.Column("selected_digest", sa.String(length=64)),
            sa.Column("selected_definition", sa.JSON()),
            sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint(
                "(kind = 'dataset' AND workflow_id IS NULL) OR "
                "(kind = 'workflow' AND experiment_id IS NULL AND dataset_view_id IS NULL)",
                name="ck_project_choice_event_target",
            ),
            sa.CheckConstraint(
                "(kind = 'dataset' AND selected_experiment_id IS NOT NULL AND selected_workflow_id IS NULL) OR "
                "(kind = 'workflow' AND selected_workflow_id IS NOT NULL "
                "AND selected_experiment_id IS NULL AND selected_dataset_view_id IS NULL)",
                name="ck_project_choice_event_snapshot",
            ),
        )
    indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("project_choice_event")}
    if "ix_project_choice_event_current" not in indexes:
        op.create_index(
            "ix_project_choice_event_current",
            "project_choice_event",
            ["project_id", "user_id", "kind", "id"],
        )


def downgrade():
    if sa.inspect(op.get_bind()).has_table("project_choice_event"):
        op.drop_index("ix_project_choice_event_current", table_name="project_choice_event")
        op.drop_table("project_choice_event")
