"""Principal allocation must not transfer delayed requests to another user."""

import importlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from spectra_sherpa.app.db.sqlite_migration import migration_transaction

migration = importlib.import_module("spectra_sherpa.alembic.versions.o4p6q8r0s772_principal_id_nonreuse")


def test_upgrade_preserves_references_and_never_reuses_deleted_principal():
    engine = sa.create_engine("sqlite://")
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.exec_driver_sql("CREATE TABLE user (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE)")
        conn.exec_driver_sql("CREATE INDEX ix_user_username ON user(username)")
        conn.exec_driver_sql("CREATE TABLE history (owner INTEGER REFERENCES user(id) ON DELETE CASCADE)")
        conn.exec_driver_sql("INSERT INTO user VALUES (17, 'original')")
        conn.exec_driver_sql("INSERT INTO history VALUES (17)")
        conn.commit()
        for _ in range(2):
            with migration_transaction(conn), Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
            assert conn.exec_driver_sql("SELECT owner FROM history").scalar() == 17
            assert {index["name"] for index in sa.inspect(conn).get_indexes("user")} == {"ix_user_username"}
            conn.commit()
        conn.exec_driver_sql("DELETE FROM user WHERE id=17")
        conn.exec_driver_sql("INSERT INTO user(username) VALUES ('replacement')")
        assert conn.exec_driver_sql("SELECT id FROM user").scalar() == 18
        assert conn.exec_driver_sql("SELECT count(*) FROM history").scalar() == 0
        assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    engine.dispose()


def test_upgrade_refuses_unprotected_rebuild():
    engine = sa.create_engine("sqlite://")
    with engine.connect() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.exec_driver_sql("CREATE TABLE user (id INTEGER PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(conn)), pytest.raises(RuntimeError, match="canonical"):
            migration.upgrade()
    engine.dispose()
