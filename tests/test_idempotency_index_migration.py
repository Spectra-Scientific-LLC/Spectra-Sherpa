from __future__ import annotations

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from spectra_sherpa.alembic.versions import c1d3e5f7g149_unique_partial_idempotency_index as rev


def _run_upgrade(conn: sa.engine.Connection) -> None:
    ctx = MigrationContext.configure(conn)
    ops = Operations(ctx)
    original_op = rev.op
    rev.op = ops
    try:
        rev.upgrade()
    finally:
        rev.op = original_op


def test_idempotency_unique_index_migration_dedupes_existing_rows(tmp_path) -> None:
    db_path = tmp_path / "idempotency_upgrade.sqlite"
    engine = sa.create_engine(f"sqlite:///{db_path}")

    with engine.begin() as conn:
        conn.execute(sa.text("""
                CREATE TABLE execution_run (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    workflow_id INTEGER,
                    status VARCHAR(50) NOT NULL,
                    executed_at DATETIME NOT NULL,
                    created_at DATETIME,
                    idempotency_key VARCHAR(64)
                )
                """))
        conn.execute(sa.text("""
                CREATE INDEX ix_execution_run_idempotency_lookup
                ON execution_run (user_id, workflow_id, idempotency_key)
                """))
        conn.execute(sa.text("""
                INSERT INTO execution_run
                    (id, user_id, workflow_id, status, executed_at, created_at, idempotency_key)
                VALUES
                    (1, 1, 10, 'completed', '2026-05-01 10:00:00', '2026-05-01 10:00:00', 'same-key'),
                    (2, 1, 10, 'failed', '2026-05-01 10:01:00', '2026-05-01 10:01:00', 'same-key'),
                    (3, 1, 11, 'pending', '2026-05-01 10:00:00', '2026-05-01 10:00:00', 'running-key'),
                    (4, 1, 11, 'running', '2026-05-01 10:01:00', '2026-05-01 10:01:00', 'running-key'),
                    (5, 1, NULL, 'completed', '2026-05-01 10:00:00', '2026-05-01 10:00:00', 'null-workflow'),
                    (6, 1, NULL, 'completed', '2026-05-01 10:01:00', '2026-05-01 10:01:00', 'null-workflow'),
                    (7, 1, 12, 'completed', '2026-05-01 10:00:00', '2026-05-01 10:00:00', NULL),
                    (8, 1, 12, 'completed', '2026-05-01 10:01:00', '2026-05-01 10:01:00', NULL)
                """))

        _run_upgrade(conn)

        ids = conn.execute(sa.text("SELECT id FROM execution_run ORDER BY id")).scalars().all()
        assert ids == [1, 4, 5, 6, 7, 8]

        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(sa.text("""
                    INSERT INTO execution_run
                        (id, user_id, workflow_id, status, executed_at, created_at, idempotency_key)
                    VALUES
                        (9, 1, 10, 'completed', '2026-05-01 10:02:00', '2026-05-01 10:02:00', 'same-key')
                    """))
