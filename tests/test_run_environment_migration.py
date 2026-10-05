"""Additive environment column: idempotent, reversible, and never invented.

A historical run genuinely has no recorded environment. The migration must
leave it NULL rather than backfilling a plausible-looking one, because a
backfilled value would assert provenance the run never carried.
"""

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from spectra_sherpa.app.db.run_environment_migration import migrate_run_environment
from spectra_sherpa.app.db.sqlite_migration import migration_transaction
from spectra_sherpa.app.services.run_environment import (
    NUMERICAL_DISTRIBUTIONS,
    build_run_environment_snapshot,
)


def _run(connection, *, downgrade: bool = False) -> None:
    with migration_transaction(connection):
        with Operations.context(MigrationContext.configure(connection)):
            migrate_run_environment(downgrade=downgrade)


def _columns(connection) -> set[str]:
    names = {column["name"] for column in sa.inspect(connection).get_columns("execution_run")}
    # Reflection opens a transaction; the next migration step needs the
    # connection clean, so close it here rather than at every call site.
    connection.commit()
    return names


def test_upgrade_is_idempotent_and_leaves_historical_runs_unrecorded():
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        connection.exec_driver_sql("CREATE TABLE execution_run (id INTEGER PRIMARY KEY, source_metadata TEXT)")
        connection.exec_driver_sql("INSERT INTO execution_run VALUES (1, NULL)")
        connection.commit()

        # Run twice: a re-applied upgrade must not fail on the existing column.
        for _ in range(2):
            _run(connection)
            connection.commit()
            assert "environment_snapshot" in _columns(connection)

        # The pre-existing run stays NULL. "Not recorded" is the truthful value.
        assert (
            connection.exec_driver_sql("SELECT environment_snapshot FROM execution_run WHERE id = 1").scalar() is None
        )
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM execution_run").scalar() == 1
        connection.commit()
    engine.dispose()


def test_downgrade_drops_the_column_and_is_idempotent():
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        connection.exec_driver_sql("CREATE TABLE execution_run (id INTEGER PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO execution_run VALUES (1)")
        connection.commit()
        _run(connection)
        connection.commit()

        for _ in range(2):
            _run(connection, downgrade=True)
            connection.commit()
            assert "environment_snapshot" not in _columns(connection)

        # Rolling back the schema must not take the runs with it.
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM execution_run").scalar() == 1
    engine.dispose()


def test_missing_execution_run_table_is_a_no_op():
    # A legacy auth-only bootstrap has no scientific tables yet; the step must
    # pass over it rather than fail the chain.
    engine = sa.create_engine("sqlite://")
    with engine.connect() as connection:
        _run(connection)
        _run(connection, downgrade=True)
        connection.commit()
        assert not sa.inspect(connection).has_table("execution_run")
    engine.dispose()


def test_snapshot_records_every_declared_distribution():
    snapshot = build_run_environment_snapshot()
    assert snapshot["schema_version"] == 2
    assert snapshot["python"]
    # Every declared distribution appears, present or not: a later diff must be
    # able to tell "not installed" from "not recorded".
    assert set(snapshot["packages"]) == set(NUMERICAL_DISTRIBUTIONS)
    assert all(isinstance(value, str) and value for value in snapshot["packages"].values())
