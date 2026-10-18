"""Record the user's goal and Starter plan on each project."""

import sqlalchemy as sa
from alembic import op

revision = "n3o5p7q9r661"
down_revision = "m2n4o6p8q660"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("project"):
        return
    columns = {column["name"] for column in inspector.get_columns("project")}
    if "goal" not in columns:
        op.add_column("project", sa.Column("goal", sa.Text(), nullable=True))
    if "goal_plan" not in columns:
        op.add_column("project", sa.Column("goal_plan", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("project") as batch:
        batch.drop_column("goal_plan")
        batch.drop_column("goal")
