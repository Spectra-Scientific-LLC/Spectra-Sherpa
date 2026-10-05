"""Historical run provenance is assigned to explicit artifact roles."""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from spectra_sherpa.app.db import run_artifact_role_migration as migration


def test_run_artifact_role_migration_backfills_each_meaning_without_overwriting() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("""
                CREATE TABLE execution_run (
                    id INTEGER PRIMARY KEY,
                    run_kind VARCHAR(50) NOT NULL,
                    model_ids JSON,
                    applied_artifact_uids JSON
                )
                """))
        connection.execute(sa.text("""
                INSERT INTO execution_run VALUES
                    (1, 'training', '["produced-a"]', '[]'),
                    (2, 'batch_inference', '["succeeded-a"]', '["attempted-a", "attempted-b"]'),
                    (3, 'data', NULL, NULL)
                """))
        with Operations.context(MigrationContext.configure(connection)):
            migration.migrate_run_artifact_roles()
            table = sa.Table("execution_run", sa.MetaData(), autoload_with=connection)
            rows = connection.execute(sa.select(table).order_by(table.c.id)).mappings().all()
            assert rows[0]["produced_artifact_uids"] == ["produced-a"]
            assert rows[0]["attempted_artifact_uids"] == []
            assert rows[0]["succeeded_artifact_uids"] == []
            assert rows[1]["produced_artifact_uids"] == []
            assert rows[1]["attempted_artifact_uids"] == ["attempted-a", "attempted-b"]
            assert rows[1]["succeeded_artifact_uids"] == ["succeeded-a"]
            assert rows[2]["produced_artifact_uids"] == []

            connection.execute(table.update().where(table.c.id == 2).values(produced_artifact_uids=["preserved"]))
            migration.migrate_run_artifact_roles()
            assert connection.scalar(sa.select(table.c.produced_artifact_uids).where(table.c.id == 2)) == ["preserved"]

    engine.dispose()


def test_run_artifact_role_migration_ignores_unrelated_missing_foreign_key_tables() -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(sa.text("""
                CREATE TABLE execution_run (
                    id INTEGER PRIMARY KEY,
                    run_kind VARCHAR(50) NOT NULL,
                    model_ids JSON,
                    applied_artifact_uids JSON,
                    workflow_folder_id INTEGER REFERENCES workflow_folder(id)
                )
                """))
        connection.execute(sa.text("""
                INSERT INTO execution_run
                    (id, run_kind, model_ids, applied_artifact_uids)
                VALUES (1, 'training', '["produced-a"]', '[]')
                """))

        with Operations.context(MigrationContext.configure(connection)):
            migration.migrate_run_artifact_roles()

        produced = connection.execute(
            sa.text("SELECT produced_artifact_uids FROM execution_run WHERE id = 1")
        ).scalar_one()
        assert json.loads(produced) == ["produced-a"]

    engine.dispose()
