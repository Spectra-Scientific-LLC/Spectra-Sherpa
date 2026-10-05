"""Merge the application-release and proposal-receipt migration heads."""

revision = "a0b1c2d3e4f5"
down_revision = ("y3z5a7b9c693", "z9b1c3d5e827")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Join the two independently applied revisions without changing data."""


def downgrade() -> None:
    """Re-expose the two parent heads when rolling back the merge revision."""
