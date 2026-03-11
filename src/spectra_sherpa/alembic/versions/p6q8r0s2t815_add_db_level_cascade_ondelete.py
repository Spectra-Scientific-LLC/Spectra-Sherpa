"""Add DB-level ondelete cascades to FK constraints.

Many FK columns relied on ORM-only cascade="all, delete-orphan" without
DB-level ondelete clauses.  This migration adds ondelete="CASCADE" (or
SET NULL where nullable) so the database enforces referential integrity
even outside SQLAlchemy sessions.

For SQLite, FK constraints are immutable — the only way to change them is
to recreate the table.  We use batch_alter_table(recreate="always") which
rebuilds each table from the current model metadata, picking up the new
ondelete clauses that were added to the ORM model ForeignKey() calls.

Revision ID: p6q8r0s2t815
Revises: a76d82a816bf
Create Date: 2026-03-10
"""

import sqlalchemy as sa
from alembic import op

revision = "p6q8r0s2t815"
down_revision = "a76d82a816bf"
branch_labels = None
depends_on = None

# Tables that had FK columns updated with ondelete clauses.
# Grouped to minimize the number of batch_alter_table calls per table.
# Format: {table_name: [(column, ref_table, ref_column, ondelete), ...]}
_TABLE_FK_UPDATES: dict[str, list[tuple[str, str, str, str]]] = {
    "experiment_file": [("experiment_id", "experiment", "id", "CASCADE")],
    "sample": [("experiment_id", "experiment", "id", "CASCADE")],
    "mixture": [("experiment_id", "experiment", "id", "CASCADE")],
    "plate_well": [
        ("experiment_id", "experiment", "id", "CASCADE"),
        ("mixture_id", "mixture", "id", "SET NULL"),
    ],
    "run_level": [
        ("experiment_id", "experiment", "id", "CASCADE"),
        ("factor_definition_id", "factor_definition", "id", "CASCADE"),
    ],
    "factor_definition": [("experiment_id", "experiment", "id", "CASCADE")],
    "matched_acquisition": [("experiment_id", "experiment", "id", "CASCADE")],
    "exp_version": [
        ("experiment_id", "experiment", "id", "CASCADE"),
        ("parent_version_id", "exp_version", "id", "SET NULL"),
    ],
    "mixture_component": [
        ("mixture_id", "mixture", "id", "CASCADE"),
        ("sample_id", "sample", "id", "CASCADE"),
    ],
    "calibration_file": [("calibration_id", "calibration", "id", "CASCADE")],
    "cal_model": [("calibration_id", "calibration", "id", "CASCADE")],
    "workflow": [("user_id", "user", "id", "CASCADE")],
    "experiment": [("user_id", "user", "id", "CASCADE")],
    "project": [("user_id", "user", "id", "CASCADE")],
    "calibration": [("user_id", "user", "id", "CASCADE")],
    "execution_run": [("user_id", "user", "id", "CASCADE")],
    "workflow_tag": [("user_id", "user", "id", "CASCADE")],
    "workflow_folder": [("user_id", "user", "id", "CASCADE")],
    "workflow_version": [("created_by", "user", "id", "CASCADE")],
    "project_version": [("created_by", "user", "id", "CASCADE")],
    "project_script": [("user_id", "user", "id", "CASCADE")],
    "doe_config": [("user_id", "user", "id", "CASCADE")],
    "llm_config": [("user_id", "user", "id", "CASCADE")],
    "background_job": [("user_id", "user", "id", "CASCADE")],
    "folder_watch": [("user_id", "user", "id", "CASCADE")],
    "api_key": [("user_id", "user", "id", "SET NULL")],
}


def _reflect_and_find_fk(inspector, table: str, col: str):
    """Find the existing FK constraint name for a given column."""
    for fk in inspector.get_foreign_keys(table):
        if col in fk.get("constrained_columns", []):
            return fk.get("name")
    return None


def _is_sqlite(conn) -> bool:
    return conn.dialect.name == "sqlite"


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    sqlite = _is_sqlite(conn)

    for table, fk_list in _TABLE_FK_UPDATES.items():
        # Check the table exists (some tables may not exist in all deployments)
        if table not in inspector.get_table_names():
            continue

        if sqlite:
            # SQLite: FK constraints are immutable, must recreate the table.
            with op.batch_alter_table(table, recreate="always") as batch_op:
                for col, ref_table, ref_col, ondelete in fk_list:
                    existing_name = _reflect_and_find_fk(inspector, table, col)
                    if existing_name:
                        batch_op.drop_constraint(existing_name, type_="foreignkey")
                    batch_op.create_foreign_key(
                        f"fk_{table}_{col}",
                        ref_table,
                        [col],
                        [ref_col],
                        ondelete=ondelete,
                    )
        else:
            # PostgreSQL: drop and recreate FK constraints directly.
            for col, ref_table, ref_col, ondelete in fk_list:
                existing_name = _reflect_and_find_fk(inspector, table, col)
                if existing_name:
                    op.drop_constraint(existing_name, table, type_="foreignkey")
                op.create_foreign_key(
                    f"fk_{table}_{col}",
                    table,
                    ref_table,
                    [col],
                    [ref_col],
                    ondelete=ondelete,
                )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    sqlite = _is_sqlite(conn)

    for table, fk_list in _TABLE_FK_UPDATES.items():
        if table not in inspector.get_table_names():
            continue

        if sqlite:
            with op.batch_alter_table(table, recreate="always") as batch_op:
                for col, ref_table, ref_col, _ondelete in fk_list:
                    existing_name = _reflect_and_find_fk(inspector, table, col)
                    if existing_name:
                        batch_op.drop_constraint(existing_name, type_="foreignkey")
                    batch_op.create_foreign_key(
                        f"fk_{table}_{col}",
                        ref_table,
                        [col],
                        [ref_col],
                    )
        else:
            for col, ref_table, ref_col, _ondelete in fk_list:
                existing_name = _reflect_and_find_fk(inspector, table, col)
                if existing_name:
                    op.drop_constraint(existing_name, table, type_="foreignkey")
                op.create_foreign_key(
                    f"fk_{table}_{col}",
                    table,
                    ref_table,
                    [col],
                    [ref_col],
                )
