from __future__ import annotations

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from spectra_sherpa.alembic.versions import l2g4h6i8j471_custom_algo_user_fk_cascade as rev


def _run_upgrade(conn: sa.engine.Connection) -> None:
    ctx = MigrationContext.configure(conn)
    ops = Operations(ctx)
    original_op = rev.op
    rev.op = ops
    try:
        rev.upgrade()
    finally:
        rev.op = original_op


def test_custom_algo_upgrade_enforces_user_fk_cascade(tmp_path) -> None:
    db_path = tmp_path / "fk_upgrade.sqlite"
    engine = sa.create_engine(f"sqlite:///{db_path}")

    with engine.begin() as conn:
        conn.execute(sa.text("PRAGMA foreign_keys=ON"))

        conn.execute(sa.text("CREATE TABLE user (id INTEGER PRIMARY KEY)"))
        conn.execute(sa.text("CREATE TABLE project (id INTEGER PRIMARY KEY)"))
        conn.execute(sa.text("""
                CREATE TABLE custom_algo (
                    id INTEGER PRIMARY KEY,
                    project_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    name VARCHAR(255) NOT NULL,
                    slug VARCHAR(255) NOT NULL,
                    description TEXT,
                    code TEXT NOT NULL,
                    mode VARCHAR(20) NOT NULL DEFAULT 'simple',
                    icon VARCHAR(10) NOT NULL DEFAULT 'x',
                    node_type VARCHAR(255) NOT NULL UNIQUE,
                    created_at DATETIME,
                    updated_at DATETIME,
                    FOREIGN KEY(project_id) REFERENCES project (id) ON DELETE CASCADE,
                    FOREIGN KEY(user_id) REFERENCES user (id)
                )
                """))
        conn.execute(sa.text("CREATE INDEX ix_custom_algo_project_id ON custom_algo (project_id)"))
        conn.execute(sa.text("CREATE INDEX ix_custom_algo_user_id ON custom_algo (user_id)"))

        conn.execute(sa.text("INSERT INTO user (id) VALUES (1)"))
        conn.execute(sa.text("INSERT INTO project (id) VALUES (1)"))
        conn.execute(sa.text("""
                INSERT INTO custom_algo (id, project_id, user_id, name, slug, code, mode, icon, node_type)
                VALUES (1, 1, 1, 'algo', 'algo', 'result = data', 'simple', 'x', 'ualgo.1.algo')
                """))

        _run_upgrade(conn)

        fks = conn.execute(sa.text("PRAGMA foreign_key_list('custom_algo')")).mappings().all()
        user_fk = next((row for row in fks if row["table"] == "user" and row["from"] == "user_id"), None)
        assert user_fk is not None
        assert str(user_fk["on_delete"]).upper() == "CASCADE"

        conn.execute(sa.text("DELETE FROM user WHERE id = 1"))
        remaining = conn.execute(sa.text("SELECT COUNT(*) FROM custom_algo")).scalar_one()
        assert remaining == 0
