"""An actual predecessor diagnostic remains readable without an execution alias."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from spectra_sherpa.app.api.v1.routes import runs
from spectra_sherpa.app.services import run_output_retention as retention
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.run_validation_summary import validation_summary


@pytest.mark.asyncio
async def test_predecessor_permutation_retained_output_and_report(tmp_path, monkeypatch):
    recorded = json.loads((Path(__file__).parent / "fixtures/preprocessing_permutation_history.json").read_text())
    assert recorded["producer_contract"] == "1b4d8a3f538be250518594d0bcee7f6530598de60963e8b165427a658c7f1eff"
    assert node_registry.get_metadata("diagnostics.plsda_permutation").resolved_execution_contract().digest == (
        "cefd94b6d587d017f5ec33a99d4443c2ea715d9294d5140e7045aae0ea9a80ec"
    )
    for relative, content in recorded["members"].items():
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    run = SimpleNamespace(
        id=13,
        user_id=1,
        status="completed",
        diagnostics={},
        source_metadata={},
        params_snapshot={"permutation": {"seed": 42}},
        evidence_completeness=recorded["evidence"],
    )

    async def owned(*args, **kwargs):
        return run

    # This test isolates retention/report reading, not database authorization.
    monkeypatch.setattr(runs, "_owned_run", owned)
    response = await runs.get_retained_run_output(
        13, "permutation", "default", project_id=1, session=None, current_user=SimpleNamespace(id=1)
    )
    assert response["value"] == recorded["value"]
    assert len(response["value"]["null"]) == 19
    summary = validation_summary(
        run,
        {
            "schema_version": 1,
            "nodes": [{"node_id": "permutation", "node_type": "diagnostics.plsda_permutation"}],
            "edges": [],
        },
    )
    rows = {row["label"]: row for row in summary["rows"]}
    assert any("permutation p-value" in label and float(row["value"]) == 0.05 for label, row in rows.items())
    assert any("permutation scope" in label and "calibration" in str(row).lower() for label, row in rows.items())
