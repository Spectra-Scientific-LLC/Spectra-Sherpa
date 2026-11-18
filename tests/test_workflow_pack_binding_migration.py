"""The additive binding migration never invents or discards old pack identity."""

import importlib

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

migration = importlib.import_module("spectra_sherpa.alembic.versions.w2x4y6z8a650_workflow_pack_binding")


def test_upgrade_preserves_history_and_refuses_destructive_downgrade(tmp_path, monkeypatch):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'bindings.db'}")
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE workflow (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"))
            connection.execute(sa.text("INSERT INTO workflow VALUES (1, 'Historical OSS')"))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            migration.upgrade()  # Fresh metadata and migration replay remain compatible.
            assert connection.execute(sa.text("SELECT name, pack_binding FROM workflow")).one() == (
                "Historical OSS",
                None,
            )
            connection.execute(sa.text("UPDATE workflow SET pack_binding=:binding"), {"binding": '{"nodes":[]}'})
            with pytest.raises(RuntimeError, match="Cannot discard"):
                migration.downgrade()
            assert connection.scalar(sa.text("SELECT pack_binding FROM workflow")) == '{"nodes":[]}'
            connection.execute(sa.text("UPDATE workflow SET pack_binding=NULL"))
            migration.downgrade()
            assert "pack_binding" not in {column["name"] for column in sa.inspect(connection).get_columns("workflow")}
            assert connection.scalar(sa.text("SELECT name FROM workflow")) == "Historical OSS"
    finally:
        engine.dispose()
