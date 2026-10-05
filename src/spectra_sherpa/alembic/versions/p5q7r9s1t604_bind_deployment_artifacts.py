"""Require an explicit reviewed artifact for operational watches."""

from spectra_sherpa.app.db.deployment_binding_migration import migrate_deployment_binding

revision = "p5q7r9s1t604"
down_revision = "o4p6q8r0s593"
branch_labels = None
depends_on = None


def upgrade() -> None:
    migrate_deployment_binding()


def downgrade() -> None:
    migrate_deployment_binding(downgrade=True)
