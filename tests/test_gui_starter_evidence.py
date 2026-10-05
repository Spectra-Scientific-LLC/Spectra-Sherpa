"""GUI starter readiness and sheet-level source provenance regressions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.v1.routes.workflow_templates import DataBindingSpec
from spectra_sherpa.app.lib.workflow_purpose import ANALYSIS_WORKFLOW
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
from spectra_sherpa.app.services.project_data_sources import sync_workflow_data_sources


def _targeted_template_data() -> dict:
    return {
        "status": "ready",
        "nodes": [
            {
                "node_id": "data_1",
                "node_type": "data.file_load",
                "label": "Load data",
                "parameters": {},
            },
            {
                "node_id": "model_1",
                "node_type": "model.fitted_pls",
                "label": "Fit PLS",
                "parameters": {"n_components": 2},
            },
        ],
        "edges": [
            {"from_node_id": "data_1", "to_node_id": "model_1", "from_output": "default", "to_input": "default"},
            {"from_node_id": "data_1", "to_node_id": "model_1", "from_output": "target", "to_input": "y"},
        ],
        "data_roles": {
            "X_features": {"role_type": "X_features", "node_binding": "data_1", "required": True},
            "y_continuous": {
                "role_type": "Y_reference",
                "target_type": "continuous",
                "node_binding": "data_1",
                "required": True,
            },
        },
    }


@pytest.mark.asyncio
async def test_bound_source_preview_readmits_active_sheet_before_offering_starter(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
) -> None:
    template = WorkflowTemplate(
        slug="bound_preview_regression",
        name="Bound Preview Regression",
        description="Requires a numeric target",
        category="calibration",
        template_data=_targeted_template_data(),
        is_active=True,
    )
    project = Project(user_id=test_user.id, name="Bound preview", description="")
    test_session.add_all([template, project])
    await test_session.commit()
    binding = DataBindingSpec(experiment_id=8, file_id=9, stage="raw")
    profile = {
        "primary_role": "X_features",
        "modality": "features",
        "technique": "ML/Statistics",
        "target_type": None,
        "target_fields": [],
        "identity_fields": [],
        "group_fields": [],
        "ordered_samples": False,
    }

    with patch(
        "spectra_sherpa.app.api.v1.routes.workflow_templates._validate_binding",
        new=AsyncMock(return_value=(binding, profile)),
    ) as validate:
        response = await auth_client.post(
            "/api/v1/workflow-templates/binding-compatibility-preview",
            json={
                "project_id": project.id,
                "binding": {"experiment_id": 8, "file_id": 9, "stage": "raw"},
            },
        )

    assert response.status_code == 200, response.text
    validate.assert_awaited_once()
    decision = next(item for item in response.json()["decisions"] if item["template_slug"] == template.slug)
    assert decision["status"] == "needs_input"
    assert decision["reason_codes"] == ["continuous_target_missing"]


@pytest.mark.asyncio
async def test_sheet_source_context_keeps_example_identity_outside_scientific_node_parameters(
    test_session: AsyncSession,
    test_user: User,
) -> None:
    project = Project(user_id=test_user.id, name="Example provenance", description="")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(
        user_id=test_user.id,
        project_id=project.id,
        name="Example PCA",
        status="draft",
        purpose=ANALYSIS_WORKFLOW,
        data_origin="example",
    )
    test_session.add(workflow)
    await test_session.flush()

    sources = await sync_workflow_data_sources(
        workflow,
        test_session,
        [
            {
                "node_id": "source",
                "node_type": "data.file_load",
                "parameters": {"experiment_id": 12, "file_id": 34, "stage": "raw"},
            }
        ],
        display_names_by_node={"source": "Wine (bundled example)"},
    )

    assert workflow.data_origin == "example"
    assert workflow.primary_data_source_id == sources[0].id
    assert sources[0].display_name == "Wine (bundled example)"
    assert "source_origin" not in sources[0].metadata_


def test_report_identity_prefers_run_bound_source_over_edited_sheet() -> None:
    from spectra_sherpa.app.api.v1.routes.workflow_export import _workflow_identity

    workflow = SimpleNamespace(
        id=17,
        project_id=9,
        name="Current sheet",
        data_origin="current",
        primary_data_source=SimpleNamespace(display_name="New source"),
        created_from_template_name="PCA Starter",
        created_from_template_version="1",
    )
    definition = {
        "name": "Executed sheet",
        "data_context": {
            "schema_version": 1,
            "data_source_id": 12,
            "source_name": "Wine (bundled example)",
            "source_origin": "example",
        },
        "nodes": [{"node_id": "source", "node_type": "data.file_load", "parameters": {}}],
    }

    identity = _workflow_identity(workflow, definition=definition)

    assert identity["workflow_name"] == "Executed sheet"
    assert identity["source_name"] == "Wine (bundled example)"
    assert identity["source_origin"] == "example"
    assert identity["source_node_id"] == "source"
