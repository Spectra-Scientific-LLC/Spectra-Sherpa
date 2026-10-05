"""Remove empty legacy LLM preferences from the OSS schema.

The singular ``llm_config`` table has no current reader or writer. OSS BYOK
settings use the configured chat endpoint, and the managed server owns the
separate ``llm_configs`` table. Fresh installs need neither this empty table
nor a retired ORM model. Existing preference rows are preserved for archival
purposes; credentials and scientific history are never changed here.
"""

import sqlalchemy as sa
from alembic import op

revision = "g6h8i0j2k444"
down_revision = "f5g7h9i1j333"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("llm_config"):
        return
    table = sa.table("llm_config", sa.column("id"))
    if bind.execute(sa.select(table.c.id).limit(1)).first() is None:
        op.drop_table("llm_config")


def downgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("llm_config"):
        return
    op.create_table(
        "llm_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False, server_default="deepseek"),
        sa.Column("base_url", sa.String(255), nullable=False, server_default="https://api.deepseek.com"),
        sa.Column("model", sa.String(100), nullable=False, server_default="deepseek-chat"),
        sa.Column("verbose", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], name="fk_llm_config_user_id", ondelete="CASCADE"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index("ix_llm_config_user_id", "llm_config", ["user_id"])
