"""Shared additive schema step for OSS and server migration chains."""

import sqlalchemy as sa
from alembic import op


def migrate_run_environment(*, downgrade: bool = False) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("execution_run"):
        return  # Legacy auth-only bootstrap has no scientific tables yet.
    columns = {column["name"] for column in inspector.get_columns("execution_run")}
    # A plain ALTER, never a batch rebuild. Rebuilding reflects the table's
    # foreign keys, and partway through a chain the tables they point at need
    # not exist yet; a single nullable column has no need to make this step
    # depend on the rest of the schema.
    if downgrade:
        if "environment_snapshot" in columns:
            op.drop_column("execution_run", "environment_snapshot")
    elif "environment_snapshot" not in columns:
        # Nullable with no backfill: a historical run genuinely has no
        # recorded environment, and inventing one would assert provenance
        # the run never carried.
        op.add_column("execution_run", sa.Column("environment_snapshot", sa.JSON(), nullable=True))
