"""Give multi-well plans independent storage and retire the unexposed DOE schema."""

from spectra_sherpa.app.db.retired_doe_migration import migrate_retired_doe_storage

revision = "q6r8s0t2u715"
down_revision = "p5q7r9s1t604"
branch_labels = None
depends_on = None


def upgrade() -> None:
    migrate_retired_doe_storage()


def downgrade() -> None:
    migrate_retired_doe_storage(downgrade=True)
