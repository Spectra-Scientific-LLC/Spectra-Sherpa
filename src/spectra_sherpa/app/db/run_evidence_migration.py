"""Shared additive schema step for OSS and server migration chains."""

import sqlalchemy as sa
from alembic import op


def migrate_run_evidence(*, downgrade: bool = False) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("execution_run") or not inspector.has_table("model_artifact"):
        return  # Legacy auth-only bootstrap has no scientific tables yet.
    naming = {"fk": "fk_%(table_name)s_%(column_0_name)s"}
    target_action = "SET NULL" if downgrade else "RESTRICT"
    changes = []
    for column, target in (("source_run_id", "execution_run"), ("workflow_version_id", "workflow_version")):
        fk = next(
            (fk for fk in inspector.get_foreign_keys("model_artifact") if fk["constrained_columns"] == [column]),
            None,
        )
        if fk and (fk.get("options", {}).get("ondelete") or "").upper() == target_action:
            continue
        changes.append((column, target, fk))
    if changes:
        with op.batch_alter_table("model_artifact", naming_convention=naming) as batch:
            for column, target, fk in changes:
                if fk:
                    batch.drop_constraint(fk.get("name") or f"fk_model_artifact_{column}", type_="foreignkey")
                batch.create_foreign_key(
                    f"fk_model_artifact_{column}", target, [column], ["id"], ondelete=target_action
                )

    columns = {column["name"]: column for column in sa.inspect(bind).get_columns("execution_run")}
    with op.batch_alter_table("execution_run") as batch:
        if downgrade:
            if "evidence_completeness" in columns:
                batch.drop_column("evidence_completeness")
        elif "evidence_completeness" not in columns:
            batch.add_column(sa.Column("evidence_completeness", sa.JSON(), nullable=True))
        batch.alter_column("run_kind", existing_type=sa.String(50), server_default="training" if downgrade else "other")
    if not downgrade:
        op.execute(sa.text("UPDATE execution_run SET run_kind = 'batch_inference' WHERE source_type = 'folder_watch'"))

    job_columns = {column["name"] for column in sa.inspect(bind).get_columns("background_job")}
    if not downgrade and "execution_run_id" not in job_columns:
        with op.batch_alter_table("background_job") as batch:
            batch.add_column(sa.Column("execution_run_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_background_job_execution_run_id",
                "execution_run",
                ["execution_run_id"],
                ["id"],
                ondelete="SET NULL",
            )
            batch.create_index("ix_background_job_execution_run_id", ["execution_run_id"])
    elif downgrade and "execution_run_id" in job_columns:
        with op.batch_alter_table("background_job", naming_convention=naming) as batch:
            fk = next(
                fk
                for fk in sa.inspect(bind).get_foreign_keys("background_job")
                if fk["constrained_columns"] == ["execution_run_id"]
            )
            batch.drop_constraint(fk.get("name") or "fk_background_job_execution_run_id", type_="foreignkey")
            batch.drop_index("ix_background_job_execution_run_id")
            batch.drop_column("execution_run_id")
