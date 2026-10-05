"""Rehome specimens under the experiment-owned authority.

Revision ID: u0v2w4x6y359
Revises: t9u1v3w5x248
"""

from spectra_sherpa.app.db.experiment_specimen_migration import migrate_experiment_specimen_authority

revision = "u0v2w4x6y359"
down_revision = "t9u1v3w5x248"
branch_labels = None
depends_on = None


def upgrade() -> None:
    migrate_experiment_specimen_authority()


def downgrade() -> None:
    migrate_experiment_specimen_authority(downgrade=True)
