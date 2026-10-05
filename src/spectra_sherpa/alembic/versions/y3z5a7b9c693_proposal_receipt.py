"""Retain the server-admitted scientific proposal.

Revision ID: y3z5a7b9c693
Revises: x2y4z6a8b582
"""

from spectra_sherpa.app.db.proposal_receipt_migration import migrate_proposal_receipt

revision = "y3z5a7b9c693"
down_revision = "x2y4z6a8b582"
branch_labels = None
depends_on = None


def upgrade() -> None:
    migrate_proposal_receipt()


def downgrade() -> None:
    migrate_proposal_receipt(downgrade=True)
