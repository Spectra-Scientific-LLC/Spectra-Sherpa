"""Retained proposal identity and additive migration behavior."""

from copy import deepcopy

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from spectra_sherpa.app.db import proposal_receipt_migration
from spectra_sherpa.app.services.dag.proposal_contract import build_proposal_receipt, read_proposal_receipt


def receipt(kind="ordinary_workflow"):
    return build_proposal_receipt(
        kind=kind,
        actor_user_id=7,
        request_id="request-1",
        request_digest="a" * 64,
        parent_identity={"workflow_id": 1},
        source_bindings={"source": "b" * 64},
        admitted_definitions=[{"nodes": [], "edges": []}],
        operation_contracts={},
        effective_parameters={},
        population_receipts={},
        changes=[],
    )


@pytest.mark.parametrize("field", ["parent_identity", "source_bindings", "effective_parameters", "execution"])
def test_receipt_refuses_changed_authority(field):
    value = deepcopy(receipt())
    value[field]["changed"] = True
    with pytest.raises(ValueError, match="receipt changed"):
        read_proposal_receipt(value)


def test_campaign_and_ordinary_share_receipt_without_granting_execution():
    ordinary, campaign = read_proposal_receipt(receipt()), read_proposal_receipt(receipt("managed_campaign"))
    assert ordinary.schema_version == campaign.schema_version
    assert ordinary.execution["requested"] is campaign.execution["requested"] is False
    assert ordinary.execution["state"] == campaign.execution["state"] == "draft"
    assert not ordinary.execution["requires_campaign_quote"]
    assert campaign.execution["requires_campaign_quote"]


@pytest.mark.parametrize("managed", [False, True])
def test_receipt_migration_is_additive_and_leaves_historical_rows_unknown(monkeypatch, managed):
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        tables = ["workflow"] + (["canonical_llm_search_proposal"] if managed else [])
        for table in tables:
            connection.exec_driver_sql(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
            connection.exec_driver_sql(f"INSERT INTO {table} (id) VALUES (1)")
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(proposal_receipt_migration, "op", operations)
        proposal_receipt_migration.migrate_proposal_receipt()
        proposal_receipt_migration.migrate_proposal_receipt()
        for table in tables:
            assert connection.exec_driver_sql(f"SELECT proposal_receipt FROM {table}").scalar() is None
        proposal_receipt_migration.migrate_proposal_receipt(downgrade=True)
        for table in tables:
            assert connection.exec_driver_sql(f"SELECT id FROM {table}").scalar() == 1
            assert "proposal_receipt" not in {c["name"] for c in sa.inspect(connection).get_columns(table)}
    engine.dispose()
