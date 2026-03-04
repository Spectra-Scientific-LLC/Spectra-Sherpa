"""Enforce ON DELETE CASCADE on custom_algo.user_id via table rebuild.

Revision ID: l2g4h6i8j471
Revises: k1f9g3h7i360
Create Date: 2026-02-24 19:15:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "l2g4h6i8j471"
down_revision = "k1f9g3h7i360"
branch_labels = None
depends_on = None

_CUSTOM_ALGO_COLUMNS = (
    "id",
    "project_id",
    "user_id",
    "name",
    "slug",
    "description",
    "code",
    "mode",
    "icon",
    "node_type",
    "created_at",
    "updated_at",
)


def _assert_expected_source_table() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("custom_algo"):
        raise RuntimeError("Migration requires existing 'custom_algo' table")

    if inspector.has_table("custom_algo_new"):
        raise RuntimeError("Temporary table 'custom_algo_new' already exists; aborting fail-fast migration")

    actual = {col["name"] for col in inspector.get_columns("custom_algo")}
    expected = set(_CUSTOM_ALGO_COLUMNS)
    missing = expected - actual
    if missing:
        raise RuntimeError(
            f"custom_algo table missing required columns: {sorted(missing)}. " "Cannot rebuild table safely."
        )


def _create_custom_algo_new(*, user_ondelete: str | None) -> None:
    user_fk = sa.ForeignKey("user.id", ondelete=user_ondelete) if user_ondelete else sa.ForeignKey("user.id")

    op.create_table(
        "custom_algo_new",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), user_fk, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(20), nullable=False, server_default="simple"),
        sa.Column("icon", sa.String(10), nullable=False, server_default="🧪"),
        sa.Column("node_type", sa.String(255), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def _rebuild_custom_algo(*, user_ondelete: str | None) -> None:
    _assert_expected_source_table()
    _create_custom_algo_new(user_ondelete=user_ondelete)

    op.execute(
        sa.text(
            """
            INSERT INTO custom_algo_new (
                id, project_id, user_id, name, slug, description, code,
                mode, icon, node_type, created_at, updated_at
            )
            SELECT
                id, project_id, user_id, name, slug, description, code,
                mode, icon, node_type, created_at, updated_at
            FROM custom_algo
            """
        )
    )

    op.drop_table("custom_algo")
    op.rename_table("custom_algo_new", "custom_algo")

    op.create_index("ix_custom_algo_project_id", "custom_algo", ["project_id"], unique=False)
    op.create_index("ix_custom_algo_user_id", "custom_algo", ["user_id"], unique=False)


def _user_fk_has_cascade() -> bool:
    """Check if user_id FK already has ON DELETE CASCADE."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("custom_algo"):
        return False
    for fk in inspector.get_foreign_keys("custom_algo"):
        if "user_id" in fk.get("constrained_columns", []):
            ondelete = (fk.get("options", {}).get("ondelete") or "").upper()
            if ondelete == "CASCADE":
                return True
    return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("custom_algo"):
        return  # Table will be created with CASCADE by create_all() or k1f9g3h7i360
    if _user_fk_has_cascade():
        return  # Already correct (e.g. create_all() on fresh DB)
    _rebuild_custom_algo(user_ondelete="CASCADE")


def downgrade() -> None:
    _rebuild_custom_algo(user_ondelete=None)
