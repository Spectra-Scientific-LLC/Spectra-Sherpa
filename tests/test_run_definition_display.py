"""Run staleness uses exact retained definitions without rewriting hashes."""

from types import SimpleNamespace

import pytest

from spectra_sherpa.app.api.v1.routes import execution_runs
from spectra_sherpa.app.services import run_output_retention


@pytest.mark.asyncio
@pytest.mark.parametrize("saved_value, expected", [(1.0, True), (2.0, False), (True, False)])
async def test_definition_match_preserves_numeric_semantics(monkeypatch, saved_value, expected):
    item = SimpleNamespace(state="exact")
    response = SimpleNamespace(
        evidence_completeness=SimpleNamespace(outputs={"__workflow__": {"definition": item}}),
        matches_current_definition=None,
    )
    monkeypatch.setattr(execution_runs.ExecutionRunOut, "model_validate", lambda run: response)
    retained = {
        "nodes": [{"node_id": "n", "node_type": "data.source", "parameters": {"value": saved_value}}],
        "edges": [],
    }
    monkeypatch.setattr(run_output_retention, "read_output", lambda user, evidence: retained)
    run = SimpleNamespace(user_id=1, integrity_hash="historical")
    workflow = SimpleNamespace(
        nodes=[SimpleNamespace(node_id="n", node_type="data.source", parameters={"value": 1})], edges=[]
    )
    result = await execution_runs._run_with_definition_match(run, workflow)
    assert result.matches_current_definition is expected
    assert run.integrity_hash == "historical"


@pytest.mark.asyncio
async def test_invalid_retained_definition_does_not_suppress_warning(monkeypatch):
    response = SimpleNamespace(
        evidence_completeness=SimpleNamespace(outputs={"__workflow__": {"definition": SimpleNamespace(state="exact")}}),
        matches_current_definition=None,
    )
    monkeypatch.setattr(execution_runs.ExecutionRunOut, "model_validate", lambda run: response)

    def reject(*args):
        raise ValueError("Checksum mismatch")

    monkeypatch.setattr(run_output_retention, "read_output", reject)
    result = await execution_runs._run_with_definition_match(SimpleNamespace(user_id=1), SimpleNamespace())
    assert result.matches_current_definition is None
