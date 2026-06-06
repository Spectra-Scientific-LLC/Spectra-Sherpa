"""Make execution runs durable project records

Revision ID: y7z9a1b3c605
Revises: x6y8z0a2b594
Create Date: 2026-05-21 00:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "y7z9a1b3c605"
down_revision = "x6y8z0a2b594"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(col["name"] == column_name for col in sa.inspect(op.get_bind()).get_columns(table_name))


def _fk_names_for_columns(table_name: str, columns: set[str]) -> list[str]:
    names: list[str] = []
    if not _table_exists(table_name):
        return names
    for fk in sa.inspect(op.get_bind()).get_foreign_keys(table_name):
        if set(fk.get("constrained_columns") or []) == columns and fk.get("name"):
            names.append(str(fk["name"]))
    return names


def _fk_exists_for_columns(table_name: str, columns: set[str]) -> bool:
    if not _table_exists(table_name):
        return False
    return any(
        set(fk.get("constrained_columns") or []) == columns
        for fk in sa.inspect(op.get_bind()).get_foreign_keys(table_name)
    )


SQLITE_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def upgrade() -> None:
    if not _table_exists("execution_run"):
        return

    if not _column_exists("execution_run", "project_id"):
        op.add_column("execution_run", sa.Column("project_id", sa.Integer(), nullable=True))
        op.create_index("ix_execution_run_project_id", "execution_run", ["project_id"])

    op.execute(
        "UPDATE execution_run "
        "SET project_id = ("
        "  SELECT workflow.project_id FROM workflow WHERE workflow.id = execution_run.workflow_id"
        ") "
        "WHERE project_id IS NULL AND workflow_id IS NOT NULL"
    )

    sqlite = op.get_bind().dialect.name == "sqlite"
    if sqlite:
        has_workflow_fk = _fk_exists_for_columns("execution_run", {"workflow_id"})
        has_project_fk = _fk_exists_for_columns("execution_run", {"project_id"})
        with op.batch_alter_table("execution_run", naming_convention=SQLITE_NAMING_CONVENTION) as batch_op:
            if has_workflow_fk:
                batch_op.drop_constraint("fk_execution_run_workflow_id_workflow", type_="foreignkey")
            if has_project_fk:
                batch_op.drop_constraint("fk_execution_run_project_id_project", type_="foreignkey")
            batch_op.alter_column("workflow_id", existing_type=sa.Integer(), nullable=True)
            batch_op.create_foreign_key(
                "fk_execution_run_project_id_project",
                "project",
                ["project_id"],
                ["id"],
                ondelete="CASCADE",
            )
            batch_op.create_foreign_key(
                "fk_execution_run_workflow_id_workflow",
                "workflow",
                ["workflow_id"],
                ["id"],
                ondelete="SET NULL",
            )
    else:
        for fk_name in _fk_names_for_columns("execution_run", {"workflow_id"}):
            op.drop_constraint(fk_name, "execution_run", type_="foreignkey")
        if not _fk_names_for_columns("execution_run", {"project_id"}):
            op.create_foreign_key(
                "fk_execution_run_project_id_project",
                "execution_run",
                "project",
                ["project_id"],
                ["id"],
                ondelete="CASCADE",
            )
        op.create_foreign_key(
            "fk_execution_run_workflow_id_workflow",
            "execution_run",
            "workflow",
            ["workflow_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.alter_column("execution_run", "workflow_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    if not _table_exists("execution_run") or not _column_exists("execution_run", "project_id"):
        return

    sqlite = op.get_bind().dialect.name == "sqlite"
    if sqlite:
        has_workflow_fk = _fk_exists_for_columns("execution_run", {"workflow_id"})
        has_project_fk = _fk_exists_for_columns("execution_run", {"project_id"})
        with op.batch_alter_table("execution_run", naming_convention=SQLITE_NAMING_CONVENTION) as batch_op:
            if has_project_fk:
                batch_op.drop_constraint("fk_execution_run_project_id_project", type_="foreignkey")
            if has_workflow_fk:
                batch_op.drop_constraint("fk_execution_run_workflow_id_workflow", type_="foreignkey")
            batch_op.alter_column("workflow_id", existing_type=sa.Integer(), nullable=False)
            batch_op.create_foreign_key(
                "fk_execution_run_workflow_id_workflow",
                "workflow",
                ["workflow_id"],
                ["id"],
                ondelete="CASCADE",
            )
    else:
        for fk_name in _fk_names_for_columns("execution_run", {"project_id"}):
            op.drop_constraint(fk_name, "execution_run", type_="foreignkey")
        for fk_name in _fk_names_for_columns("execution_run", {"workflow_id"}):
            op.drop_constraint(fk_name, "execution_run", type_="foreignkey")
        op.alter_column("execution_run", "workflow_id", existing_type=sa.Integer(), nullable=False)
        op.create_foreign_key(
            "fk_execution_run_workflow_id_workflow",
            "execution_run",
            "workflow",
            ["workflow_id"],
            ["id"],
            ondelete="CASCADE",
        )

    op.drop_index("ix_execution_run_project_id", table_name="execution_run")
    op.drop_column("execution_run", "project_id")
