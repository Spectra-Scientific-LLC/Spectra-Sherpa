"""Relax legacy auth columns on user table after managed-auth split.

Migration 0004 in the commercial server moved password_hash, is_superuser, and
login_count to the managed_user_account table, but never relaxed the NOT
NULL constraints on the original user columns.  The OSS User ORM model
no longer maps these columns, so INSERTs fail on databases that still
carry the old NOT NULL constraints.

Revision ID: s1t3u5v7w149
Revises: r8s0t2u4v037
Create Date: 2026-04-03 10:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "s1t3u5v7w149"
down_revision = "r8s0t2u4v037"
branch_labels = None
depends_on = None

_LEGACY_DUMMY_HASH = "__managed_auth_moved__"

# Legacy auth columns that must become nullable now that they are owned
# by managed_user_account (commercial server migration 0004).
_COLUMNS_TO_RELAX = [
    ("password_hash", sa.String(length=255)),
    ("is_superuser", sa.Boolean()),
    ("login_count", sa.Integer()),
]


def _user_columns() -> dict[str, dict[str, object]]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("user"):
        return {}
    return {column["name"]: column for column in inspector.get_columns("user")}


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    columns = _user_columns()
    if not columns:
        return

    to_relax = [
        (name, col_type)
        for name, col_type in _COLUMNS_TO_RELAX
        if name in columns and not columns[name].get("nullable", True)
    ]

    if not to_relax:
        return

    if _is_sqlite():
        with op.batch_alter_table("user", recreate="always") as batch_op:
            for name, col_type in to_relax:
                batch_op.alter_column(
                    name,
                    existing_type=col_type,
                    nullable=True,
                )
        return

    for name, col_type in to_relax:
        op.alter_column(
            "user",
            name,
            existing_type=col_type,
            nullable=True,
        )


def downgrade() -> None:
    columns = _user_columns()
    if not columns:
        return

    user_table = sa.table(
        "user",
        sa.column("password_hash", sa.String(length=255)),
        sa.column("is_superuser", sa.Boolean()),
        sa.column("login_count", sa.Integer()),
    )

    # Backfill NULLs before restoring NOT NULL constraints
    if "password_hash" in columns:
        op.execute(
            user_table.update().where(user_table.c.password_hash.is_(None)).values(password_hash=_LEGACY_DUMMY_HASH)
        )
    if "is_superuser" in columns:
        op.execute(user_table.update().where(user_table.c.is_superuser.is_(None)).values(is_superuser=False))
    if "login_count" in columns:
        op.execute(user_table.update().where(user_table.c.login_count.is_(None)).values(login_count=0))

    to_restore = [(name, col_type) for name, col_type in _COLUMNS_TO_RELAX if name in columns]

    if not to_restore:
        return

    if _is_sqlite():
        with op.batch_alter_table("user", recreate="always") as batch_op:
            for name, col_type in to_restore:
                batch_op.alter_column(
                    name,
                    existing_type=col_type,
                    nullable=False,
                )
        return

    for name, col_type in to_restore:
        op.alter_column(
            "user",
            name,
            existing_type=col_type,
            nullable=False,
        )
