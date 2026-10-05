"""Add durable canonical project artifact custody.

Revision ID: e3b7c1a9d402
Revises: d2e4f6g8h260
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e3b7c1a9d402"
down_revision = "d2e4f6g8h260"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    if _table_exists("canonical_project_artifact"):
        return
    op.create_table(
        "canonical_project_artifact",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "workflow_id",
            sa.Integer(),
            sa.ForeignKey("workflow.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("artifact_digest", sa.String(64), nullable=False),
        sa.Column("capsule_digest", sa.String(64), nullable=False),
        sa.Column("application_plan_digest", sa.String(64), nullable=False),
        sa.Column("package_sha256", sa.String(64), nullable=False),
        sa.Column("artifact_dir", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "artifact_digest", name="uq_canonical_project_artifact"),
    )
    op.create_index("ix_canonical_project_artifact_user_id", "canonical_project_artifact", ["user_id"])
    op.create_index("ix_canonical_project_artifact_project_id", "canonical_project_artifact", ["project_id"])
    op.create_index("ix_canonical_project_artifact_artifact_digest", "canonical_project_artifact", ["artifact_digest"])


def downgrade() -> None:
    if _table_exists("canonical_project_artifact"):
        op.drop_table("canonical_project_artifact")
