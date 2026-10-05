"""Migrate every retained DOE concept into complete acquisition plans.

Revision ID: t9u1v3w5x248
Revises: s8t0u2v4w137
"""

from spectra_sherpa.app.db.acquisition_plan_migration import migrate_complete_acquisition_plans

revision = "t9u1v3w5x248"
down_revision = "s8t0u2v4w137"
branch_labels = None
depends_on = None


def upgrade() -> None:
    migrate_complete_acquisition_plans()


def downgrade() -> None:
    migrate_complete_acquisition_plans(downgrade=True)
