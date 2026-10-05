"""Fresh startup and tracked upgrades preserve the scientific history schema."""

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

from spectra_sherpa._paths import get_package_root
from spectra_sherpa.app import models  # noqa: F401
from spectra_sherpa.app.db.base import Base


def config():
    root = get_package_root()
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("_skip_logging_config", "true")
    return cfg


def assert_history_schema(connection):
    inspector = sa.inspect(connection)
    columns = {column["name"] for column in inspector.get_columns("folder_watch")}
    assert {"uncertainty_record", "uncertainty_population"} <= columns
    for table, indexes in (
        ("analytical_qualification_record", {"user_id", "workflow_id"}),
        ("instrument_qc_record", {"watch_id", "user_id"}),
    ):
        assert inspector.has_table(table)
        actual = {tuple(index["column_names"]) for index in inspector.get_indexes(table)}
        assert {(column,) for column in indexes} <= actual
        assert inspector.get_unique_constraints(table)
    assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == (
        ScriptDirectory.from_config(config()).get_current_head()
    )


@pytest.fixture
def isolated_settings(tmp_path):
    from spectra_sherpa.app.core.config import app_config, settings

    old_url, old_mode = settings.database_url, app_config.mode
    url = f"sqlite+aiosqlite:///{tmp_path / 'profile.db'}"
    object.__setattr__(settings, "database_url", url)
    object.__setattr__(app_config, "mode", "local")
    try:
        yield url
    finally:
        object.__setattr__(settings, "database_url", old_url)
        object.__setattr__(app_config, "mode", old_mode)


def test_actual_initializer_bootstraps_empty_profile_and_reopens(isolated_settings, monkeypatch):
    from spectra_sherpa.app.db import init_db as initializer

    url = isolated_settings
    engine = create_async_engine(url)
    monkeypatch.setattr(initializer, "engine", engine)

    async def initialize():
        try:
            await initializer.init_db()
            await initializer.init_db()
            async with engine.connect() as connection:
                await connection.run_sync(assert_history_schema)
        finally:
            await engine.dispose()

    asyncio.run(initialize())


def test_tracked_pre_scientific_history_profile_upgrades_to_head(isolated_settings):
    engine = sa.create_engine(isolated_settings.replace("sqlite+aiosqlite", "sqlite", 1))
    try:
        Base.metadata.create_all(engine)
        cfg = config()
        command.stamp(cfg, "head")
        command.downgrade(cfg, "b1c3d5e7f929")
        assert not sa.inspect(engine).has_table("instrument_qc_record")
        command.upgrade(cfg, "head")
        with engine.connect() as connection:
            assert_history_schema(connection)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "existing",
    [(), ("uncertainty_record",), ("uncertainty_population",), ("uncertainty_record", "uncertainty_population")],
)
def test_uncertainty_upgrade_preserves_rows_and_existing_values(existing):
    module = ScriptDirectory.from_config(config()).get_revision("c2d4e6f8g030").module
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE folder_watch (id INTEGER PRIMARY KEY)")
            connection.exec_driver_sql("INSERT INTO folder_watch (id) VALUES (42)")
            for name in existing:
                connection.exec_driver_sql(f"ALTER TABLE folder_watch ADD COLUMN {name} TEXT")
                connection.execute(sa.text(f"UPDATE folder_watch SET {name}=:value"), {"value": "retained"})
            with Operations.context(MigrationContext.configure(connection)):
                module.upgrade()
                module.upgrade()
            row = connection.exec_driver_sql("SELECT * FROM folder_watch").mappings().one()
            assert row["id"] == 42
            for name in ("uncertainty_record", "uncertainty_population"):
                assert row[name] == ("retained" if name in existing else None)
    finally:
        engine.dispose()
