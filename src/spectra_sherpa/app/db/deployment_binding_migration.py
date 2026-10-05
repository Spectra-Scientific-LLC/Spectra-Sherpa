"""Bind operational watches without inventing historical model approval."""

import logging

import sqlalchemy as sa
from alembic import op

logger = logging.getLogger(__name__)


def migrate_deployment_binding(*, downgrade: bool = False) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("folder_watch"):
        return
    columns = {column["name"] for column in inspector.get_columns("folder_watch")}
    additions = (
        ("artifact_uid", sa.String(36), "model_artifact", "artifact_uid"),
        ("workflow_version_id", sa.Integer(), "workflow_version", "id"),
    )
    if downgrade:
        if "artifact_uid" not in columns:
            return
        if bind.execute(sa.text("SELECT 1 FROM folder_watch WHERE artifact_uid IS NOT NULL LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade while folder watches retain exact artifact bindings")
        foreign_keys = inspector.get_foreign_keys("folder_watch")
        with op.batch_alter_table("folder_watch", reflect_kwargs={"resolve_fks": False}) as batch:
            for column, _, _, _ in additions:
                if column in columns:
                    for constraint in foreign_keys:
                        if column in constraint["constrained_columns"] and constraint.get("name"):
                            batch.drop_constraint(constraint["name"], type_="foreignkey")
                    batch.drop_column(column)
        return
    missing = [item for item in additions if item[0] not in columns]
    if missing:
        with op.batch_alter_table("folder_watch", reflect_kwargs={"resolve_fks": False}) as batch:
            for column, datatype, table, target in missing:
                batch.add_column(sa.Column(column, datatype, nullable=True))
                batch.create_foreign_key(f"fk_folder_watch_{column}", table, [column], [target], ondelete="RESTRICT")
    # All existing watches are unbound on first upgrade. Repair independently
    # of column creation so either chain can enforce this invariant idempotently.
    result = bind.execute(
        sa.text(
            "UPDATE folder_watch SET is_enabled=false, active_poll_token=NULL, "
            "active_poll_claimed_at=NULL, configuration_generation=configuration_generation+1, "
            "last_error='Select an exact deploy-ready artifact before enabling this watch' "
            "WHERE (artifact_uid IS NULL OR workflow_version_id IS NULL) "
            "AND (is_enabled=true OR active_poll_token IS NOT NULL OR active_poll_claimed_at IS NOT NULL "
            "OR last_error IS NULL OR last_error != 'Select an exact deploy-ready artifact before enabling this watch')"
        )
    )
    logger.info("Disabled/reconciled %d unbound folder watches", result.rowcount)
