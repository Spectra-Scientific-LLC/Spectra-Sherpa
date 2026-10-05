"""Record the resolved numerical environment on every run.

Revision ID: x2y4z6a8b582
Revises: x4c6a8m0p292
"""

from spectra_sherpa.app.db.run_environment_migration import migrate_run_environment

revision = "x2y4z6a8b582"
down_revision = "x4c6a8m0p292"
branch_labels = None
depends_on = None


def upgrade() -> None:
    migrate_run_environment()


def downgrade() -> None:
    migrate_run_environment(downgrade=True)
