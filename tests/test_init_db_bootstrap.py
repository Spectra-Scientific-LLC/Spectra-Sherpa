"""Validate init_db bootstrap paths: fresh, legacy-untracked, and tracked.

These tests create real temp SQLite databases and run the full Alembic
migration chain to verify that the three-path logic in init_db.py is safe.

The Alembic ``env.py`` reads its URL from ``settings.database_url``, so each
test monkeypatches that setting to point at the temp database.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from spectra_sherpa.app import models  # noqa: F401  # Ensure metadata is populated for create_all paths.
from spectra_sherpa.app.db.base import Base
from spectra_sherpa.app.db.experiment_specimen_migration import migrated_specimen_uid
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.acquisition_plans import read_acquisition_plan


def _alembic_cfg() -> Config:
    """Build an Alembic Config."""
    from spectra_sherpa._paths import get_package_root

    package_root = get_package_root()
    alembic_ini = package_root / "alembic.ini"
    alembic_dir = package_root / "alembic"

    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(alembic_dir))
    cfg.set_main_option("_skip_logging_config", "true")
    return cfg


def _run_upgrade_head(async_url: str) -> None:
    """Run alembic upgrade head with settings.database_url overridden."""
    _run_upgrade(async_url, "head")


def _run_upgrade(async_url: str, revision: str) -> None:
    """Run alembic upgrade to a specific revision with settings overridden."""
    from spectra_sherpa.app.core.config import settings

    original = settings.database_url
    # Settings is frozen (Pydantic), so use object.__setattr__
    object.__setattr__(settings, "database_url", async_url)
    try:
        cfg = _alembic_cfg()
        command.upgrade(cfg, revision)
    finally:
        object.__setattr__(settings, "database_url", original)


def _run_downgrade(async_url: str, revision: str) -> None:
    from spectra_sherpa.app.core.config import settings

    original = settings.database_url
    object.__setattr__(settings, "database_url", async_url)
    try:
        command.downgrade(_alembic_cfg(), revision)
    finally:
        object.__setattr__(settings, "database_url", original)


def _sync_url(path: Path) -> str:
    return f"sqlite:///{path}"


def _async_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path}"


class TestBootstrapFreshDB:
    """Scenario: empty database, no tables at all.

    Mirrors init_db.py's untracked path: create_all() then upgrade head.
    """

    def test_create_all_then_upgrade_head(self, tmp_path):
        db_path = tmp_path / "fresh.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)

        # Step 1: create_all (same as init_db for untracked)
        sync_engine = sa.create_engine(sync_url)
        Base.metadata.create_all(sync_engine)

        # Verify tables exist
        inspector = sa_inspect(sync_engine)
        assert "user" in inspector.get_table_names()
        user_columns = {column["name"] for column in inspector.get_columns("user")}
        assert "principal_kind" in user_columns

        # Step 2: alembic upgrade head (should not crash)
        _run_upgrade_head(async_url)

        # Verify alembic_version is stamped
        inspector = sa_inspect(sync_engine)
        assert "alembic_version" in inspector.get_table_names()
        assert "dataset_analysis_binding" in inspector.get_table_names()
        assert "workflow_data_selection_revision" in inspector.get_table_names()

        # custom_algo is dropped by migration a76d82a816bf
        assert "custom_algo" not in inspector.get_table_names()
        assert "llm_config" not in inspector.get_table_names()

        # Verify project_id FK on experiment has ondelete SET NULL
        # (added by q7r9s1t3u926)
        fks = inspector.get_foreign_keys("experiment")
        project_fk = [fk for fk in fks if "project_id" in fk.get("constrained_columns", [])]
        assert len(project_fk) == 1
        assert project_fk[0].get("options", {}).get("ondelete", "").upper() == "SET NULL"

        sync_engine.dispose()


class TestBootstrapLegacyUntracked:
    """Scenario: tables exist (from old create_all) but no alembic_version."""

    def test_legacy_tables_then_upgrade_head(self, tmp_path):
        db_path = tmp_path / "legacy.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)

        # Simulate legacy DB: create tables via create_all, no alembic stamp
        sync_engine = sa.create_engine(sync_url)
        Base.metadata.create_all(sync_engine)

        # Verify no alembic_version
        inspector = sa_inspect(sync_engine)
        assert "alembic_version" not in inspector.get_table_names()

        # Run upgrade head — should succeed
        _run_upgrade_head(async_url)

        # Verify alembic_version is now stamped
        inspector = sa_inspect(sync_engine)
        assert "alembic_version" in inspector.get_table_names()
        assert "dataset_analysis_binding" in inspector.get_table_names()

        # custom_algo is dropped by migration a76d82a816bf
        assert "custom_algo" not in inspector.get_table_names()
        assert "llm_config" not in inspector.get_table_names()

        # Verify core tables survived
        assert "user" in inspector.get_table_names()
        assert "workflow" in inspector.get_table_names()
        assert "experiment" in inspector.get_table_names()

        sync_engine.dispose()


class TestBootstrapTracked:
    """Scenario: database already tracked by Alembic (upgrade from scratch)."""

    def test_upgrade_head_on_empty_db(self, tmp_path):
        db_path = tmp_path / "tracked.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)

        # Run upgrade head from scratch (no create_all first)
        _run_upgrade_head(async_url)

        # Verify tables and alembic_version
        sync_engine = sa.create_engine(sync_url)
        inspector = sa_inspect(sync_engine)
        assert "alembic_version" in inspector.get_table_names()
        assert "dataset_analysis_binding" in inspector.get_table_names()
        assert "workflow_data_selection_revision" in inspector.get_table_names()
        assert "user" in inspector.get_table_names()
        user_columns = {column["name"] for column in inspector.get_columns("user")}
        assert "principal_kind" in user_columns

        # custom_algo is created then dropped during the migration chain
        assert "custom_algo" not in inspector.get_table_names()
        assert "llm_config" not in inspector.get_table_names()

        # Verify project_id FK on workflow has ondelete SET NULL
        fks = inspector.get_foreign_keys("workflow")
        project_fk = [fk for fk in fks if "project_id" in fk.get("constrained_columns", [])]
        assert len(project_fk) == 1
        assert project_fk[0].get("options", {}).get("ondelete", "").upper() == "SET NULL"

        # Run upgrade head again — should be a no-op
        _run_upgrade_head(async_url)

        sync_engine.dispose()


class TestUnusedLlmConfigMigration:
    @pytest.mark.parametrize("state", ["absent", "empty", "populated"])
    def test_cleanup_preserves_existing_preferences_and_credentials(self, tmp_path, state):
        db_path = tmp_path / f"legacy-llm-{state}.db"
        async_url = _async_url(db_path)
        _run_upgrade(async_url, "f5g7h9i1j333")
        sync_engine = sa.create_engine(_sync_url(db_path))
        with sync_engine.begin() as connection:
            connection.execute(text("INSERT INTO user (id, username) VALUES (1, 'chemist')"))
            connection.execute(
                text(
                    "INSERT INTO api_key (user_id, service_name, key_encrypted) "
                    "VALUES (1, 'chat', 'synthetic-encrypted-credential')"
                )
            )
            if state == "absent":
                connection.execute(text("DROP TABLE llm_config"))
            elif state == "populated":
                connection.execute(
                    text("INSERT INTO llm_config (id, user_id, model) VALUES (1, 1, 'legacy-user-choice')")
                )

        _run_upgrade_head(async_url)
        _run_upgrade_head(async_url)  # reopening must be harmless
        assert sa_inspect(sync_engine).has_table("llm_config") is (state == "populated")
        with sync_engine.connect() as connection:
            assert connection.execute(text("SELECT key_encrypted FROM api_key")).scalar_one() == (
                "synthetic-encrypted-credential"
            )
            if state == "populated":
                assert connection.execute(text("SELECT model FROM llm_config")).scalar_one() == "legacy-user-choice"

        _run_downgrade(async_url, "f5g7h9i1j333")
        assert sa_inspect(sync_engine).has_table("llm_config")
        with sync_engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM llm_config")).scalar_one() == (
                1 if state == "populated" else 0
            )
        _run_upgrade_head(async_url)
        assert sa_inspect(sync_engine).has_table("llm_config") is (state == "populated")
        sync_engine.dispose()


class TestProjectArchiveMigration:
    def test_downgrade_refuses_to_erase_archive_state(self, tmp_path):
        db_path = tmp_path / "project-archive.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)
        _run_upgrade_head(async_url)

        sync_engine = sa.create_engine(sync_url)
        with sync_engine.begin() as connection:
            connection.execute(text("INSERT INTO \"user\" (id, username) VALUES (1, 'chemist')"))
            connection.execute(
                text(
                    "INSERT INTO project (id, user_id, name, archived_at) "
                    "VALUES (1, 1, 'Retained study', CURRENT_TIMESTAMP)"
                )
            )

        with pytest.raises(RuntimeError, match="Export archived and permanently removed projects"):
            _run_downgrade(async_url, "u0v2w4x6y359")
        with sync_engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == ScriptDirectory.from_config(_alembic_cfg()).get_current_head()
            )
            assert connection.execute(text("SELECT archived_at FROM project WHERE id = 1")).scalar_one() is not None
        sync_engine.dispose()


class TestRetiredDoeMigration:
    def test_duplicate_normalized_legacy_wells_fail_before_any_namespace_mutation(self, tmp_path):
        db_path = tmp_path / "duplicate-normalized-wells.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)
        _run_upgrade(async_url, "p5q7r9s1t604")

        sync_engine = sa.create_engine(sync_url)
        with sync_engine.begin() as connection:
            connection.execute(text("INSERT INTO \"user\" (id, username) VALUES (1, 'chemist')"))
            connection.execute(
                text(
                    "INSERT INTO experiment (id, user_id, name, metadata_path) "
                    "VALUES (10, 1, 'Plate study', 'metadata.json')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO mixture (id, experiment_id, mixture_id, basis) VALUES "
                    "(20, 10, 'first', 'volume'), (21, 10, 'second', 'volume')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO plate_well (id, experiment_id, well_position, mixture_id) VALUES "
                    "(30, 10, 'A1', 20), (31, 10, 'A01', 21)"
                )
            )

        with pytest.raises(RuntimeError, match="duplicate legacy plate wells after normalization"):
            _run_upgrade_head(async_url)

        tables = set(sa_inspect(sync_engine).get_table_names())
        assert "plate_well" in tables
        assert "mixture" in tables
        assert "retired_doe_plate_well" not in tables
        assert "acquisition_plan_well" not in tables
        assert "acquisition_plan" not in tables
        with sync_engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "p5q7r9s1t604"
            assert connection.execute(text("SELECT COUNT(*) FROM plate_well")).scalar_one() == 2
        sync_engine.dispose()

    def test_complete_plan_migration_rejects_duplicates_retained_by_an_already_upgraded_database(self, tmp_path):
        db_path = tmp_path / "already-retired-duplicate-wells.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)
        _run_upgrade(async_url, "s8t0u2v4w137")

        sync_engine = sa.create_engine(sync_url)
        with sync_engine.begin() as connection:
            connection.execute(text("INSERT INTO \"user\" (id, username) VALUES (1, 'chemist')"))
            connection.execute(
                text(
                    "INSERT INTO experiment (id, user_id, name, metadata_path) "
                    "VALUES (10, 1, 'Plate study', 'metadata.json')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO retired_doe_mixture (id, experiment_id, mixture_id, basis) VALUES "
                    "(20, 10, 'first', 'volume'), (21, 10, 'second', 'volume')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO retired_doe_plate_well "
                    "(id, experiment_id, well_position, mixture_id) VALUES "
                    "(30, 10, 'A1', 20), (31, 10, 'A01', 21)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO acquisition_plan_well "
                    "(experiment_id, well_position, planned_sample_label) "
                    "VALUES (10, 'A01', 'first')"
                )
            )

        with pytest.raises(RuntimeError, match="duplicate retained plate wells after normalization"):
            _run_upgrade_head(async_url)

        tables = set(sa_inspect(sync_engine).get_table_names())
        assert "acquisition_plan" not in tables
        assert "acquisition_plan_well" in tables
        with sync_engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "s8t0u2v4w137"
            assert connection.execute(text("SELECT COUNT(*) FROM retired_doe_plate_well")).scalar_one() == 2
        sync_engine.dispose()

    def test_existing_acquisition_plan_links_are_rewritten_to_specimen_uids(self, tmp_path):
        import json

        db_path = tmp_path / "existing-plan-specimen-link.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)
        _run_upgrade(async_url, "t9u1v3w5x248")

        document = {
            "schema_version": "spectrasherpa-acquisition-plan/2",
            "plate_format_id": "plate-96",
            "samples": [
                {
                    "sample_id": "oil",
                    "source_ref": "legacy-sample:21",
                    "name": "Oil",
                    "sample_type": "material",
                    "notes": None,
                }
            ],
            "mixtures": [],
            "factors": [],
            "wells": [],
            "acquisition_order": [],
            "matching": {"rules": {}, "matches": []},
        }
        sync_engine = sa.create_engine(sync_url)
        with sync_engine.begin() as connection:
            connection.execute(text("INSERT INTO \"user\" (id, username) VALUES (1, 'chemist')"))
            connection.execute(
                text(
                    "INSERT INTO experiment (id, user_id, name, metadata_path) "
                    "VALUES (10, 1, 'Plate', 'metadata.json')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO sample (id, experiment_id, sample_id, name, type, active) "
                    "VALUES (21, 10, 'oil', 'Oil', 'material', 1)"
                )
            )
            connection.execute(
                text("INSERT INTO acquisition_plan (experiment_id, document) VALUES (10, :document)"),
                {"document": json.dumps(document)},
            )

        _run_upgrade_head(async_url)

        with sync_engine.connect() as connection:
            migrated = connection.execute(
                text("SELECT document FROM acquisition_plan WHERE experiment_id = 10")
            ).scalar_one()
            if isinstance(migrated, str):
                migrated = json.loads(migrated)
            assert migrated["schema_version"] == "spectrasherpa-acquisition-plan/3"
            assert migrated["samples"][0]["source_specimen_uid"] == migrated_specimen_uid(21)
            assert "source_ref" not in migrated["samples"][0]

        _run_downgrade(async_url, "t9u1v3w5x248")
        with sync_engine.connect() as connection:
            downgraded = connection.execute(
                text("SELECT document FROM acquisition_plan WHERE experiment_id = 10")
            ).scalar_one()
            if isinstance(downgraded, str):
                downgraded = json.loads(downgraded)
            assert downgraded["schema_version"] == "spectrasherpa-acquisition-plan/2"
            assert downgraded["samples"][0]["source_ref"] == "legacy-sample:21"
            assert "source_specimen_uid" not in downgraded["samples"][0]
            assert "sample" in set(sa_inspect(connection).get_table_names())

        _run_upgrade_head(async_url)
        with sync_engine.connect() as connection:
            reupgraded = connection.execute(
                text("SELECT document FROM acquisition_plan WHERE experiment_id = 10")
            ).scalar_one()
            if isinstance(reupgraded, str):
                reupgraded = json.loads(reupgraded)
            assert reupgraded["samples"][0]["source_specimen_uid"] == migrated_specimen_uid(21)
        sync_engine.dispose()

    def test_specimen_downgrade_reverse_maps_post_migration_uids(self, tmp_path):
        import json
        import uuid

        db_path = tmp_path / "post-migration-specimen-link.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)
        _run_upgrade_head(async_url)

        specimen_uid = str(uuid.uuid4())
        document = {
            "schema_version": "spectrasherpa-acquisition-plan/3",
            "plate_format_id": "plate-96",
            "samples": [
                {
                    "sample_id": "new-specimen",
                    "source_specimen_uid": specimen_uid,
                    "name": "New specimen",
                    "sample_type": "material",
                    "notes": None,
                }
            ],
            "mixtures": [],
            "factors": [],
            "wells": [],
            "acquisition_order": [],
            "matching": {"rules": {}, "matches": []},
        }
        sync_engine = sa.create_engine(sync_url)
        with sync_engine.begin() as connection:
            connection.execute(text("INSERT INTO \"user\" (id, username) VALUES (1, 'chemist')"))
            connection.execute(
                text(
                    "INSERT INTO experiment (id, user_id, name, metadata_path) "
                    "VALUES (10, 1, 'Plate', 'metadata.json')"
                )
            )
            result = connection.execute(
                text(
                    "INSERT INTO experiment_specimen "
                    "(specimen_uid, experiment_id, specimen_key, name, specimen_type, active, created_at, updated_at) "
                    "VALUES (:uid, 10, 'new-specimen', 'New specimen', 'material', 1, CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP)"
                ),
                {"uid": specimen_uid},
            )
            specimen_id = int(result.lastrowid)
            connection.execute(
                text("INSERT INTO acquisition_plan (experiment_id, document) VALUES (10, :document)"),
                {"document": json.dumps(document)},
            )

        _run_downgrade(async_url, "t9u1v3w5x248")
        with sync_engine.connect() as connection:
            downgraded = connection.execute(
                text("SELECT document FROM acquisition_plan WHERE experiment_id = 10")
            ).scalar_one()
            if isinstance(downgraded, str):
                downgraded = json.loads(downgraded)
            assert downgraded["samples"][0]["source_ref"] == f"legacy-sample:{specimen_id}"
            assert (
                connection.execute(
                    text("SELECT sample_id FROM sample WHERE id = :id"), {"id": specimen_id}
                ).scalar_one()
                == "new-specimen"
            )

        _run_upgrade_head(async_url)
        with sync_engine.connect() as connection:
            reupgraded = connection.execute(
                text("SELECT document FROM acquisition_plan WHERE experiment_id = 10")
            ).scalar_one()
            if isinstance(reupgraded, str):
                reupgraded = json.loads(reupgraded)
            expected_uid = migrated_specimen_uid(specimen_id)
            assert reupgraded["samples"][0]["source_specimen_uid"] == expected_uid
            assert (
                connection.execute(
                    text("SELECT specimen_uid FROM experiment_specimen WHERE id = :id"), {"id": specimen_id}
                ).scalar_one()
                == expected_uid
            )
        sync_engine.dispose()

    def test_specimen_downgrade_refuses_unresolvable_plan_uid_atomically(self, tmp_path):
        import json
        import uuid

        db_path = tmp_path / "missing-specimen-link.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)
        _run_upgrade_head(async_url)
        missing_uid = str(uuid.uuid4())
        document = {
            "schema_version": "spectrasherpa-acquisition-plan/3",
            "plate_format_id": "plate-96",
            "samples": [{"sample_id": "missing", "source_specimen_uid": missing_uid, "name": "Missing"}],
            "mixtures": [],
            "factors": [],
            "wells": [],
            "acquisition_order": [],
            "matching": {"rules": {}, "matches": []},
        }
        sync_engine = sa.create_engine(sync_url)
        with sync_engine.begin() as connection:
            connection.execute(text("INSERT INTO \"user\" (id, username) VALUES (1, 'chemist')"))
            connection.execute(
                text(
                    "INSERT INTO experiment (id, user_id, name, metadata_path) "
                    "VALUES (10, 1, 'Plate', 'metadata.json')"
                )
            )
            connection.execute(
                text("INSERT INTO acquisition_plan (experiment_id, document) VALUES (10, :document)"),
                {"document": json.dumps(document)},
            )

        with pytest.raises(RuntimeError, match="has no legacy row; export specimens and plans first"):
            _run_downgrade(async_url, "t9u1v3w5x248")

        assert "experiment_specimen" in set(sa_inspect(sync_engine).get_table_names())
        with sync_engine.connect() as connection:
            retained = connection.execute(
                text("SELECT document FROM acquisition_plan WHERE experiment_id = 10")
            ).scalar_one()
            if isinstance(retained, str):
                retained = json.loads(retained)
            assert retained == document
        sync_engine.dispose()

    def test_full_downgrade_preserves_referenced_key_priority_over_lower_unreferenced_duplicate(self, tmp_path):
        import json

        db_path = tmp_path / "referenced-key-priority.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)
        _run_upgrade(async_url, "p5q7r9s1t604")

        sync_engine = sa.create_engine(sync_url)
        with sync_engine.begin() as connection:
            connection.execute(text("INSERT INTO \"user\" (id, username) VALUES (1, 'chemist')"))
            connection.execute(
                text(
                    "INSERT INTO experiment (id, user_id, name, metadata_path) "
                    "VALUES (10, 1, 'Plate', 'metadata.json')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO sample (id, experiment_id, sample_id, name, active) VALUES "
                    "(21, 10, 'oil', 'Unreferenced oil', 1), "
                    "(22, 10, 'oil', 'Referenced oil', 1)"
                )
            )
            connection.execute(
                text("INSERT INTO mixture (id, experiment_id, mixture_id, basis) " "VALUES (30, 10, 'blend', 'volume')")
            )
            connection.execute(
                text(
                    "INSERT INTO mixture_component (id, mixture_id, sample_id, amount, unit) "
                    "VALUES (40, 30, 22, 1.0, 'mL')"
                )
            )

        _run_upgrade_head(async_url)
        with sync_engine.connect() as connection:
            specimen_keys = connection.execute(
                text("SELECT id, specimen_key FROM experiment_specimen ORDER BY id")
            ).all()
            document = connection.execute(
                text("SELECT document FROM acquisition_plan WHERE experiment_id = 10")
            ).scalar_one()
            if isinstance(document, str):
                document = json.loads(document)
            assert specimen_keys == [(21, "oil#legacy-21"), (22, "oil")]
            assert document["samples"][0]["sample_id"] == "oil"
            assert document["samples"][0]["source_specimen_uid"] == migrated_specimen_uid(22)

        _run_downgrade(async_url, "p5q7r9s1t604")
        with sync_engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "p5q7r9s1t604"
            assert connection.execute(text("SELECT id, sample_id FROM sample ORDER BY id")).all() == [
                (21, "oil#legacy-21"),
                (22, "oil"),
            ]
        sync_engine.dispose()

    def test_legacy_rows_are_preserved_and_plate_plan_is_migrated(self, tmp_path):
        db_path = tmp_path / "retired-doe.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)
        _run_upgrade(async_url, "p5q7r9s1t604")

        sync_engine = sa.create_engine(sync_url)
        with sync_engine.begin() as connection:
            connection.execute(text("INSERT INTO \"user\" (id, username) VALUES (1, 'chemist')"))
            connection.execute(
                text(
                    "INSERT INTO experiment (id, user_id, name, metadata_path) "
                    "VALUES (10, 1, 'Plate study', 'metadata.json')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO mixture (id, experiment_id, mixture_id, basis) "
                    "VALUES (20, 10, 'standard-1', 'volume')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO sample "
                    "(id, experiment_id, sample_id, name, type, brand, cas_number, active, notes, created_at) VALUES "
                    "(21, 10, 'oil', 'Oil', 'material', 'Supplier A', '67-64-1', 1, "
                    "'referenced', '2025-01-02 03:04:05'), "
                    "(27, 10, 'unused', 'Unused', 'control', 'Supplier B', '7732-18-5', 0, "
                    "'unreferenced', '2025-02-03 04:05:06'), "
                    "(28, 10, 'oil', 'Oil duplicate', 'material', 'Supplier C', '64-17-5', 1, "
                    "'same textual id', '2025-03-04 05:06:07')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO mixture_component (id, mixture_id, sample_id, amount, unit) "
                    "VALUES (22, 20, 21, 1.5, 'mL'), (29, 20, 28, 0.25, 'mL')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO factor_definition (id, experiment_id, name, scope, type, levels) "
                    "VALUES (23, 10, 'Temperature', 'method', 'numeric', '[20, 30]')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO run_level (id, experiment_id, factor_definition_id, level_value, sequence_order) "
                    "VALUES (24, 10, 23, '20', 0)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO matched_acquisition (id, experiment_id, seq, filename, cell, factor_values) "
                    "VALUES (25, 10, 1, 'run_1.csv', 'A1', '{\"Temperature\": 20}')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO doe_config (id, user_id, name, is_default, match_settings) "
                    "VALUES (26, 1, 'Default match', 1, '{\"use_plate_map\": true}')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO plate_well (id, experiment_id, well_position, mixture_id) " "VALUES (30, 10, 'A1', 20)"
                )
            )
            specimen_rows_before = connection.execute(
                text(
                    "SELECT id, experiment_id, sample_id, name, type, brand, cas_number, active, notes, created_at "
                    "FROM sample ORDER BY id"
                )
            ).all()

        _run_upgrade_head(async_url)
        inspector = sa_inspect(sync_engine)
        tables = set(inspector.get_table_names())
        assert "plate_well" not in tables
        assert "mixture" not in tables
        assert "retired_doe_plate_well" in tables
        assert "retired_doe_mixture" in tables
        assert "acquisition_plan_well" not in tables
        assert "acquisition_plan" in tables
        assert "acquisition_plan_preset" in tables
        assert "sample" not in tables
        assert "experiment_specimen" in tables
        specimen_columns = {column["name"]: column for column in inspector.get_columns("experiment_specimen")}
        assert specimen_columns["specimen_uid"]["nullable"] is False
        assert specimen_columns["created_at"]["nullable"] is False
        assert specimen_columns["updated_at"]["nullable"] is False
        unique_constraints = {
            constraint["name"] for constraint in inspector.get_unique_constraints("experiment_specimen")
        }
        assert {"uq_experiment_specimen_uid", "uq_experiment_specimen_key"} <= unique_constraints
        with sync_engine.connect() as connection:
            document = connection.execute(
                text("SELECT document FROM acquisition_plan WHERE experiment_id = 10")
            ).scalar_one()
            if isinstance(document, str):
                import json

                document = json.loads(document)
            assert document["samples"] == [
                {
                    "sample_id": "oil",
                    "source_specimen_uid": migrated_specimen_uid(21),
                    "name": "Oil",
                    "sample_type": "material",
                    "notes": "referenced",
                },
                {
                    "sample_id": "oil#legacy-28",
                    "source_specimen_uid": migrated_specimen_uid(28),
                    "name": "Oil duplicate",
                    "sample_type": "material",
                    "notes": "same textual id",
                },
            ]
            assert document["mixtures"][0]["components"] == [
                {"sample_id": "oil", "amount": 1.5, "unit": "mL"},
                {"sample_id": "oil#legacy-28", "amount": 0.25, "unit": "mL"},
            ]
            assert document["factors"][0]["name"] == "Temperature"
            assert document["acquisition_order"][0]["level_value"] == "20"
            assert document["matching"]["matches"][0]["filename"] == "run_1.csv"
            assert document["wells"][0]["mixture_id"] == "standard-1"
            settings = connection.execute(
                text("SELECT settings FROM acquisition_plan_preset WHERE preset_key = 'legacy-26'")
            ).scalar_one()
            if isinstance(settings, str):
                import json

                settings = json.loads(settings)
            assert settings["match_settings"] == {"use_plate_map": True}
            assert connection.execute(
                text("SELECT id, experiment_id, well_position, mixture_id FROM retired_doe_plate_well")
            ).one() == (30, 10, "A1", 20)
            assert connection.execute(
                text(
                    "SELECT id, experiment_id, specimen_key, name, specimen_type, brand, cas_number, active, "
                    "notes FROM experiment_specimen ORDER BY id"
                )
            ).all() == [
                specimen_rows_before[0][:-1],
                specimen_rows_before[1][:-1],
                (
                    specimen_rows_before[2][0],
                    specimen_rows_before[2][1],
                    "oil#legacy-28",
                    *specimen_rows_before[2][3:-1],
                ),
            ]

        _run_downgrade(async_url, "p5q7r9s1t604")
        inspector = sa_inspect(sync_engine)
        tables = set(inspector.get_table_names())
        assert "acquisition_plan_well" not in tables
        assert "plate_well" in tables
        assert "mixture" in tables
        assert "retired_doe_plate_well" not in tables
        with sync_engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT id, experiment_id, sample_id, name, type, brand, cas_number, active, notes "
                    "FROM sample ORDER BY id"
                )
            ).all() == [
                specimen_rows_before[0][:-1],
                specimen_rows_before[1][:-1],
                (
                    specimen_rows_before[2][0],
                    specimen_rows_before[2][1],
                    "oil#legacy-28",
                    *specimen_rows_before[2][3:-1],
                ),
            ]
        sync_engine.dispose()

    @pytest.mark.parametrize("failure", ["missing", "cross-experiment"])
    def test_complete_plan_migration_rejects_invalid_specimen_references_atomically(self, tmp_path, failure):
        db_path = tmp_path / f"invalid-specimen-reference-{failure}.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)
        _run_upgrade(async_url, "s8t0u2v4w137")

        sync_engine = sa.create_engine(sync_url)
        with sync_engine.begin() as connection:
            connection.execute(text("INSERT INTO \"user\" (id, username) VALUES (1, 'chemist')"))
            connection.execute(
                text(
                    "INSERT INTO experiment (id, user_id, name, metadata_path) VALUES "
                    "(10, 1, 'First', 'first.json'), (11, 1, 'Second', 'second.json')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO retired_doe_mixture (id, experiment_id, mixture_id, basis) "
                    "VALUES (20, 10, 'mix', 'volume')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO sample (id, experiment_id, sample_id, name, active) "
                    "VALUES (21, 11, 'foreign', 'Foreign specimen', 1)"
                )
            )
            sample_id = 999 if failure == "missing" else 21
            connection.execute(
                text(
                    "INSERT INTO retired_doe_mixture_component "
                    "(id, mixture_id, sample_id, amount, unit) VALUES (22, 20, :sample_id, 1.0, 'mL')"
                ),
                {"sample_id": sample_id},
            )
            specimen_rows_before = connection.execute(text("SELECT * FROM sample ORDER BY id")).all()

        expected = "is missing" if failure == "missing" else "belongs to another experiment"
        with pytest.raises(RuntimeError, match=expected):
            _run_upgrade_head(async_url)

        tables = set(sa_inspect(sync_engine).get_table_names())
        assert "acquisition_plan" not in tables
        assert "acquisition_plan_preset" not in tables
        with sync_engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "s8t0u2v4w137"
            assert connection.execute(text("SELECT * FROM sample ORDER BY id")).all() == specimen_rows_before
        sync_engine.dispose()

    def test_boundary_length_duplicate_ids_upgrade_read_and_downgrade(self, tmp_path):
        db_path = tmp_path / "boundary-length-duplicate-ids.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)
        _run_upgrade(async_url, "p5q7r9s1t604")
        sample_id = "s" * 100
        mixture_id = "m" * 100

        sync_engine = sa.create_engine(sync_url)
        with sync_engine.begin() as connection:
            connection.execute(text("INSERT INTO \"user\" (id, username) VALUES (1, 'chemist')"))
            connection.execute(
                text(
                    "INSERT INTO experiment (id, user_id, name, metadata_path) "
                    "VALUES (10, 1, 'Boundary IDs', 'metadata.json')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO sample (id, experiment_id, sample_id, name, active) VALUES "
                    "(21, 10, :sample_id, 'First', 1), (22, 10, :sample_id, 'Second', 1)"
                ),
                {"sample_id": sample_id},
            )
            connection.execute(
                text(
                    "INSERT INTO mixture (id, experiment_id, mixture_id, basis) VALUES "
                    "(30, 10, :mixture_id, 'volume'), (31, 10, :mixture_id, 'volume')"
                ),
                {"mixture_id": mixture_id},
            )
            connection.execute(
                text(
                    "INSERT INTO mixture_component (id, mixture_id, sample_id, amount, unit) VALUES "
                    "(40, 30, 21, 1.0, 'mL'), (41, 31, 22, 2.0, 'mL')"
                )
            )

        _run_upgrade_head(async_url)

        async def read_plan() -> dict[str, object]:
            engine = create_async_engine(async_url)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            try:
                async with sessions() as session:
                    return await read_acquisition_plan(session, 10)
            finally:
                await engine.dispose()

        plan = asyncio.run(read_plan())
        samples_by_ref = {str(item["source_specimen_uid"]): str(item["sample_id"]) for item in plan["samples"]}
        migrated_sample_ids = list(samples_by_ref.values())
        migrated_mixture_ids = [str(item["mixture_id"]) for item in plan["mixtures"]]
        assert samples_by_ref == {
            migrated_specimen_uid(21): sample_id,
            migrated_specimen_uid(22): f"{'s' * 90}#legacy-22",
        }
        assert migrated_mixture_ids == sorted([mixture_id, f"{'m' * 90}#legacy-31"])
        assert all(len(value) <= 100 for value in migrated_sample_ids + migrated_mixture_ids)

        _run_downgrade(async_url, "p5q7r9s1t604")
        with sync_engine.connect() as connection:
            assert connection.execute(text("SELECT sample_id FROM sample ORDER BY id")).scalars().all() == [
                sample_id,
                f"{'s' * 90}#legacy-22",
            ]
            assert connection.execute(text("SELECT mixture_id FROM mixture ORDER BY id")).scalars().all() == [
                mixture_id,
                mixture_id,
            ]
        sync_engine.dispose()

    def test_downgrade_refuses_to_discard_changed_acquisition_plan(self, tmp_path):
        db_path = tmp_path / "changed-acquisition-plan.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)
        _run_upgrade(async_url, "p5q7r9s1t604")

        sync_engine = sa.create_engine(sync_url)
        with sync_engine.begin() as connection:
            connection.execute(text("INSERT INTO \"user\" (id, username) VALUES (1, 'chemist')"))
            connection.execute(
                text(
                    "INSERT INTO experiment (id, user_id, name, metadata_path) "
                    "VALUES (10, 1, 'Plate study', 'metadata.json')"
                )
            )
        _run_upgrade_head(async_url)
        with sync_engine.begin() as connection:
            import json

            document = {
                "schema_version": "spectrasherpa-acquisition-plan/3",
                "plate_format_id": "plate-96",
                "samples": [],
                "mixtures": [],
                "factors": [],
                "wells": [
                    {
                        "well_position": "A01",
                        "planned_sample_label": "new sample",
                        "sample_id": None,
                        "mixture_id": None,
                        "factor_values": {},
                    }
                ],
                "acquisition_order": [],
                "matching": {"rules": {}, "matches": []},
            }
            connection.execute(
                text("INSERT INTO acquisition_plan (experiment_id, document) VALUES (10, :document)"),
                {"document": json.dumps(document)},
            )

        with pytest.raises(RuntimeError, match="Cannot downgrade after complete acquisition plans changed"):
            _run_downgrade(async_url, "p5q7r9s1t604")

        assert "acquisition_plan" in set(sa_inspect(sync_engine).get_table_names())
        sync_engine.dispose()

    def test_precreated_active_table_is_populated_from_untracked_legacy_storage(self, tmp_path):
        db_path = tmp_path / "untracked-retired-doe.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)
        _run_upgrade(async_url, "p5q7r9s1t604")

        sync_engine = sa.create_engine(sync_url)
        with sync_engine.begin() as connection:
            connection.execute(text("INSERT INTO \"user\" (id, username) VALUES (1, 'chemist')"))
            connection.execute(
                text(
                    "INSERT INTO experiment (id, user_id, name, metadata_path) "
                    "VALUES (10, 1, 'Plate study', 'metadata.json')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO mixture (id, experiment_id, mixture_id, basis) "
                    "VALUES (20, 10, 'standard-1', 'volume')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO plate_well (id, experiment_id, well_position, mixture_id) " "VALUES (30, 10, 'A1', 20)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE acquisition_plan_well ("
                    "id INTEGER PRIMARY KEY, experiment_id INTEGER NOT NULL, "
                    "well_position VARCHAR(10) NOT NULL, planned_sample_label VARCHAR(100), "
                    "UNIQUE (experiment_id, well_position))"
                )
            )

        _run_upgrade_head(async_url)

        with sync_engine.connect() as connection:
            document = connection.execute(
                text("SELECT document FROM acquisition_plan WHERE experiment_id = 10")
            ).scalar_one()
            if isinstance(document, str):
                import json

                document = json.loads(document)
            assert document["wells"][0]["well_position"] == "A01"
            assert document["wells"][0]["planned_sample_label"] == "standard-1"
        sync_engine.dispose()

    def test_precreated_active_table_must_match_legacy_labels_exactly(self, tmp_path):
        db_path = tmp_path / "divergent-active-plan.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)
        _run_upgrade(async_url, "p5q7r9s1t604")

        sync_engine = sa.create_engine(sync_url)
        with sync_engine.begin() as connection:
            connection.execute(text("INSERT INTO \"user\" (id, username) VALUES (1, 'chemist')"))
            connection.execute(
                text(
                    "INSERT INTO experiment (id, user_id, name, metadata_path) "
                    "VALUES (10, 1, 'Plate study', 'metadata.json')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO mixture (id, experiment_id, mixture_id, basis) "
                    "VALUES (20, 10, 'legacy-label', 'volume')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO plate_well (id, experiment_id, well_position, mixture_id) " "VALUES (30, 10, 'A1', 20)"
                )
            )
            connection.execute(
                text(
                    "CREATE TABLE acquisition_plan_well ("
                    "id INTEGER PRIMARY KEY, experiment_id INTEGER NOT NULL, "
                    "well_position VARCHAR(10) NOT NULL, planned_sample_label VARCHAR(100), "
                    "UNIQUE (experiment_id, well_position))"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO acquisition_plan_well "
                    "(experiment_id, well_position, planned_sample_label) "
                    "VALUES (10, 'A01', 'different-label')"
                )
            )

        with pytest.raises(RuntimeError, match="active acquisition plan already differs"):
            _run_upgrade_head(async_url)
        sync_engine.dispose()


class TestBootstrapLegacyWithOldCustomAlgo:
    """Scenario: legacy DB with custom_algo created without CASCADE on user_id.

    After upgrade head, custom_algo should be dropped (migration a76d82a816bf).
    """

    def test_legacy_custom_algo_gets_dropped(self, tmp_path):
        db_path = tmp_path / "legacy_no_cascade.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)

        # Create minimal tables mimicking pre-CASCADE schema
        sync_engine = sa.create_engine(sync_url)
        with sync_engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE "user" (
                    id INTEGER PRIMARY KEY,
                    username VARCHAR(100) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    is_superuser BOOLEAN DEFAULT 0,
                    is_active BOOLEAN DEFAULT 1,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(text("""
                CREATE TABLE project (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES "user"(id),
                    name VARCHAR(255) NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            # custom_algo WITHOUT CASCADE on user_id
            conn.execute(text("""
                CREATE TABLE custom_algo (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER NOT NULL REFERENCES project(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES "user"(id),
                    name VARCHAR(255) NOT NULL,
                    slug VARCHAR(255) NOT NULL,
                    description TEXT,
                    code TEXT NOT NULL,
                    mode VARCHAR(20) NOT NULL DEFAULT 'simple',
                    icon VARCHAR(10) NOT NULL DEFAULT '🧪',
                    node_type VARCHAR(255) NOT NULL UNIQUE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))

        # Verify custom_algo exists before migration
        inspector = sa_inspect(sync_engine)
        assert "custom_algo" in inspector.get_table_names()

        # Run upgrade head — a76d82a816bf should drop custom_algo
        _run_upgrade_head(async_url)

        # Verify custom_algo has been dropped
        inspector = sa_inspect(sync_engine)
        assert "custom_algo" not in inspector.get_table_names()

        sync_engine.dispose()


class TestTrackedLegacyAuthSplit:
    """Scenario: tracked DB still has the pre-split user.password_hash constraint."""

    def test_upgrade_head_unblocks_legacy_user_insert(self, tmp_path):
        db_path = tmp_path / "tracked_legacy_auth.db"
        sync_url = _sync_url(db_path)
        async_url = _async_url(db_path)

        sync_engine = sa.create_engine(sync_url)
        with sync_engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE "user" (
                    id INTEGER PRIMARY KEY,
                    username VARCHAR(100) NOT NULL UNIQUE,
                    password_hash VARCHAR(255) NOT NULL,
                    is_superuser BOOLEAN NOT NULL DEFAULT 0,
                    api_key_hash VARCHAR(255),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    email VARCHAR(255),
                    last_active DATETIME,
                    last_login_at DATETIME,
                    login_count INTEGER NOT NULL DEFAULT 0
                )
            """))
            conn.execute(text("""
                CREATE TABLE alembic_version (
                    version_num VARCHAR(32) NOT NULL PRIMARY KEY
                )
            """))
            conn.execute(text("""
                INSERT INTO alembic_version (version_num)
                VALUES ('r8s0t2u4v037')
            """))

        with Session(sync_engine) as session:
            session.add(User(username="before-upgrade"))
            with pytest.raises(SQLAlchemyError):
                session.flush()
            session.rollback()

        _run_upgrade_head(async_url)

        inspector = sa_inspect(sync_engine)
        columns = {column["name"]: column for column in inspector.get_columns("user")}
        assert columns["password_hash"]["nullable"] is True
        assert columns["is_superuser"]["nullable"] is True
        assert columns["login_count"]["nullable"] is True
        assert columns["email"]["nullable"] is True
        assert columns["principal_kind"]["nullable"] is False

        with Session(sync_engine) as session:
            user = User(username="after-upgrade")
            session.add(user)
            session.flush()
            row = (
                session.execute(
                    text("""
                    SELECT username, principal_kind, password_hash, is_superuser, login_count
                    FROM "user"
                    WHERE username = :username
                    """),
                    {"username": "after-upgrade"},
                )
                .mappings()
                .one()
            )
            assert row["username"] == "after-upgrade"
            assert row["principal_kind"] == "human"
            assert row["password_hash"] is None
            assert row["is_superuser"] in (None, 0, False)
            assert row["login_count"] in (None, 0)
            session.rollback()

        sync_engine.dispose()


class TestLegacyAuthDefaults:
    """Validate the narrower production hotfix behavior directly."""

    def test_password_hash_relaxation_alone_unblocks_current_user_insert(self, tmp_path):
        db_path = tmp_path / "legacy_defaults.db"
        sync_engine = sa.create_engine(_sync_url(db_path))

        with sync_engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE "user" (
                    id INTEGER PRIMARY KEY,
                    username VARCHAR(100) NOT NULL UNIQUE,
                    principal_kind VARCHAR(32) NOT NULL DEFAULT 'human',
                    password_hash VARCHAR(255),
                    is_superuser BOOLEAN NOT NULL DEFAULT 0,
                    api_key_hash VARCHAR(255),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    email VARCHAR(255),
                    last_active DATETIME,
                    last_login_at DATETIME,
                    login_count INTEGER NOT NULL DEFAULT 0
                )
            """))

        with Session(sync_engine) as session:
            session.add(User(username="password-hash-only"))
            session.flush()
            row = (
                session.execute(
                    text("""
                    SELECT principal_kind, password_hash, is_superuser, login_count
                    FROM "user"
                    WHERE username = :username
                    """),
                    {"username": "password-hash-only"},
                )
                .mappings()
                .one()
            )
            assert row["principal_kind"] == "human"
            assert row["password_hash"] is None
            assert row["is_superuser"] == 0
            assert row["login_count"] == 0
            session.rollback()

        sync_engine.dispose()


@pytest.mark.parametrize(
    "url", ["sqlite+aiosqlite:///D%3A%5Cdata%5Ctest.db", "sqlite+aiosqlite:////tmp/100%25/test.db"]
)
def test_alembic_config_preserves_escaped_database_urls(monkeypatch, url):
    from types import SimpleNamespace

    from spectra_sherpa.app.db import init_db as module

    monkeypatch.setattr(module, "engine", SimpleNamespace(url=sa.engine.make_url(url)))
    received = []
    monkeypatch.setattr(
        command, "upgrade", lambda cfg, revision: received.append(cfg.get_main_option("sqlalchemy.url"))
    )
    asyncio.run(module._run_alembic("upgrade", "head"))
    assert received == [sa.engine.make_url(url).render_as_string(hide_password=False)]


def test_full_upgrade_opens_legacy_classifier_profile_without_changing_source_files(tmp_path):
    """An untracked pip profile reaches head with all classifier identities intact."""
    import hashlib

    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.models.workflow_node import WorkflowNode

    db_path = tmp_path / "classifiers.db"
    sync_engine = sa.create_engine(_sync_url(db_path))
    Base.metadata.create_all(sync_engine)
    with Session(sync_engine) as session:
        user = User(username="classifier-upgrade-chemist")
        session.add(user)
        session.flush()
        workflow = Workflow(user_id=user.id, name="Existing classification", purpose="analysis")
        session.add(workflow)
        session.flush()
        for index, kind in enumerate(("knn", "plsda", "simca"), 1):
            session.add(
                WorkflowNode(
                    workflow_id=workflow.id,
                    node_id=f"classifier-{index}",
                    node_type=f"classification.{kind}",
                    parameters={"cv_folds": 5} if index != 1 else {},
                )
            )
        session.commit()
    files = {}
    for relative in ("experiments/source.csv", "user/models/model.bin", "exports/python/result.py"):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic retained asset\n")
        files[relative] = (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest())

    _run_upgrade_head(_async_url(db_path))
    with sync_engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            ScriptDirectory.from_config(_alembic_cfg()).get_current_head()
        )
        rows = conn.execute(
            text("SELECT node_id, node_type, parameters, annotation FROM workflow_node ORDER BY node_id")
        ).all()
        assert [(row.node_id, row.node_type) for row in rows] == [
            (f"classifier-{index}", f"classification.{kind}") for index, kind in enumerate(("knn", "plsda", "simca"), 1)
        ]
        assert all('"cv_folds"' not in row.parameters for row in rows)
        assert all("not cross-validation evidence" in row.annotation for row in rows)
    for relative, expected in files.items():
        path = tmp_path / relative
        assert (path.stat().st_size, hashlib.sha256(path.read_bytes()).hexdigest()) == expected
    sync_engine.dispose()
