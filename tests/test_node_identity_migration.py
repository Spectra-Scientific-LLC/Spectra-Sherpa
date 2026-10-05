from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from spectra_sherpa.alembic.versions import s8t0u2v4w137_canonical_node_identities as rev
from spectra_sherpa.app.services.dag.integrity import compute_workflow_hash


def _run_upgrade(conn: sa.engine.Connection) -> None:
    operations = Operations(MigrationContext.configure(conn))
    original_op = rev.op
    rev.op = operations
    try:
        rev.upgrade()
    finally:
        rev.op = original_op


def _run_downgrade(conn: sa.engine.Connection) -> None:
    operations = Operations(MigrationContext.configure(conn))
    original_op = rev.op
    rev.op = operations
    try:
        rev.downgrade()
    finally:
        rev.op = original_op


def _digest(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    ).hexdigest()


def test_migration_rewrites_live_nodes_and_nested_workflow_snapshots(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'node-identities.sqlite'}")
    workflow_snapshot = {
        "nodes": [
            {
                "node_id": "pls",
                "node_type": "model.fitted_pls_v2",
                "label": "model.fitted_pls_v2",
                "parameters": {},
            }
        ]
    }
    project_snapshot = {
        "workflows": [workflow_snapshot],
        "children": [
            {
                "workflows": [
                    {
                        "nodes": [
                            {
                                "node_id": "score",
                                "node_type": "diagnostics.regression_evaluator_v2",
                                "parameters": {},
                            }
                        ]
                    }
                ]
            }
        ],
    }

    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE workflow (id INTEGER PRIMARY KEY, integrity_hash VARCHAR(64)); "))
        conn.execute(
            sa.text(
                "CREATE TABLE workflow_node ("
                "id INTEGER PRIMARY KEY, workflow_id INTEGER, node_id VARCHAR(255), "
                "node_type VARCHAR(255), parameters JSON)"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE workflow_edge ("
                "workflow_id INTEGER, from_node_id VARCHAR(255), to_node_id VARCHAR(255), "
                "from_output VARCHAR(255), to_input VARCHAR(255))"
            )
        )
        conn.execute(sa.text("CREATE TABLE workflow_version (id INTEGER PRIMARY KEY, snapshot JSON NOT NULL)"))
        conn.execute(sa.text("CREATE TABLE project_version (id INTEGER PRIMARY KEY, snapshot JSON NOT NULL)"))
        legacy_hash = rev._workflow_hash(
            [
                {
                    "node_id": "score",
                    "node_type": "diagnostics.classification_evaluator_v2",
                    "parameters": {},
                }
            ],
            [],
        )
        conn.execute(
            sa.text("INSERT INTO workflow (id, integrity_hash) VALUES (7, :integrity_hash)"),
            {"integrity_hash": legacy_hash},
        )
        conn.execute(
            sa.text(
                "INSERT INTO workflow_node (id, workflow_id, node_id, node_type, parameters) VALUES "
                "(1, 7, 'score', :legacy, '{}'), (2, 8, 'pca', 'model.pca', '{}')"
            ),
            {"legacy": "diagnostics.classification_evaluator_v2"},
        )
        conn.execute(
            sa.text("INSERT INTO workflow_version (id, snapshot) VALUES (1, :snapshot)"),
            {"snapshot": json.dumps(workflow_snapshot)},
        )
        conn.execute(
            sa.text("INSERT INTO project_version (id, snapshot) VALUES (1, :snapshot)"),
            {"snapshot": json.dumps(project_snapshot)},
        )

        _run_upgrade(conn)

        node_types = conn.execute(sa.text("SELECT node_type FROM workflow_node ORDER BY id")).scalars().all()
        workflow_hash = conn.execute(sa.text("SELECT integrity_hash FROM workflow WHERE id = 7")).scalar_one()
        migrated_workflow = json.loads(conn.execute(sa.text("SELECT snapshot FROM workflow_version")).scalar_one())
        migrated_project = json.loads(conn.execute(sa.text("SELECT snapshot FROM project_version")).scalar_one())

    assert node_types == ["diagnostics.classification_evaluator", "model.pca"]
    assert workflow_hash == compute_workflow_hash(
        [{"node_id": "score", "node_type": "diagnostics.classification_evaluator", "parameters": {}}],
        [],
    )
    assert migrated_workflow["nodes"][0]["node_type"] == "model.fitted_pls"
    assert migrated_workflow["nodes"][0]["label"] == "model.fitted_pls_v2"
    assert migrated_project["children"][0]["workflows"][0]["nodes"][0]["node_type"] == (
        "diagnostics.regression_evaluator"
    )


def test_migration_tolerates_partial_bootstrap_databases(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'partial.sqlite'}")
    with engine.begin() as conn:
        _run_upgrade(conn)


def test_migration_tolerates_present_tables_with_partial_columns(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'partial-columns.sqlite'}")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE workflow (id INTEGER PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE workflow_node (workflow_id INTEGER, node_type VARCHAR(255))"))
        conn.execute(sa.text("CREATE TABLE workflow_edge (workflow_id INTEGER)"))
        conn.execute(sa.text("CREATE TABLE workflow_version (id INTEGER PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE project_version (snapshot JSON)"))
        conn.execute(
            sa.text("INSERT INTO workflow_node (workflow_id, node_type) VALUES (1, :node_type)"),
            {"node_type": "model.fitted_pls_v2"},
        )

        _run_upgrade(conn)

        assert conn.execute(sa.text("SELECT node_type FROM workflow_node")).scalar_one() == "model.fitted_pls"


