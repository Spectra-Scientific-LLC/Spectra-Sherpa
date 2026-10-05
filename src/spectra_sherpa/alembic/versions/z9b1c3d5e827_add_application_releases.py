"""Add the shared Deploy application-release identity."""

import sqlalchemy as sa
from alembic import op

revision = "z9b1c3d5e827"
down_revision = "x2y4z6a8b582"
branch_labels = None
depends_on = None


def _table_exists() -> bool:
    return sa.inspect(op.get_bind()).has_table("application_release")


def upgrade() -> None:
    # Test and first-boot paths may create the metadata tables before running
    # Alembic. In that case the model already supplied the complete schema.
    if _table_exists():
        return
    op.create_table(
        "application_release",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("handle", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("workflow_id", sa.Integer(), nullable=False),
        sa.Column("workflow_version_id", sa.Integer(), nullable=True),
        sa.Column("source_run_id", sa.Integer(), nullable=True),
        sa.Column("model_artifact_uid", sa.String(length=36), nullable=True),
        sa.Column("canonical_artifact_id", sa.Integer(), nullable=True),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=24), server_default="released", nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("package_digest", sa.String(length=64), nullable=True),
        sa.Column("package_schema_version", sa.String(length=128), nullable=True),
        sa.Column("readiness", sa.JSON(), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["canonical_artifact_id"], ["canonical_project_artifact.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_run_id"], ["execution_run.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_id"], ["workflow.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_version_id"], ["workflow_version.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_artifact_id", name="uq_application_release_canonical_artifact"),
        sa.UniqueConstraint("handle"),
        sa.UniqueConstraint("model_artifact_uid", name="uq_application_release_model_artifact"),
    )
    op.create_index("ix_application_release_handle", "application_release", ["handle"], unique=False)
    op.create_index("ix_application_release_user_id", "application_release", ["user_id"], unique=False)
    op.create_index("ix_application_release_project_id", "application_release", ["project_id"], unique=False)
    op.create_index("ix_application_release_workflow_id", "application_release", ["workflow_id"], unique=False)
    op.create_index("ix_application_release_source_run_id", "application_release", ["source_run_id"], unique=False)
    op.create_index(
        "ix_application_release_model_artifact_uid", "application_release", ["model_artifact_uid"], unique=False
    )
    op.create_index(
        "ix_application_release_canonical_artifact_id", "application_release", ["canonical_artifact_id"], unique=False
    )
    op.create_index(
        "ix_application_release_project_state", "application_release", ["project_id", "state"], unique=False
    )


def downgrade() -> None:
    if not _table_exists():
        return
    op.drop_index("ix_application_release_project_state", table_name="application_release")
    op.drop_index("ix_application_release_canonical_artifact_id", table_name="application_release")
    op.drop_index("ix_application_release_model_artifact_uid", table_name="application_release")
    op.drop_index("ix_application_release_source_run_id", table_name="application_release")
    op.drop_index("ix_application_release_workflow_id", table_name="application_release")
    op.drop_index("ix_application_release_project_id", table_name="application_release")
    op.drop_index("ix_application_release_user_id", table_name="application_release")
    op.drop_index("ix_application_release_handle", table_name="application_release")
    op.drop_table("application_release")
