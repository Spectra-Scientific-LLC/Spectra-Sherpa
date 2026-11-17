"""Ordinary workflow persistence composes with a caller-owned transaction."""

import pytest
from sqlalchemy import func, select

from spectra_sherpa.app.api.v1.routes.workflows.crud import persist_workflow
from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.models.advisor_channel import AdvisorChannel
from spectra_sherpa.app.models.audit_event import AuditEvent
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.project_data_source import ProjectDataSource, WorkflowDataSource
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_edge import WorkflowEdge
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.schemas.workflows import WorkflowCreate
from spectra_sherpa.app.services.audit import AuditContext, use_audit_context


@pytest.mark.parametrize("commit", [False, True])
async def test_workflow_and_all_dependent_rows_share_caller_transaction(test_session, test_user, monkeypatch, commit):
    monkeypatch.setattr(app_config, "audit_enabled", True)
    project = Project(user_id=test_user.id, name="Transaction owner")
    test_session.add(project)
    await test_session.commit()
    project_id, actor_id = project.id, test_user.id
    payload = WorkflowCreate.model_validate(
        {
            "name": "Composed draft",
            "project_id": project_id,
            "nodes": [
                {
                    "node_id": "source",
                    "node_type": "data.file_load",
                    "parameters": {"experiment_id": 1, "file_id": 1, "stage": "raw"},
                },
                {
                    "node_id": "scale",
                    "node_type": "preprocess.scale",
                    "parameters": {"method": "autoscale", "center": True},
                },
            ],
            "edges": [{"from_node_id": "source", "to_node_id": "scale"}],
        }
    )
    # This caller mutation must neither commit nor disappear inside persistence.
    project.name = "Composed change"
    with use_audit_context(AuditContext("local", actor_id, "user", "transaction-proof")):
        detail = await persist_workflow(payload, session=test_session, current_user=test_user)
    assert detail.name == payload.name and len(detail.nodes) == 2 and len(detail.edges) == 1
    assert detail.primary_data_source_id is not None and detail.advisor_channel_id is not None
    models = (Workflow, WorkflowNode, WorkflowEdge, ProjectDataSource, WorkflowDataSource, AdvisorChannel, AuditEvent)
    before = [await test_session.scalar(select(func.count()).select_from(model)) for model in models]
    assert before == [1, 2, 1, 1, 1, 1, 1]
    if commit:
        await test_session.commit()
    else:
        await test_session.rollback()
    after = [await test_session.scalar(select(func.count()).select_from(model)) for model in models]
    assert after == (before if commit else [0] * len(models))
    assert (await test_session.get(Project, project_id)).name == ("Composed change" if commit else "Transaction owner")
    if commit:
        event = await test_session.scalar(select(AuditEvent))
        assert event.actor_id == actor_id and event.action == "workflow.created"
        assert event.after_state["integrity_hash"] == detail.integrity_hash
