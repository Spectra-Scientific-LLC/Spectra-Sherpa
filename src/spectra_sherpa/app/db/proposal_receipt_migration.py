"""Add nullable proposal provenance without inventing historical authority."""

import sqlalchemy as sa
from alembic import op


def migrate_proposal_receipt(*, downgrade: bool = False) -> None:
    inspector = sa.inspect(op.get_bind())
    for table in ("workflow", "canonical_llm_search_proposal"):
        if not inspector.has_table(table):
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if downgrade:
            if "proposal_receipt" in columns:
                op.drop_column(table, "proposal_receipt")
        elif "proposal_receipt" not in columns:
            op.add_column(table, sa.Column("proposal_receipt", sa.JSON(), nullable=True))
