"""Bind folder watches to an imported campaign application plan.

Revision ID: x4c6a8m0p292
Revises: w1x3y5z7a471
"""

from spectra_sherpa.app.db.canonical_watch_migration import migrate_canonical_watch

revision = "x4c6a8m0p292"
down_revision = "w1x3y5z7a471"
branch_labels = None
depends_on = None


def upgrade():
    migrate_canonical_watch()


def downgrade():
    migrate_canonical_watch(downgrade=True)
