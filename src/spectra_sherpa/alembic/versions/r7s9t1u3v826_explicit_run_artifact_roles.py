"""Give saved-run artifact relationships one meaning each."""

from spectra_sherpa.app.db.run_artifact_role_migration import migrate_run_artifact_roles

revision = "r7s9t1u3v826"
down_revision = "q6r8s0t2u715"
branch_labels = None
depends_on = None


def upgrade() -> None:
    migrate_run_artifact_roles()


def downgrade() -> None:
    migrate_run_artifact_roles(downgrade=True)
