"""Saved recipe export cannot replace retained pack identity with current code."""

from copy import deepcopy

import httpx
import pytest
from fastapi import FastAPI

from spectra_sherpa.app.api.deps import get_current_user, get_session
from spectra_sherpa.app.api.v1.routes.workflows import crud
from spectra_sherpa.app.api.v1.routes.workflows.export import router
from spectra_sherpa.app.schemas.workflows import WorkflowCreate
from spectra_sherpa.app.services.dag.nodes.preprocessing.normalize_node import NormalizeNode
from spectra_sherpa.app.services.dag.pack_requirements import capture_pack_graph_binding
from spectra_sherpa.app.services.python_export import build_canonical_executable_export
from tests.pack_retention_fixtures import make_retained_registry
from tests.test_export_robustness import _deployment_workflow
from tests.test_pack_manifest import pack


def test_direct_export_preserves_exact_binding_and_refuses_changes_before_callbacks(monkeypatch):
    registry = make_retained_registry(monkeypatch, base_node=NormalizeNode)
    workflow = _deployment_workflow()
    workflow.nodes[1].node_type = "pro.reference.record"
    workflow.pack_binding = capture_pack_graph_binding(
        [{"node_id": node.node_id, "node_type": node.node_type} for node in workflow.nodes], registry=registry
    ).model_dump(mode="json")
    original = deepcopy(workflow.pack_binding)
    exported = build_canonical_executable_export(workflow, export_context=None)
    assert exported.workflow.payload["pack_binding"] == original
    registry._pack_manifests = (pack(build_sha256="b" * 64),)

    def forbidden(*args, **kwargs):
        pytest.fail("Export called node construction before rejecting changed retained identity")

    monkeypatch.setattr(registry, "create_node", forbidden)
    with pytest.raises(ValueError, match="Retained pack bindings"):
        build_canonical_executable_export(workflow, export_context=None)
    assert workflow.pack_binding == original


@pytest.mark.parametrize("format_name", ["python", "notebook"])
@pytest.mark.parametrize("change", ["changed_build", "missing_binding"])
async def test_http_export_refuses_changed_or_stripped_saved_binding(
    test_session, test_user, monkeypatch, format_name, change
):
    registry = make_retained_registry(monkeypatch)
    detail = await crud.persist_workflow(
        WorkflowCreate(name="Retained export", nodes=[{"node_id": "pack", "node_type": "pro.reference.record"}]),
        session=test_session,
        current_user=test_user,
    )
    if change == "changed_build":
        registry._pack_manifests = (pack(build_sha256="b" * 64),)
    else:
        from spectra_sherpa.app.models.workflow import Workflow

        workflow = await test_session.get(Workflow, detail.id)
        workflow.pack_binding = None
        await test_session.commit()

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: test_user

    async def session():
        yield test_session

    app.dependency_overrides[get_session] = session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        response = await client.get(f"/workflows/{detail.id}/export/{format_name}")
    assert response.status_code == 422
