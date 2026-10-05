"""Populated upgrade/rollback proofs; no foreign-key nulling during rebuilds."""

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from spectra_sherpa.app.db.run_evidence_migration import migrate_run_evidence
from spectra_sherpa.app.db.sqlite_migration import migration_transaction


def test_populated_migration_preserves_references_and_supports_downgrade():
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE workflow_version (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE execution_run (id INTEGER PRIMARY KEY, run_kind VARCHAR(50) NOT NULL "
            "DEFAULT 'training', source_type TEXT)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE model_artifact (id INTEGER PRIMARY KEY, "
            "source_run_id INTEGER REFERENCES execution_run(id) ON DELETE SET NULL, "
            "workflow_version_id INTEGER REFERENCES workflow_version(id) ON DELETE SET NULL)"
        )
        connection.exec_driver_sql("CREATE TABLE background_job (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO workflow_version VALUES (1)")
        connection.exec_driver_sql("INSERT INTO execution_run VALUES (1, 'training', 'folder_watch')")
        connection.exec_driver_sql("INSERT INTO model_artifact VALUES (1, 1, 1)")
        connection.commit()
        for downgrade in (False, False, True):
            with migration_transaction(connection):
                with Operations.context(MigrationContext.configure(connection)):
                    migrate_run_evidence(downgrade=downgrade)
            assert connection.exec_driver_sql("SELECT * FROM model_artifact").one() == (1, 1, 1)
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            assert connection.exec_driver_sql("SELECT run_kind FROM execution_run").scalar() == "batch_inference"
            fks = sa.inspect(connection).get_foreign_keys("model_artifact")
            assert {fk["options"]["ondelete"] for fk in fks} == {"SET NULL" if downgrade else "RESTRICT"}
            connection.commit()
    engine.dispose()


def test_failed_migration_rolls_back_and_reenables_enforcement():
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        connection.exec_driver_sql("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE child (parent_id INTEGER REFERENCES parent(id))")
        connection.commit()
        with pytest.raises(RuntimeError, match="rolling back"):
            with migration_transaction(connection):
                connection.exec_driver_sql("INSERT INTO child VALUES (99)")
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM child").scalar() == 0
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    engine.dispose()
