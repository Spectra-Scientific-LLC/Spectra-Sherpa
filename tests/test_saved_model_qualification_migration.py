"""The saved-model history migration accepts only an exact metadata bootstrap."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import sqlalchemy as sa

from spectra_sherpa.alembic.versions import m2n4o6p8q660_saved_model_qualification as migration
from spectra_sherpa.app import models  # noqa: F401  # Populate the bootstrap metadata.
from spectra_sherpa.app.db.base import Base


def test_current_bootstrap_shape_is_accepted_and_retained(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'qualification.db'}")
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            table = Base.metadata.tables["saved_model_qualification_record"]
            connection.execute(
                table.insert().values(
                    user_id=1,
                    project_id=1,
                    artifact_uid="synthetic-artifact",
                    record_digest="a" * 64,
                    kind="assessment",
                    model_integrity_hash="b" * 64,
                    manifest_digest="c" * 64,
                    application_plan_digest="d" * 64,
                    validation_view_id=1,
                    validation_view_digest="e" * 64,
                    payload={"synthetic": True},
                )
            )
            migration._validate_existing_table(sa.inspect(connection))
            assert connection.scalar(sa.select(sa.func.count()).select_from(table)) == 1
    finally:
        engine.dispose()


def test_partial_bootstrap_is_refused(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'partial.db'}")
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(sa.text("DROP INDEX ix_saved_model_qualification_record_artifact_uid"))
            with pytest.raises(RuntimeError, match="artifact_uid index"):
                migration._validate_existing_table(sa.inspect(connection))
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "missing,dialect,expected",
    [
        ("created_at", "sqlite", "created_at server default"),
        ("id", "postgresql", "id generator"),
    ],
)
def test_missing_generated_default_is_refused(tmp_path, missing, dialect, expected):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'defaults.db'}")
    try:
        Base.metadata.create_all(engine)
        with engine.connect() as connection:
            inspector = sa.inspect(connection)
            reflected = deepcopy(inspector.get_columns("saved_model_qualification_record"))
            next(column for column in reflected if column["name"] == missing)["default"] = None
            probe = Mock(wraps=inspector)
            probe.get_columns.return_value = reflected
            probe.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect))
            with pytest.raises(RuntimeError, match=expected):
                migration._validate_existing_table(probe)
    finally:
        engine.dispose()
