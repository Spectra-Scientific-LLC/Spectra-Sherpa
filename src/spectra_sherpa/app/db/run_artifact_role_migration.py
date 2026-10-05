"""Add explicit artifact roles to saved runs and backfill historical rows."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

ROLE_COLUMNS = (
    "produced_artifact_uids",
    "attempted_artifact_uids",
    "succeeded_artifact_uids",
)


def _columns() -> set[str]:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("execution_run"):
        return set()
    return {str(column["name"]) for column in sa.inspect(bind).get_columns("execution_run")}


def migrate_run_artifact_roles(*, downgrade: bool = False) -> None:
    columns = _columns()
    if not columns:
        return
    if downgrade:
        for name in reversed(ROLE_COLUMNS):
            if name in columns:
                op.drop_column("execution_run", name)
        return

    for name in ROLE_COLUMNS:
        if name not in columns:
            op.add_column("execution_run", sa.Column(name, sa.JSON(), nullable=True))

    bind = op.get_bind()
    # Keep this migration column-local. Historical schemas can omit tables
    # referenced by execution_run foreign keys, so full reflection would fail
    # before these additive columns can be backfilled.
    available_columns = columns | set(ROLE_COLUMNS)
    column_types: dict[str, sa.types.TypeEngine] = {
        "id": sa.Integer(),
        "run_kind": sa.String(),
        "model_ids": sa.JSON(),
        "applied_artifact_uids": sa.JSON(),
        **{name: sa.JSON() for name in ROLE_COLUMNS},
    }
    table = sa.table(
        "execution_run",
        *(sa.column(name, column_type) for name, column_type in column_types.items() if name in available_columns),
    )
    for row in bind.execute(sa.select(table)).mappings():
        values: dict[str, list] = {}
        if row["produced_artifact_uids"] is None:
            values["produced_artifact_uids"] = list(row["model_ids"] or []) if row["run_kind"] == "training" else []
        if row["attempted_artifact_uids"] is None:
            values["attempted_artifact_uids"] = (
                list(row["applied_artifact_uids"] or []) if row["run_kind"] == "batch_inference" else []
            )
        if row["succeeded_artifact_uids"] is None:
            values["succeeded_artifact_uids"] = (
                list(row["model_ids"] or []) if row["run_kind"] == "batch_inference" else []
            )
        if values:
            bind.execute(table.update().where(table.c.id == row["id"]).values(**values))