def test_migration_refuses_to_resign_an_invalid_legacy_snapshot(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'corrupt-snapshot.sqlite'}")
    snapshot = {
        "nodes": [{"node_id": "fit", "node_type": "model.fitted_pls_v2", "parameters": {}}],
        "edges": [],
        "integrity_hash": "0" * 64,
    }
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE workflow_version (id INTEGER PRIMARY KEY, snapshot JSON NOT NULL)"))
        conn.execute(
            sa.text("INSERT INTO workflow_version (id, snapshot) VALUES (1, :snapshot)"),
            {"snapshot": json.dumps(snapshot)},
        )

        with pytest.raises(RuntimeError, match="invalid integrity hash"):
            _run_upgrade(conn)


def test_migration_updates_artifact_and_replay_bindings_and_round_trips(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'bound-application.sqlite'}")
    source_digest = "ac05f06a069e5551f5cd101dbaec0d40ff352860b360a98e367e1f17dbbaf98d"
    old_application_digest = "efee828721a2fa29dc3ddb8b0737a9fcd72d45830b5c9db391438cdd4f087baa"
    binding = {
        "artifact_digest": "a" * 64,
        "state_node_id": "apply",
        "state_digest": "b" * 64,
        "state_content_digest": "c" * 64,
        "serializer": "spectra.sherpa-simpls-regression-json/6",
        "source_contract_digest": source_digest,
    }
    legacy_nodes = [
        {"node_id": "canonical-local-source", "node_type": "deploy.input", "parameters": {}},
        {"node_id": "apply", "node_type": "model.apply_fitted_pls_v2", "parameters": binding},
    ]
    edges = [
        {
            "from_node_id": "canonical-local-source",
            "to_node_id": "apply",
            "from_output": "default",
            "to_input": "default",
        }
    ]
    old_workflow_hash = rev._workflow_hash(legacy_nodes, edges)
    old_application_hash = rev._workflow_hash(legacy_nodes[1:], [])
    unsigned_plan = {
        "nodes": [
            {
                "node_id": "apply",
                "source_operation_id": "model.fitted_pls_v2",
                "source_contract_digest": source_digest,
                "application_operation_id": "model.apply_fitted_pls_v2",
                "application_contract_digest": old_application_digest,
                "artifact_binding": binding,
                "parameters": {},
            }
        ],
        "edges": [],
    }
    legacy_plan = {**unsigned_plan, "application_plan_digest": _digest(unsigned_plan)}
    snapshot = {"nodes": legacy_nodes, "edges": edges, "integrity_hash": old_workflow_hash}

    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE workflow (id INTEGER PRIMARY KEY, integrity_hash VARCHAR(64))"))
        conn.execute(
            sa.text(
                "CREATE TABLE workflow_node (workflow_id INTEGER, node_id VARCHAR(255), "
                "node_type VARCHAR(255), parameters JSON)"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE workflow_edge (workflow_id INTEGER, from_node_id VARCHAR(255), "
                "to_node_id VARCHAR(255), from_output VARCHAR(255), to_input VARCHAR(255))"
            )
        )
        conn.execute(sa.text("CREATE TABLE execution_run (workflow_id INTEGER, integrity_hash VARCHAR(64))"))
        conn.execute(sa.text("CREATE TABLE workflow_version (id INTEGER PRIMARY KEY, snapshot JSON NOT NULL)"))
        conn.execute(
            sa.text(
                "CREATE TABLE canonical_project_artifact (id INTEGER PRIMARY KEY, workflow_id INTEGER, "
                "application_plan_digest VARCHAR(64), application_plan_payload JSON, "
                "application_integrity_hash VARCHAR(64))"
            )
        )
        conn.execute(
            sa.text("INSERT INTO workflow (id, integrity_hash) VALUES (7, :integrity_hash)"),
            {"integrity_hash": old_workflow_hash},
        )
        for node in legacy_nodes:
            conn.execute(
                sa.text(
                    "INSERT INTO workflow_node (workflow_id, node_id, node_type, parameters) "
                    "VALUES (7, :node_id, :node_type, :parameters)"
                ),
                {**node, "parameters": json.dumps(node["parameters"])},
            )
        conn.execute(
            sa.text(
                "INSERT INTO workflow_edge (workflow_id, from_node_id, to_node_id, from_output, to_input) "
                "VALUES (7, :from_node_id, :to_node_id, :from_output, :to_input)"
            ),
            edges[0],
        )
        conn.execute(
            sa.text(
                "INSERT INTO execution_run (workflow_id, integrity_hash) VALUES "
                "(7, :current_hash), (7, :historical_hash)"
            ),
            {"current_hash": old_workflow_hash, "historical_hash": "d" * 64},
        )
        conn.execute(
            sa.text("INSERT INTO workflow_version (id, snapshot) VALUES (1, :snapshot)"),
            {"snapshot": json.dumps(snapshot)},
        )
        conn.execute(
            sa.text(
                "INSERT INTO canonical_project_artifact "
                "(id, workflow_id, application_plan_digest, application_plan_payload, application_integrity_hash) "
                "VALUES (1, 7, :plan_digest, :plan, :application_hash)"
            ),
            {
                "plan_digest": legacy_plan["application_plan_digest"],
                "plan": json.dumps(legacy_plan),
                "application_hash": old_application_hash,
            },
        )

        _run_upgrade(conn)

        canonical_nodes = deepcopy(legacy_nodes)
        canonical_nodes[1]["node_type"] = "model.apply_fitted_pls"
        canonical_hash = rev._workflow_hash(canonical_nodes, edges)
        assert conn.execute(sa.text("SELECT integrity_hash FROM workflow")).scalar_one() == canonical_hash
        assert conn.execute(sa.text("SELECT integrity_hash FROM execution_run ORDER BY rowid")).scalars().all() == [
            canonical_hash,
            "d" * 64,
        ]
        migrated_plan = json.loads(
            conn.execute(sa.text("SELECT application_plan_payload FROM canonical_project_artifact")).scalar_one()
        )
        assert migrated_plan["nodes"][0]["source_operation_id"] == "model.fitted_pls"
        assert migrated_plan["nodes"][0]["application_operation_id"] == "model.apply_fitted_pls"
        assert migrated_plan["nodes"][0]["source_contract_digest"] == source_digest
        assert migrated_plan["nodes"][0]["artifact_binding"]["source_contract_digest"] == source_digest
        assert migrated_plan["nodes"][0]["application_contract_digest"] == rev._CURRENT_PLS_APPLICATION_DIGEST
        assert migrated_plan["application_plan_digest"] == _digest(
            {key: value for key, value in migrated_plan.items() if key != "application_plan_digest"}
        )
        artifact_row = conn.execute(
            sa.text("SELECT application_plan_digest, application_integrity_hash FROM canonical_project_artifact")
        ).one()
        assert artifact_row[0] == migrated_plan["application_plan_digest"]
        assert artifact_row[1] == rev._workflow_hash([canonical_nodes[1]], [])
        migrated_snapshot = json.loads(conn.execute(sa.text("SELECT snapshot FROM workflow_version")).scalar_one())
        assert migrated_snapshot["integrity_hash"] == canonical_hash

        _run_downgrade(conn)

        assert conn.execute(sa.text("SELECT integrity_hash FROM workflow")).scalar_one() == old_workflow_hash
        assert conn.execute(sa.text("SELECT integrity_hash FROM execution_run ORDER BY rowid")).scalars().all() == [
            old_workflow_hash,
            "d" * 64,
        ]
        restored_plan = json.loads(
            conn.execute(sa.text("SELECT application_plan_payload FROM canonical_project_artifact")).scalar_one()
        )
        assert restored_plan == legacy_plan
        restored_snapshot = json.loads(conn.execute(sa.text("SELECT snapshot FROM workflow_version")).scalar_one())
        assert restored_snapshot == snapshot


def test_application_plan_migration_requires_exact_legacy_contract_pair() -> None:
    source_digest = "ac05f06a069e5551f5cd101dbaec0d40ff352860b360a98e367e1f17dbbaf98d"
    unsigned = {
        "nodes": [
            {
                "node_id": "apply",
                "source_operation_id": "model.fitted_pls_v2",
                "source_contract_digest": source_digest,
                "application_operation_id": "model.apply_fitted_pls_v2",
                "application_contract_digest": "0" * 64,
                "artifact_binding": {"source_contract_digest": source_digest},
                "parameters": {},
            }
        ],
        "edges": [],
    }
    plan = {**unsigned, "application_plan_digest": _digest(unsigned)}

    with pytest.raises(RuntimeError, match="invalid contract bindings"):
        rev._rewrite_application_plan(plan, downgrade=False)


@pytest.mark.parametrize(
    ("corrupt_column", "message"),
    [
        ("application_plan_digest", "mismatched application plan digest"),
        ("application_integrity_hash", "invalid application integrity hash"),
    ],
)
def test_artifact_migration_refuses_mismatched_persisted_custody(tmp_path, corrupt_column, message) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / f'{corrupt_column}.sqlite'}")
    source_digest = "ac05f06a069e5551f5cd101dbaec0d40ff352860b360a98e367e1f17dbbaf98d"
    application_digest = "efee828721a2fa29dc3ddb8b0737a9fcd72d45830b5c9db391438cdd4f087baa"
    binding = {
        "artifact_digest": "a" * 64,
        "state_node_id": "apply",
        "state_digest": "b" * 64,
        "state_content_digest": "c" * 64,
        "serializer": "spectra.sherpa-simpls-regression-json/6",
        "source_contract_digest": source_digest,
    }
    nodes = [
        {"node_id": "canonical-local-source", "node_type": "deploy.input", "parameters": {}},
        {"node_id": "apply", "node_type": "model.apply_fitted_pls_v2", "parameters": binding},
    ]
    edges = [
        {
            "from_node_id": "canonical-local-source",
            "to_node_id": "apply",
            "from_output": "default",
            "to_input": "default",
        }
    ]
    unsigned_plan = {
        "nodes": [
            {
                "node_id": "apply",
                "source_operation_id": "model.fitted_pls_v2",
                "source_contract_digest": source_digest,
                "application_operation_id": "model.apply_fitted_pls_v2",
                "application_contract_digest": application_digest,
                "artifact_binding": binding,
                "parameters": {},
            }
        ],
        "edges": [],
    }
    plan = {**unsigned_plan, "application_plan_digest": _digest(unsigned_plan)}
    columns = {
        "application_plan_digest": plan["application_plan_digest"],
        "application_integrity_hash": rev._workflow_hash(nodes[1:], []),
    }
    columns[corrupt_column] = "0" * 64

    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE workflow (id INTEGER PRIMARY KEY, integrity_hash VARCHAR(64))"))
        conn.execute(
            sa.text(
                "CREATE TABLE workflow_node (workflow_id INTEGER, node_id VARCHAR(255), "
                "node_type VARCHAR(255), parameters JSON)"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE workflow_edge (workflow_id INTEGER, from_node_id VARCHAR(255), "
                "to_node_id VARCHAR(255), from_output VARCHAR(255), to_input VARCHAR(255))"
            )
        )
        conn.execute(
            sa.text(
                "CREATE TABLE canonical_project_artifact (id INTEGER PRIMARY KEY, workflow_id INTEGER, "
                "application_plan_digest VARCHAR(64), application_plan_payload JSON, "
                "application_integrity_hash VARCHAR(64))"
            )
        )
        conn.execute(
            sa.text("INSERT INTO workflow VALUES (7, :integrity_hash)"),
            {"integrity_hash": rev._workflow_hash(nodes, edges)},
        )
        for node in nodes:
            conn.execute(
                sa.text(
                    "INSERT INTO workflow_node (workflow_id, node_id, node_type, parameters) "
                    "VALUES (7, :node_id, :node_type, :parameters)"
                ),
                {**node, "parameters": json.dumps(node["parameters"])},
            )
        conn.execute(
            sa.text(
                "INSERT INTO workflow_edge (workflow_id, from_node_id, to_node_id, from_output, to_input) "
                "VALUES (7, :from_node_id, :to_node_id, :from_output, :to_input)"
            ),
            edges[0],
        )
        conn.execute(
            sa.text(
                "INSERT INTO canonical_project_artifact VALUES "
                "(1, 7, :application_plan_digest, :payload, :application_integrity_hash)"
            ),
            {**columns, "payload": json.dumps(plan)},
        )

        with pytest.raises(RuntimeError, match=message):
            _run_upgrade(conn)


def test_downgrade_refuses_artifacts_created_with_the_canonical_contract(tmp_path) -> None:
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'unsafe-downgrade.sqlite'}")
    plan = {
        "nodes": [
            {
                "source_operation_id": "model.fitted_pls",
                "source_contract_digest": rev._CURRENT_PLS_SOURCE_DIGEST,
            }
        ]
    }
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE canonical_project_artifact (id INTEGER PRIMARY KEY, workflow_id INTEGER, "
                "application_plan_digest VARCHAR(64), application_plan_payload JSON, "
                "application_integrity_hash VARCHAR(64))"
            )
        )
        conn.execute(
            sa.text("INSERT INTO canonical_project_artifact VALUES (1, 7, :digest, :payload, :integrity_hash)"),
            {"digest": "a" * 64, "payload": json.dumps(plan), "integrity_hash": "b" * 64},
        )

        with pytest.raises(RuntimeError, match="created after this migration"):
            _run_downgrade(conn)
