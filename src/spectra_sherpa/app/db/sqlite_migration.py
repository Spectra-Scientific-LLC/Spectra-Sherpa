"""Atomic SQLite table rebuilds without firing destructive FK cascades."""

from contextlib import contextmanager

from sqlalchemy.engine import Connection


@contextmanager
def migration_transaction(connection: Connection):
    if connection.dialect.name != "sqlite":
        yield
        return
    if connection.in_transaction():
        raise RuntimeError("SQLite migrations require a dedicated connection without an active transaction")
    connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    connection.commit()
    connection.exec_driver_sql("BEGIN IMMEDIATE")
    try:
        yield
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchmany(1)
        if violations:
            raise RuntimeError("Migration would leave invalid foreign-key references; rolling back")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()
