import json

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from spectra_sherpa.alembic.versions import g6h8i0j2k434_merge_peak_summary_port as rev


@pytest.mark.parametrize("starting_revision", ["g6h8i0j2k434", "g6h8i0j2k444"])
def test_peak_and_config_branches_upgrade_to_one_head(tmp_path, starting_revision):
    from alembic.script import ScriptDirectory

    from tests.test_init_db_bootstrap import _alembic_cfg, _run_upgrade

    database = tmp_path / "branches.db"
    url = f"sqlite+aiosqlite:///{database}"
    _run_upgrade(url, starting_revision)
    _run_upgrade(url, "head")
    scripts = ScriptDirectory.from_config(_alembic_cfg())
    assert scripts.get_heads() == ["j9k1l3m5n657"]
    engine = sa.create_engine(f"sqlite:///{database}")
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalars().all() == [
            "j9k1l3m5n657"
        ]
    engine.dispose()


@pytest.mark.parametrize("duplicate", [False, True])
def test_peak_connections_migrate_without_rewriting_history(duplicate):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE workflow (id INTEGER PRIMARY KEY, integrity_hash TEXT)"))
        conn.execute(
            sa.text("CREATE TABLE workflow_node (workflow_id INTEGER, node_id TEXT, node_type TEXT, parameters JSON)")
        )
        conn.execute(
            sa.text(
                "CREATE TABLE workflow_edge (workflow_id INTEGER, from_node_id TEXT, to_node_id TEXT, "
                "from_output TEXT, to_input TEXT)"
            )
        )
        conn.execute(sa.text("INSERT INTO workflow VALUES (1, NULL)"))
        for node_id, node_type in [
            ("peak", "analysis.peak_finding"),
            ("table", "output.data_table"),
            ("other", "other.producer"),
        ]:
            conn.execute(
                sa.text("INSERT INTO workflow_node VALUES (1, :id, :type, '{}')"), {"id": node_id, "type": node_type}
            )
        conn.execute(sa.text("INSERT INTO workflow_edge VALUES (1, 'peak', 'table', 'salient_features', 'data')"))
        conn.execute(sa.text("INSERT INTO workflow_edge VALUES (1, 'other', 'table', 'salient_features', 'other')"))
        if duplicate:
            conn.execute(sa.text("INSERT INTO workflow_edge VALUES (1, 'peak', 'table', 'peaks', 'data')"))
        _, nodes, edges = rev._workflow_tables(conn)
        old_hash = rev._workflow_hash(*rev._load_graph(conn, 1, nodes, edges))
        conn.execute(sa.text("UPDATE workflow SET integrity_hash=:hash"), {"hash": old_hash})
        for name in ("execution_run", "workflow_version", "project_version"):
            conn.execute(sa.text(f"CREATE TABLE {name} (id INTEGER, snapshot TEXT, integrity_hash TEXT)"))
            conn.execute(
                sa.text(f"INSERT INTO {name} VALUES (1, :snapshot, :hash)"),
                {"snapshot": json.dumps({"from_output": "salient_features"}), "hash": old_hash},
            )
        history = {
            name: conn.execute(sa.text(f"SELECT * FROM {name}")).all()
            for name in ("execution_run", "workflow_version", "project_version")
        }
        with Operations.context(MigrationContext.configure(conn)):
            rev.upgrade()
            rev.upgrade()  # idempotent
        assert conn.execute(sa.text("SELECT from_output FROM workflow_edge WHERE from_node_id='peak'")).all() == [
            ("peaks",)
        ]
        assert (
            conn.execute(sa.text("SELECT from_output FROM workflow_edge WHERE from_node_id='other'")).scalar()
            == "salient_features"
        )
        new_hash = conn.execute(sa.text("SELECT integrity_hash FROM workflow")).scalar()
        assert new_hash != old_hash
        assert new_hash == rev._workflow_hash(*rev._load_graph(conn, 1, nodes, edges))
        for name, records in history.items():
            assert conn.execute(sa.text(f"SELECT * FROM {name}")).all() == records
        with Operations.context(MigrationContext.configure(conn)), pytest.raises(RuntimeError, match="not reversible"):
            rev.downgrade()
        # Unrelated installations can still downgrade earlier schema changes.
        conn.execute(sa.text("DELETE FROM workflow_edge WHERE from_node_id='peak'"))
        with Operations.context(MigrationContext.configure(conn)):
            rev.downgrade()
        conn.execute(sa.text("INSERT INTO workflow_edge VALUES (1, 'peak', 'table', 'peaks', 'data')"))
        conn.execute(sa.text("UPDATE workflow_edge SET from_output='salient_features' WHERE from_node_id='peak'"))
        with (
            Operations.context(MigrationContext.configure(conn)),
            pytest.raises(RuntimeError, match="invalid integrity hash"),
        ):
            rev.upgrade()
    engine.dispose()
