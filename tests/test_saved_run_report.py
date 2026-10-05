from dataclasses import replace
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from spectra_sherpa.app.api.v1.routes import workflow_export
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.services import run_output_retention as retention
from spectra_sherpa.app.services import run_validation_summary


@pytest.mark.asyncio
async def test_report_uses_saved_graph_not_current_canvas_and_discloses_missing_history(
    test_session,
    test_user,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(workflow_export, "check_export_allowed", AsyncMock(return_value=True))
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    workflow = Workflow(user_id=test_user.id, name="Changed canvas", description="New hypothesis")
    test_session.add(workflow)
    await test_session.flush()
    test_session.add(
        WorkflowNode(
            workflow_id=workflow.id,
            node_id="edited",
            node_type="preprocess.scale",
            label="Not the saved method",
            parameters={"method": "autoscale"},
            position_x=0,
            position_y=0,
        )
    )
    definition = {
        "schema_version": 1,
        "name": "Original method",
        "nodes": [
            {
                "node_id": "saved",
                "node_type": "preprocess.scale",
                "label": "Saved center",
                "parameters": {"method": "mean_center"},
                "position_x": 0,
                "position_y": 0,
            },
        ],
        "edges": [],
    }
    run = ExecutionRun(
        user_id=test_user.id,
        workflow_id=workflow.id,
        name="Inspected run",
        status="completed",
        params_snapshot={},
        results_summary={"saved": {"rmse": 0.5}},
        executed_at=datetime.now(timezone.utc),
        run_kind="data",
        evidence_completeness=retention.retain_run_outputs(
            test_user.id,
            {"__workflow__": {"definition": definition}},
            {},
        ),
    )
    test_session.add(run)
    await test_session.commit()

    from unittest.mock import Mock

    summary_spy = Mock(wraps=run_validation_summary.validation_summary)
    monkeypatch.setattr(run_validation_summary, "validation_summary", summary_spy)
    report = await workflow_export.get_report_data(
        workflow.id, run_ids=str(run.id), session=test_session, current_user=test_user
    )
    assert summary_spy.call_args.kwargs["include_row_level_plots"] is False
    await workflow_export.get_report_data(
        workflow.id,
        run_ids=str(run.id),
        include_row_level_plots=True,
        session=test_session,
        current_user=test_user,
    )
    assert summary_spy.call_args.kwargs["include_row_level_plots"] is True
    assert report["name"] == "Original method"
    assert report["description"] is None
    assert report["nodes"] == definition["nodes"]
    assert report["runs"][0]["saved_definition"] == definition
    assert "not the complete" in report["runs"][0]["evidence_notice"]

    run.evidence_completeness = None
    await test_session.commit()
    report = await workflow_export.get_report_data(
        workflow.id, run_ids=str(run.id), session=test_session, current_user=test_user
    )
    assert report["nodes"] == []
    assert report["runs"][0]["saved_definition"] is None
    assert "not substituted" in report["runs"][0]["evidence_notice"]

    with pytest.raises(HTTPException) as exc:
        await workflow_export.get_report_data(
            workflow.id, run_ids=f"{run.id},999999", session=test_session, current_user=test_user
        )
    assert exc.value.status_code == 404
