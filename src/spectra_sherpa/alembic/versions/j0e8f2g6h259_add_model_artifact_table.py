"""Add model_artifact table and model_id columns to execution_run/batch_prediction.

Revision ID: j0e8f2g6h259
Revises: i9d7e1f5g148
Create Date: 2026-02-23 12:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "j0e8f2g6h259"
down_revision = "i9d7e1f5g148"
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    columns = sa.inspect(op.get_bind()).get_columns(table_name)
    return any(col["name"] == column_name for col in columns)


def upgrade() -> None:
    # 1. Create model_artifact table
    if not _table_exists("model_artifact"):
        op.create_table(
            "model_artifact",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("artifact_uid", sa.String(36), unique=True, nullable=False, index=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("user.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "project_id",
                sa.Integer(),
                sa.ForeignKey("project.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column(
                "workflow_id",
                sa.Integer(),
                sa.ForeignKey("workflow.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column(
                "workflow_version_id",
                sa.Integer(),
                sa.ForeignKey("workflow_version.id", ondelete="SET NULL"),
                nullable=True,
                index=True,
            ),
            sa.Column("node_id", sa.String(255), nullable=False),
            sa.Column("model_type", sa.String(50), nullable=False, index=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            # Storage
            sa.Column("artifact_dir", sa.String(500), nullable=False),
            sa.Column("integrity_hash", sa.String(64), nullable=False),
            # Quick-inspect metadata
            sa.Column("n_features", sa.Integer(), nullable=False),
            sa.Column("n_components", sa.Integer(), nullable=True),
            sa.Column("classes_json", sa.Text(), nullable=True),
            sa.Column("feature_axis_json", sa.Text(), nullable=True),
            sa.Column("metrics_json", sa.Text(), nullable=True),
            # Provenance
            sa.Column("training_data_hash", sa.String(64), nullable=True),
            sa.Column("preprocessing_summary", sa.Text(), nullable=True),
            # Lifecycle
            sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                index=True,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
            ),
        )

    # 2. Add model_ids column to execution_run
    if not _column_exists("execution_run", "model_ids"):
        op.add_column(
            "execution_run",
            sa.Column("model_ids", sa.JSON(), nullable=True),
        )

    # 3. Add model_id column to batch_prediction
    if not _column_exists("batch_prediction", "model_id"):
        op.add_column(
            "batch_prediction",
            sa.Column("model_id", sa.String(64), nullable=True, index=True),
        )


def downgrade() -> None:
    if _column_exists("batch_prediction", "model_id"):
        op.drop_column("batch_prediction", "model_id")
    if _column_exists("execution_run", "model_ids"):
        op.drop_column("execution_run", "model_ids")
    if _table_exists("model_artifact"):
        op.drop_table("model_artifact")
