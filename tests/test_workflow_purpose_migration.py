"""Round-trip the workflow-purpose migration against a real SQLite schema."""

from __future__ import annotations

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError


def _config() -> Config:
    from spectra_sherpa._paths import get_package_root

    package_root = get_package_root()
    config = Config(str(package_root / "alembic.ini"))
    config.set_main_option("script_location", str(package_root / "alembic"))
    config.set_main_option("_skip_logging_config", "true")
    return config


def _migrate(path: Path, revision: str) -> None:
    from spectra_sherpa.app.core.config import settings

    original = settings.database_url
    object.__setattr__(settings, "database_url", f"sqlite+aiosqlite:///{path}")
    try:
        command.upgrade(_config(), revision)
    finally:
        object.__setattr__(settings, "database_url", original)


def test_workflow_purpose_backfill_constraint_and_downgrade(tmp_path: Path):
    path = tmp_path / "purpose.db"
    _migrate(path, "g5d9e3b1f624")
    engine = sa.create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO user (username) VALUES ('migration-owner')"))
        connection.execute(
            sa.text(
                "INSERT INTO workflow (user_id, name, status, color_source, sheet_order) "
                "VALUES (1, 'Existing analysis', 'draft', 'blank', 0)"
            )
        )

    _migrate(path, "h6e0f4c2a735")
    with engine.begin() as connection:
        assert connection.scalar(sa.text("SELECT purpose FROM workflow")) == "analysis"
        with pytest.raises(IntegrityError):
            connection.execute(
                sa.text(
                    "INSERT INTO workflow "
                    "(user_id, name, status, color_source, sheet_order, purpose) "
                    "VALUES (1, 'Invalid', 'draft', 'blank', 1, 'hidden_guess')"
                )
            )

    from spectra_sherpa.app.core.config import settings

    original = settings.database_url
    object.__setattr__(settings, "database_url", f"sqlite+aiosqlite:///{path}")
    try:
        command.downgrade(_config(), "g5d9e3b1f624")
    finally:
        object.__setattr__(settings, "database_url", original)
    engine.dispose()
    engine = sa.create_engine(f"sqlite:///{path}")
    assert "purpose" not in {column["name"] for column in sa.inspect(engine).get_columns("workflow")}
    engine.dispose()
