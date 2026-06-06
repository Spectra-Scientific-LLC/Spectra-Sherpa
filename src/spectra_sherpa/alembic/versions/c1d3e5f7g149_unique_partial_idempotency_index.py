"""Make execution_run.idempotency_key uniquely indexed where present

Revision ID: c1d3e5f7g149
Revises: b0c2d4e6f938
Create Date: 2026-05-21 00:00:00.000000

PR-A (#161) created a NON-unique index on
``(user_id, workflow_id, idempotency_key)``. Two concurrent POSTs with
the same key both miss the lookup (no row yet), both execute, both
insert — duplicate rows AND duplicate executions.

This migration replaces the non-unique index with a UNIQUE PARTIAL
index covering only rows where ``idempotency_key IS NOT NULL``. With
the unique constraint in place, the route can claim a key by inserting
a reservation row BEFORE executing; the loser of the race catches
IntegrityError and replays the winner's row.

Partial-unique-index support:
  - Postgres: native CREATE UNIQUE INDEX ... WHERE
  - SQLite >= 3.8: same syntax supported

Both engines accept the syntax via sqlalchemy.Index(...,
unique=True, sqlite_where=..., postgresql_where=...).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c1d3e5f7g149"
down_revision = "b0c2d4e6f938"
branch_labels = None
depends_on = None

OLD_INDEX_NAME = "ix_execution_run_idempotency_lookup"
NEW_INDEX_NAME = "uq_execution_run_idempotency_key"


def _table_exists(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(idx["name"] == index_name for idx in sa.inspect(op.get_bind()).get_indexes(table_name))


def _dedupe_idempotency_keys() -> None:
    """Drop legacy duplicate rows before adding the unique partial index."""
    op.execute(sa.text("""
            DELETE FROM execution_run
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            PARTITION BY user_id, workflow_id, idempotency_key
                            ORDER BY
                                CASE status
                                    WHEN 'completed' THEN 0
                                    WHEN 'partial' THEN 1
                                    WHEN 'running' THEN 2
                                    WHEN 'pending' THEN 3
                                    WHEN 'failed' THEN 4
                                    WHEN 'error' THEN 5
                                    WHEN 'cancelled' THEN 6
                                    ELSE 7
                                END,
                                executed_at DESC,
                                created_at DESC,
                                id DESC
                        ) AS duplicate_rank
                    FROM execution_run
                    WHERE workflow_id IS NOT NULL
                      AND idempotency_key IS NOT NULL
                ) ranked
                WHERE duplicate_rank > 1
            )
            """))


def upgrade() -> None:
    if not _table_exists("execution_run"):
        return

    # Drop the prior non-unique index. ``if_exists=True`` keeps the
    # migration idempotent across environments that may have skipped
    # the earlier a9b1c3d5e827 migration.
    if _index_exists("execution_run", OLD_INDEX_NAME):
        op.drop_index(OLD_INDEX_NAME, table_name="execution_run")

    if _index_exists("execution_run", NEW_INDEX_NAME):
        return

    _dedupe_idempotency_keys()

    # Partial unique index: collisions only count when a key is present.
    # Pass dialect-specific WHERE clauses so both Postgres and SQLite emit
    # the partial form natively.
    op.create_index(
        NEW_INDEX_NAME,
        "execution_run",
        ["user_id", "workflow_id", "idempotency_key"],
        unique=True,
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    if not _table_exists("execution_run"):
        return
    if _index_exists("execution_run", NEW_INDEX_NAME):
        op.drop_index(NEW_INDEX_NAME, table_name="execution_run")
    if _index_exists("execution_run", OLD_INDEX_NAME):
        return
    op.create_index(
        OLD_INDEX_NAME,
        "execution_run",
        ["user_id", "workflow_id", "idempotency_key"],
        unique=False,
    )
