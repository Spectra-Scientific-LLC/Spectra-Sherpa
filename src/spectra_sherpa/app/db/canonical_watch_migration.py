"""Add canonical watch authority consistently to both migration chains."""

import sqlalchemy as sa
from alembic import op


def migrate_canonical_watch(*, downgrade: bool = False) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("folder_watch"):
        return
    columns = {c["name"] for c in inspector.get_columns("folder_watch")}
    if downgrade:
        if "canonical_artifact_id" not in columns:
            return
        if bind.execute(sa.text("SELECT 1 FROM folder_watch WHERE canonical_artifact_id IS NOT NULL LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade while folder watches retain canonical campaign bindings")
        with op.batch_alter_table("folder_watch", reflect_kwargs={"resolve_fks": False}) as batch:
            for fk in inspector.get_foreign_keys("folder_watch"):
                if "canonical_artifact_id" in fk["constrained_columns"] and fk.get("name"):
                    batch.drop_constraint(fk["name"], type_="foreignkey")
            batch.drop_column("canonical_artifact_id")
            if "canonical_plan_digest" in columns:
                batch.drop_column("canonical_plan_digest")
        return
    with op.batch_alter_table("folder_watch", reflect_kwargs={"resolve_fks": False}) as batch:
        if "canonical_artifact_id" not in columns:
            batch.add_column(sa.Column("canonical_artifact_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_watch_canonical_artifact",
                "canonical_project_artifact",
                ["canonical_artifact_id"],
                ["id"],
                ondelete="RESTRICT",
            )
        if "canonical_plan_digest" not in columns:
            batch.add_column(sa.Column("canonical_plan_digest", sa.String(64), nullable=True))
