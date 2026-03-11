"""Add missing project_id FK constraints to experiment and workflow.

These columns were added as plain integer columns (no DB-level FK) in
g7b5c9d3e926_add_project_tables.py.  The ORM models now declare
ForeignKey("project.id", ondelete="SET NULL"), but tracked databases
that upgraded through that migration never got the DB constraint.

Fresh databases created via create_all() already have the correct FK;
this migration closes the gap for upgrade-path databases.

Revision ID: q7r9s1t3u926
Revises: p6q8r0s2t815
Create Date: 2026-03-11
"""

import sqlalchemy as sa
from alembic import op

revision = "q7r9s1t3u926"
down_revision = "p6q8r0s2t815"
branch_labels = None
depends_on = None

# SQLite often reflects unnamed FKs with ``name=None``. In batch mode we
# provide a deterministic naming convention so those constraints can still
# be dropped by a synthetic name during table recreation.
_BATCH_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s",
}


def _reflect_and_find_fk(inspector, table: str, col: str, ref_table: str):
    """Find the existing FK definition for a given column/referred table."""
    for fk in inspector.get_foreign_keys(table):
        if fk.get("constrained_columns") == [col] and fk.get("referred_table") == ref_table:
            return fk
    return None


def _column_exists(inspector, table: str, col: str) -> bool:
    return any(column.get("name") == col for column in inspector.get_columns(table))


def _resolved_fk_name(fk: dict | None, table: str, col: str) -> str:
    if fk and fk.get("name"):
        return str(fk["name"])
    return f"fk_{table}_{col}"


def _has_target_ondelete(fk: dict | None, *, ondelete: str) -> bool:
    if not fk:
        return False
    current = (fk.get("options", {}).get("ondelete") or "").upper()
    return current == ondelete.upper()


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    for table in ("experiment", "workflow"):
        if table not in inspector.get_table_names():
            continue
        if not _column_exists(inspector, table, "project_id"):
            continue

        existing_fk = _reflect_and_find_fk(inspector, table, "project_id", "project")
        if _has_target_ondelete(existing_fk, ondelete="SET NULL"):
            continue

        with op.batch_alter_table(
            table,
            recreate="always",
            naming_convention=_BATCH_NAMING_CONVENTION,
        ) as batch_op:
            if existing_fk:
                batch_op.drop_constraint(_resolved_fk_name(existing_fk, table, "project_id"), type_="foreignkey")
            batch_op.create_foreign_key(
                f"fk_{table}_project_id",
                "project",
                ["project_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    for table in ("experiment", "workflow"):
        if table not in inspector.get_table_names():
            continue
        if not _column_exists(inspector, table, "project_id"):
            continue

        existing_fk = _reflect_and_find_fk(inspector, table, "project_id", "project")
        if not existing_fk:
            continue

        with op.batch_alter_table(
            table,
            recreate="always",
            naming_convention=_BATCH_NAMING_CONVENTION,
        ) as batch_op:
            batch_op.drop_constraint(_resolved_fk_name(existing_fk, table, "project_id"), type_="foreignkey")
