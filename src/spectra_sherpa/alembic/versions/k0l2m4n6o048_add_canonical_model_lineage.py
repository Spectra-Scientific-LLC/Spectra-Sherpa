"""Add canonical full-refit origin and lineage identities to saved models.

Revision ID: k0l2m4n6o048
Revises: j9k1l3m5n937
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "k0l2m4n6o048"
down_revision = "j9k1l3m5n937"
branch_labels = None
depends_on = None


def _has_model_column(column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("model_artifact"):
        return False
    return any(column["name"] == column_name for column in inspector.get_columns("model_artifact"))


def _has_origin_index() -> bool:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("model_artifact"):
        return False
    return any(
        index["name"] == "ix_model_artifact_artifact_origin" for index in inspector.get_indexes("model_artifact")
    )


def upgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("model_artifact"):
        return
    with op.batch_alter_table("model_artifact") as batch_op:
        if not _has_model_column("artifact_origin"):
            batch_op.add_column(sa.Column("artifact_origin", sa.String(length=96), nullable=True))
        if not _has_model_column("canonical_lineage_digest"):
            batch_op.add_column(sa.Column("canonical_lineage_digest", sa.String(length=64), nullable=True))
        if not _has_model_column("validation_evidence_digest"):
            batch_op.add_column(sa.Column("validation_evidence_digest", sa.String(length=64), nullable=True))
    if not _has_origin_index():
        op.create_index("ix_model_artifact_artifact_origin", "model_artifact", ["artifact_origin"], unique=False)


def downgrade() -> None:
    if not sa.inspect(op.get_bind()).has_table("model_artifact"):
        return
    if _has_origin_index():
        op.drop_index("ix_model_artifact_artifact_origin", table_name="model_artifact")
    with op.batch_alter_table("model_artifact") as batch_op:
        if _has_model_column("validation_evidence_digest"):
            batch_op.drop_column("validation_evidence_digest")
        if _has_model_column("canonical_lineage_digest"):
            batch_op.drop_column("canonical_lineage_digest")
        if _has_model_column("artifact_origin"):
            batch_op.drop_column("artifact_origin")
