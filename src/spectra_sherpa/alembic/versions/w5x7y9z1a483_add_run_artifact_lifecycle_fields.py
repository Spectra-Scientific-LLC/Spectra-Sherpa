"""Add run/artifact lifecycle metadata

Revision ID: w5x7y9z1a483
Revises: v4w6x8y0z372
Create Date: 2026-05-20 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "w5x7y9z1a483"
down_revision = "v4w6x8y0z372"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(col["name"] == column_name for col in sa.inspect(op.get_bind()).get_columns(table_name))


def upgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    if _table_exists("model_artifact"):
        if not _column_exists("model_artifact", "source_run_id"):
            op.add_column("model_artifact", sa.Column("source_run_id", sa.Integer(), nullable=True))
            op.create_index("ix_model_artifact_source_run_id", "model_artifact", ["source_run_id"])
            if not sqlite:
                op.create_foreign_key(
                    "fk_model_artifact_source_run_id_execution_run",
                    "model_artifact",
                    "execution_run",
                    ["source_run_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
        if not _column_exists("model_artifact", "training_dataset_id"):
            op.add_column("model_artifact", sa.Column("training_dataset_id", sa.Integer(), nullable=True))
            op.create_index("ix_model_artifact_training_dataset_id", "model_artifact", ["training_dataset_id"])
            if not sqlite:
                op.create_foreign_key(
                    "fk_model_artifact_training_dataset_id_experiment",
                    "model_artifact",
                    "experiment",
                    ["training_dataset_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
        if not _column_exists("model_artifact", "display_name"):
            op.add_column("model_artifact", sa.Column("display_name", sa.String(length=255), nullable=True))
            op.execute("UPDATE model_artifact SET display_name = name WHERE display_name IS NULL")
        if not _column_exists("model_artifact", "is_deploy_ready"):
            op.add_column(
                "model_artifact",
                sa.Column("is_deploy_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
            )
            if op.get_bind().dialect.name != "sqlite":
                op.alter_column("model_artifact", "is_deploy_ready", server_default=None)
        if not _column_exists("model_artifact", "tags"):
            op.add_column("model_artifact", sa.Column("tags", sa.JSON(), nullable=True))

    if _table_exists("execution_run"):
        if not _column_exists("execution_run", "run_kind"):
            op.add_column(
                "execution_run",
                sa.Column("run_kind", sa.String(length=50), nullable=False, server_default="training"),
            )
            if op.get_bind().dialect.name != "sqlite":
                op.alter_column("execution_run", "run_kind", server_default=None)
        if not _column_exists("execution_run", "applied_artifact_uids"):
            op.add_column("execution_run", sa.Column("applied_artifact_uids", sa.JSON(), nullable=True))


def downgrade() -> None:
    sqlite = op.get_bind().dialect.name == "sqlite"
    if _table_exists("execution_run"):
        if _column_exists("execution_run", "applied_artifact_uids"):
            op.drop_column("execution_run", "applied_artifact_uids")
        if _column_exists("execution_run", "run_kind"):
            op.drop_column("execution_run", "run_kind")

    if _table_exists("model_artifact"):
        if _column_exists("model_artifact", "tags"):
            op.drop_column("model_artifact", "tags")
        if _column_exists("model_artifact", "is_deploy_ready"):
            op.drop_column("model_artifact", "is_deploy_ready")
        if _column_exists("model_artifact", "display_name"):
            op.drop_column("model_artifact", "display_name")
        if _column_exists("model_artifact", "training_dataset_id"):
            if not sqlite:
                op.drop_constraint(
                    "fk_model_artifact_training_dataset_id_experiment",
                    "model_artifact",
                    type_="foreignkey",
                )
            op.drop_index("ix_model_artifact_training_dataset_id", table_name="model_artifact")
            op.drop_column("model_artifact", "training_dataset_id")
        if _column_exists("model_artifact", "source_run_id"):
            if not sqlite:
                op.drop_constraint(
                    "fk_model_artifact_source_run_id_execution_run",
                    "model_artifact",
                    type_="foreignkey",
                )
            op.drop_index("ix_model_artifact_source_run_id", table_name="model_artifact")
            op.drop_column("model_artifact", "source_run_id")
