from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.services.project_data_sources import effective_workflow_tab_color


def sheet(files=(1, 2), target="claimed_botanical_group", override=None):
    workflow = Workflow(name="Analysis", color_source="ai", tab_color_override=override)
    workflow.nodes = [
        WorkflowNode(
            node_id="source",
            node_type="data.collection_load",
            parameters={
                "experiment_id": 1,
                "selected_file_ids": [str(value) for value in files],
                "asset_id": "",
                "source_manifest_sha256": "a" * 64,
                "stage": "raw",
                "target_authority": {"column": target, "target_type": "categorical", "units": None},
            },
        )
    ]
    return workflow


def test_portfolio_color_tracks_files_and_target_not_sheet_name_or_origin():
    original = sheet()
    same = sheet()
    same.name = "Another analysis"
    same.color_source = "data"
    color = effective_workflow_tab_color(original)
    assert color == effective_workflow_tab_color(same)
    assert color != effective_workflow_tab_color(sheet(files=(1,)))
    assert color != effective_workflow_tab_color(sheet(target="species"))


def test_manual_color_survives_until_explicit_reset():
    workflow = sheet(override="#ff0000")
    assert effective_workflow_tab_color(workflow) == "#ff0000"
    workflow.tab_color_override = None
    assert effective_workflow_tab_color(workflow) == effective_workflow_tab_color(sheet())
