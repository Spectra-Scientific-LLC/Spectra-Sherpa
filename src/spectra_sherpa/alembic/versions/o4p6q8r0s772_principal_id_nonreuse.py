"""Prevent automatic reuse of deleted SQLite principal identities.

Existing identities, references and constraints remain unchanged. PostgreSQL
already allocates through a monotonically advancing sequence.
"""

import sqlalchemy as sa
from alembic import op

revision = "o4p6q8r0s772"
down_revision = "n3o5p7q9r661"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        return
    ddl = bind.execute(sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name='user'")).scalar()
    if not ddl or "AUTOINCREMENT" in ddl.upper():
        return
    # The canonical migration_transaction disables FK cascades for the rebuild,
    # validates references, and commits atomically. Refuse unsafe direct use.
    if bind.exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError("Principal migration requires the canonical SQLite migration transaction")
    with op.batch_alter_table("user", recreate="always", table_kwargs={"sqlite_autoincrement": True}):
        pass


def downgrade():
    # Retain the stronger identity allocation invariant on downgrade. It is
    # compatible with older application code and contains no new columns.
    pass
