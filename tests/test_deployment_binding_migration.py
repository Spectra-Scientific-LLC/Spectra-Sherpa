"""Approved watch migration preserves history without inventing a binding."""

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from spectra_sherpa.app.db.deployment_binding_migration import migrate_deployment_binding
from spectra_sherpa.app.db.sqlite_migration import migration_transaction


@pytest.mark.parametrize("alternate_constraint_names", [False, True])
def test_watch_upgrade_disables_legacy_leases_and_protects_exact_binding(alternate_constraint_names):
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE model_artifact (artifact_uid VARCHAR(36) PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE workflow_version (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE folder_watch (id INTEGER PRIMARY KEY, is_enabled BOOLEAN, active_poll_token TEXT, "
            "active_poll_claimed_at TEXT, configuration_generation INTEGER, last_error TEXT, processed_files TEXT)"
        )
        connection.exec_driver_sql("INSERT INTO folder_watch VALUES (1, 1, 'lease', 'today', 2, NULL, 'history')")
        connection.exec_driver_sql("INSERT INTO model_artifact VALUES ('reviewed')")
        connection.exec_driver_sql("INSERT INTO workflow_version VALUES (7)")
        connection.commit()

        def migrate(downgrade=False):
            with migration_transaction(connection):
                with Operations.context(MigrationContext.configure(connection)):
                    migrate_deployment_binding(downgrade=downgrade)

        migrate()
        row = connection.execute(sa.text("SELECT * FROM folder_watch")).mappings().one()
        assert not row["is_enabled"]
        assert row["active_poll_token"] is None
        assert row["active_poll_claimed_at"] is None
        assert row["configuration_generation"] == 3
        assert row["processed_files"] == "history"
        assert row["artifact_uid"] is None
        assert "Select an exact" in row["last_error"]
        connection.commit()
        migrate()
        assert connection.exec_driver_sql("SELECT configuration_generation FROM folder_watch").scalar() == 3
        # Existing columns do not prove that another migration chain repaired the row.
        connection.exec_driver_sql("UPDATE folder_watch SET is_enabled=1, active_poll_token='stale'")
        connection.commit()
        migrate()
        repaired = connection.execute(sa.text("SELECT * FROM folder_watch")).mappings().one()
        assert not repaired["is_enabled"]
        assert repaired["active_poll_token"] is None
        assert repaired["configuration_generation"] == 4
        connection.exec_driver_sql(
            "UPDATE folder_watch SET artifact_uid='reviewed', workflow_version_id=7, is_enabled=1"
        )
        connection.commit()
        migrate()
        assert connection.exec_driver_sql("SELECT is_enabled FROM folder_watch").scalar() == 1
        connection.commit()
        with pytest.raises(RuntimeError, match="retain exact"):
            migrate(True)
        with pytest.raises(sa.exc.IntegrityError):
            connection.exec_driver_sql("DELETE FROM model_artifact WHERE artifact_uid='reviewed'")
        connection.rollback()
        connection.exec_driver_sql("UPDATE folder_watch SET artifact_uid=NULL, workflow_version_id=NULL, is_enabled=0")
        connection.commit()
        if alternate_constraint_names:
            with migration_transaction(connection):
                with Operations.context(MigrationContext.configure(connection)) as operations:
                    with operations.batch_alter_table("folder_watch") as batch:
                        for column, table, target in (
                            ("artifact_uid", "model_artifact", "artifact_uid"),
                            ("workflow_version_id", "workflow_version", "id"),
                        ):
                            batch.drop_constraint(f"fk_folder_watch_{column}", type_="foreignkey")
                            batch.create_foreign_key(f"folder_watch_{column}_fkey", table, [column], [target])
        migrate(True)
        assert "artifact_uid" not in {c["name"] for c in sa.inspect(connection).get_columns("folder_watch")}
        assert connection.exec_driver_sql("SELECT processed_files FROM folder_watch").scalar() == "history"
    engine.dispose()
