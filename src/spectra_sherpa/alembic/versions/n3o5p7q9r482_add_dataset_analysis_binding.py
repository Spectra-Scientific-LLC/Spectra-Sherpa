"""Add durable portable-CSV analysis bindings.

Revision ID: n3o5p7q9r482
Revises: m2n4o6p8q371
Create Date: 2026-09-01 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "n3o5p7q9r482"
down_revision = "m2n4o6p8q371"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def upgrade() -> None:
    # Fresh OSS databases are bootstrapped from Base.metadata before the
    # migration chain is stamped. Existing databases reach this revision with
    # no table. Supporting both paths keeps create-all and upgrade ownership
    # explicit without weakening either path to an unqualified IF NOT EXISTS.
    if _table_exists("dataset_analysis_binding"):
        return
    op.create_table(
        "dataset_analysis_binding",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_file_id", sa.Integer(), nullable=False),
        sa.Column("sample_table_file_id", sa.Integer(), nullable=False),
        sa.Column("selected_target", sa.String(length=255), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "target_type IN ('continuous', 'categorical')",
            name="ck_dataset_analysis_binding_target_type",
        ),
        sa.ForeignKeyConstraint(["sample_table_file_id"], ["experiment_file.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_file_id"], ["experiment_file.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_file_id", name="uq_dataset_analysis_binding_source_file"),
    )
    op.create_index(
        op.f("ix_dataset_analysis_binding_sample_table_file_id"),
        "dataset_analysis_binding",
        ["sample_table_file_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_dataset_analysis_binding_source_file_id"),
        "dataset_analysis_binding",
        ["source_file_id"],
        unique=False,
    )


def downgrade() -> None:
    if not _table_exists("dataset_analysis_binding"):
        return
    op.drop_index(op.f("ix_dataset_analysis_binding_source_file_id"), table_name="dataset_analysis_binding")
    op.drop_index(op.f("ix_dataset_analysis_binding_sample_table_file_id"), table_name="dataset_analysis_binding")
    op.drop_table("dataset_analysis_binding")
