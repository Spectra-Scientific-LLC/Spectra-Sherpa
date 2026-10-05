from __future__ import annotations

import json

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from spectra_sherpa.alembic.versions import l1m3n5o7p159_retire_classifier_local_cv as rev
from spectra_sherpa.app.db.sqlite_migration import migration_transaction


def _run_upgrade(conn):
    with Operations.context(MigrationContext.configure(conn)):
        rev.upgrade()


def _records(conn, table):
    return [dict(row) for row in conn.execute(sa.text(f'SELECT * FROM "{table}" ORDER BY id')).mappings()]


@pytest.fixture
def database(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'profile.db'}")
    with engine.begin() as conn:
        conn.execute(
            sa.text("CREATE TABLE workflow (id INTEGER PRIMARY KEY, notes TEXT, status TEXT, integrity_hash TEXT)")
        )
        conn.execute(
            sa.text(
                "CREATE TABLE workflow_node (id INTEGER PRIMARY KEY, workflow_id INTEGER, "
                "node_id TEXT, node_type TEXT, parameters JSON, annotation TEXT)"
            )
        )
        conn.execute(sa.text("INSERT INTO workflow VALUES (1, 'Scientist notes', 'active', 'old-digest')"))
        conn.execute(sa.text("INSERT INTO workflow VALUES (2, 'Unrelated', 'active', 'other-digest')"))
        for table in ("workflow_edge", "workflow_version", "execution_run", "model_artifact"):
            conn.execute(sa.text(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, payload TEXT)'))
            conn.execute(
                sa.text(f'INSERT INTO "{table}" VALUES (1, :payload)'),
                {"payload": json.dumps({"cv_folds": 5, "node_id": "classifier", "scope": "historical"})},
            )
        conn.execute(
            sa.text("INSERT INTO workflow_node VALUES (100, 2, 'pca', 'model.pca', :parameters, 'Keep me')"),
            {"parameters": json.dumps({"n_components": 3})},
        )
    yield engine
    engine.dispose()


def _insert(conn, node_type, parameters):
    conn.execute(
        sa.text("INSERT INTO workflow_node VALUES (5, 1, 'classifier', :type, :params, 'Original annotation')"),
        {"type": node_type, "params": json.dumps(parameters)},
    )


@pytest.mark.parametrize("node_type", rev._CLASSIFIERS)
@pytest.mark.parametrize(
    "parameters",
    [
        {"n_components": 2},
        {"n_components": 2, "cv_folds": 5},
        {"n_components": 2, "cv_folds": "5"},
        {"n_components": 2, "cv_folds": None},
        {"n_components": 2, "cv_folds": 1.5},
        {"n_components": 2, "cv_folds": {"malformed": True}},
    ],
)
def test_upgrade_preserves_graph_history_and_records_retired_input(database, node_type, parameters):
    with database.begin() as conn:
        _insert(conn, node_type, parameters)
    with database.connect() as conn:
        before = {
            table: _records(conn, table)
            for table in ("workflow_edge", "workflow_version", "execution_run", "model_artifact")
        }
        unrelated_node = _records(conn, "workflow_node")[-1]
        unrelated_workflow = _records(conn, "workflow")[-1]
        conn.commit()
        with migration_transaction(conn):
            _run_upgrade(conn)
        row = _records(conn, "workflow_node")[0]
        assert row["id"] == 5 and row["node_id"] == "classifier" and row["node_type"] == node_type
        assert json.loads(row["parameters"]) == {k: v for k, v in parameters.items() if k != "cv_folds"}
        assert row["annotation"].startswith("Original annotation\n\n")
        assert rev._NOTICE in row["annotation"]
        original = json.dumps(parameters["cv_folds"]) if "cv_folds" in parameters else "not explicitly stored"
        assert f"Original cv_folds: {original}" in row["annotation"]
        workflow = _records(conn, "workflow")[0]
        assert workflow["notes"].startswith("Scientist notes\n\n")
        assert workflow["status"] == "draft" and workflow["integrity_hash"] is None
        for table, rows in before.items():
            assert _records(conn, table) == rows
        assert _records(conn, "workflow_node")[-1] == unrelated_node
        assert _records(conn, "workflow")[-1] == unrelated_workflow
        after = (_records(conn, "workflow_node"), _records(conn, "workflow"))
        conn.commit()
        with migration_transaction(conn):
            _run_upgrade(conn)
        assert (_records(conn, "workflow_node"), _records(conn, "workflow")) == after


def test_interruption_rolls_back_all_changes_and_retry_succeeds(database):
    with database.begin() as conn:
        _insert(conn, "classification.knn", {"cv_folds": 5, "n_neighbors": 3})
    with database.connect() as conn:
        before = (_records(conn, "workflow_node"), _records(conn, "workflow"))
        conn.commit()
        with pytest.raises(KeyboardInterrupt):
            with migration_transaction(conn):
                _run_upgrade(conn)
                raise KeyboardInterrupt("simulated interruption before commit")
        assert (_records(conn, "workflow_node"), _records(conn, "workflow")) == before
        conn.commit()
        with migration_transaction(conn):
            _run_upgrade(conn)
        assert "cv_folds" not in json.loads(_records(conn, "workflow_node")[0]["parameters"])


def test_upgrade_notice_is_exposed_to_workflow_ui():
    from spectra_sherpa.app.schemas.workflows import WorkflowDetail

    workflow = WorkflowDetail.model_construct(notes=f"Scientist notes\n{rev._MARKER}\n{rev._NOTICE}")
    assert workflow.warnings == [rev._NOTICE]
    assert WorkflowDetail.model_construct(notes="Ordinary notes").warnings == []
