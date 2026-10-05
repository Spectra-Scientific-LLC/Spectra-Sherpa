"""System-level proof for the closed workflow-purpose authority."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import func, select

from spectra_sherpa.app.api.v1.routes.projects import _admit_project_snapshot_graphs
from spectra_sherpa.app.lib.workflow_purpose import (
    ANALYSIS_WORKFLOW,
    MANAGED_CANDIDATE_AUTHORITY,
    WorkflowPurposeError,
    require_workflow_purpose,
)
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow


def test_workflow_purpose_is_closed_without_translation():
    assert require_workflow_purpose(ANALYSIS_WORKFLOW) == ANALYSIS_WORKFLOW
    assert require_workflow_purpose(MANAGED_CANDIDATE_AUTHORITY) == MANAGED_CANDIDATE_AUTHORITY
    for invalid in (None, "", "managed", "ANALYSIS", 1):
        with pytest.raises(WorkflowPurposeError):
            require_workflow_purpose(invalid)


def test_project_import_requires_purpose_and_re_admits_managed_authority():
    with pytest.raises(HTTPException, match="workflow purpose must be exactly"):
        _admit_project_snapshot_graphs({"workflows": [{"nodes": [], "edges": []}]})

    with pytest.raises(HTTPException, match="managed workflow 0 is not admissible"):
        _admit_project_snapshot_graphs(
            {
                "workflows": [
                    {
                        "id": 1,
                        "purpose": MANAGED_CANDIDATE_AUTHORITY,
                        "integrity_hash": "0" * 64,
                        "nodes": [],
                        "edges": [],
                    }
                ]
            }
        )


def test_every_production_workflow_constructor_declares_purpose():
    """A new creation path must choose purpose instead of inheriting a fixture default."""

    app_root = Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "app"
    omissions: list[str] = []
    for path in app_root.rglob("*.py"):
        if path.name == "workflow.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "Workflow":
                continue
            if not any(keyword.arg == "purpose" for keyword in node.keywords):
                omissions.append(f"{path.relative_to(app_root)}:{node.lineno}")
    assert omissions == []


@pytest.mark.asyncio
async def test_ordinary_create_route_cannot_mint_managed_authority(
    auth_client: AsyncClient,
):
    response = await auth_client.post(
        "/api/v1/workflows",
        json={
            "name": "Caller-claimed authority",
            "purpose": MANAGED_CANDIDATE_AUTHORITY,
            "nodes": [],
            "edges": [],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == ("Ordinary workflow creation may create only analysis workflows")


@pytest.mark.asyncio
async def test_managed_candidate_authority_is_rejected_before_run_reservation(
    auth_client: AsyncClient,
    test_session,
    test_user: User,
):
    project = Project(user_id=test_user.id, name="Purpose boundary")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(
        user_id=test_user.id,
        project_id=project.id,
        name="Harness authority",
        purpose=MANAGED_CANDIDATE_AUTHORITY,
    )
    test_session.add(workflow)
    await test_session.commit()

    response = await auth_client.post(
        f"/api/v1/workflows/{workflow.id}/execute",
        json={"initial_data": {}},
        headers={"Idempotency-Key": "purpose-boundary-001"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "managed_candidate_requires_harness"
    run_count = await test_session.scalar(
        select(func.count(ExecutionRun.id)).where(ExecutionRun.workflow_id == workflow.id)
    )
    assert run_count == 0


@pytest.mark.asyncio
async def test_managed_candidate_is_immutable_across_generic_workflow_and_project_routes(
    auth_client: AsyncClient,
    test_session,
    test_user: User,
):
    project = Project(user_id=test_user.id, name="Frozen candidate project")
    test_session.add(project)
    await test_session.flush()
    workflow = Workflow(
        user_id=test_user.id,
        project_id=project.id,
        name="Frozen managed candidate",
        purpose=MANAGED_CANDIDATE_AUTHORITY,
        sheet_order=1,
    )
    test_session.add(workflow)
    await test_session.commit()

    update_response = await auth_client.put(
        f"/api/v1/workflows/{workflow.id}",
        json={"name": "Mutation must refuse", "create_version": False},
    )
    delete_response = await auth_client.delete(f"/api/v1/workflows/{workflow.id}")
    duplicate_response = await auth_client.post(f"/api/v1/workflows/{workflow.id}/duplicate")
    data_sources_response = await auth_client.put(
        f"/api/v1/workflows/{workflow.id}/data-sources",
        json={"data_source_ids": [], "primary_data_source_id": None},
    )
    primary_source_response = await auth_client.put(
        f"/api/v1/workflows/{workflow.id}/primary-data-source",
        json={"primary_data_source_id": None},
    )
    tab_color_response = await auth_client.put(
        f"/api/v1/workflows/{workflow.id}/tab-color",
        json={"tab_color": "#123456"},
    )
    restore_response = await auth_client.post(f"/api/v1/workflows/{workflow.id}/versions/999/restore")
    open_version_response = await auth_client.post(f"/api/v1/workflows/{workflow.id}/versions/999/open-as-new-sheet")
    unlink_response = await auth_client.delete(f"/api/v1/projects/{project.id}/workflows/{workflow.id}")

    immutable_responses = (
        update_response,
        delete_response,
        duplicate_response,
        data_sources_response,
        primary_source_response,
        tab_color_response,
        restore_response,
        open_version_response,
    )
    assert all(response.status_code == 409 for response in immutable_responses)
    assert unlink_response.status_code == 409
    for response in immutable_responses:
        detail = response.json()["detail"]
        assert "immutable" in detail or "Managed candidate authority cannot" in detail
    assert "cannot be unlinked" in unlink_response.json()["detail"]

    await test_session.refresh(workflow)
    assert workflow.name == "Frozen managed candidate"
    assert workflow.project_id == project.id
    workflow.project_id = None
    await test_session.commit()
    relink_response = await auth_client.post(f"/api/v1/projects/{project.id}/workflows/{workflow.id}")
    assert relink_response.status_code == 409
    assert "cannot be moved" in relink_response.json()["detail"]
