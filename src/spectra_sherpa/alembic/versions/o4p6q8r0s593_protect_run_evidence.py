"""Protect retained model sources and declare evidence completeness.

Revision ID: o4p6q8r0s593
Revises: n3o5p7q9r482
"""

from spectra_sherpa.app.db.run_evidence_migration import migrate_run_evidence

revision = "o4p6q8r0s593"
down_revision = "n3o5p7q9r482"
branch_labels = None
depends_on = None


def upgrade() -> None:
    migrate_run_evidence()


def downgrade() -> None:
    migrate_run_evidence(downgrade=True)
