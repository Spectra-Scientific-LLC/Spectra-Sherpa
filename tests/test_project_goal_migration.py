"""The project goal migration adds and removes the goal columns."""

import sqlalchemy as sa


def _project_columns(database) -> set[str]:
    engine = sa.create_engine(f"sqlite:///{database}")
    try:
        return {column["name"] for column in sa.inspect(engine).get_columns("project")}
    finally:
        engine.dispose()


def test_project_goal_columns_upgrade_and_downgrade(tmp_path):
    from tests.test_init_db_bootstrap import _run_downgrade, _run_upgrade

    database = tmp_path / "goal.db"
    url = f"sqlite+aiosqlite:///{database}"
    _run_upgrade(url, "m2n4o6p8q660")
    assert not {"goal", "goal_plan"} & _project_columns(database)

    _run_upgrade(url, "n3o5p7q9r661")
    assert {"goal", "goal_plan"} <= _project_columns(database)

    _run_downgrade(url, "m2n4o6p8q660")
    assert not {"goal", "goal_plan"} & _project_columns(database)
