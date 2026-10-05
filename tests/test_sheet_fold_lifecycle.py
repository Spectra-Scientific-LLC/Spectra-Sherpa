"""Cross-validation semantics survive saved versions and portable projects."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_edge import WorkflowEdge
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.models.workflow_version import WorkflowVersion
from spectra_sherpa.app.services.dag.sheet_fold_validation import SheetFoldValidationPlan
from spectra_sherpa.app.services.run_params import build_saved_definition_snapshot, build_workflow_version_snapshot
from tests.test_sheet_fold_validation import _dataset, _executor, _plan


@pytest.mark.asyncio
async def test_fold_plan_survives_snapshot_restore_and_execution(test_session, test_user, tmp_path):
    from spectra_sherpa.app.api.v1.routes.projects import _build_snapshot, _restore_workflows_from_snapshot
    from spectra_sherpa.app.api.v1.routes.workflows.versions import open_version_as_new_sheet, restore_workflow_version

    project = Project(user_id=test_user.id, name="Fold lifecycle")
    test_session.add(project)
    await test_session.flush()
    data = _dataset()
    plan = _plan(data).as_dict()
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="Campaign sheet", fold_validation_plan=plan)
    test_session.add(workflow)
    await test_session.flush()
    executor = _executor(data, None, tmp_path)
    for n in executor.nodes.values():
        test_session.add(
            WorkflowNode(
                workflow_id=workflow.id, node_id=n.node_id, node_type=n.metadata.node_type, parameters=n.parameters
            )
        )
    for e in executor.edges:
        test_session.add(
            WorkflowEdge(
                workflow_id=workflow.id,
                from_node_id=e.from_node,
                to_node_id=e.to_node,
                from_output=e.from_output,
                to_input=e.to_input,
            )
        )
    await test_session.commit()
    workflow = await test_session.scalar(
        select(Workflow)
        .where(Workflow.id == workflow.id)
        .options(selectinload(Workflow.nodes), selectinload(Workflow.edges), selectinload(Workflow.data_source_links))
    )
    run_snapshot = build_saved_definition_snapshot(workflow)
    version_snapshot = build_workflow_version_snapshot(workflow)
    assert run_snapshot["fold_validation_plan"] == version_snapshot["fold_validation_plan"] == plan
    version = WorkflowVersion(
        workflow_id=workflow.id, version_number=1, created_by=test_user.id, snapshot=version_snapshot
    )
    test_session.add(version)
    await test_session.commit()
    workflow.fold_validation_plan = None
    await test_session.commit()
    restored = await restore_workflow_version(workflow.id, version.id, session=test_session, current_user=test_user)
    assert restored.fold_validation_plan == plan
    opened = await open_version_as_new_sheet(workflow.id, version.id, session=test_session, current_user=test_user)
    assert opened.fold_validation_plan == plan
    snapshot = await _build_snapshot(project, test_session, actor_id=test_user.id)
    assert snapshot["workflows"][0]["fold_validation_plan"] == plan
    imported_project = Project(user_id=test_user.id, name="Imported")
    test_session.add(imported_project)
    await test_session.flush()
    remap = await _restore_workflows_from_snapshot(imported_project, test_user.id, snapshot, {}, {}, {}, test_session)
    imported = await test_session.get(Workflow, remap[workflow.id])
    assert imported.fold_validation_plan == plan
    result = await _executor(data, SheetFoldValidationPlan.from_dict(imported.fold_validation_plan), tmp_path).execute()
    assert result["score"]["default"]["fold_validation"]["scope"] == "cross_validation"
    workflow.fold_validation_plan["origin"] = "later edit"
    assert run_snapshot["fold_validation_plan"]["origin"] == plan["origin"]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["python", "notebook", "download"])
async def test_code_exports_do_not_silently_drop_fold_semantics(auth_client, test_session, test_user, kind):
    workflow = Workflow(user_id=test_user.id, name="CV sheet", fold_validation_plan=_plan(_dataset()).as_dict())
    test_session.add(workflow)
    await test_session.commit()
    response = await auth_client.get(f"/api/v1/workflows/{workflow.id}/export/{kind}")
    assert response.status_code == 422, response.text
    assert "validation plan" in response.json()["detail"]


def test_code_export_service_cannot_bypass_validation_plan_guard():
    from types import SimpleNamespace

    from spectra_sherpa.app.services.python_export import build_canonical_executable_export

    with pytest.raises(ValueError, match="validation plan"):
        build_canonical_executable_export(
            SimpleNamespace(fold_validation_plan=_plan(_dataset()).as_dict()), export_context=None
        )
