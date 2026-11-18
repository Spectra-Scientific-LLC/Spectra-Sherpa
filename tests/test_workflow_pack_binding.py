"""Saved pack provenance survives transaction boundaries and version snapshots."""

from copy import deepcopy

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from spectra_sherpa.app.api.v1.routes.workflows import crud, versions
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.schemas.workflows import WorkflowCreate, WorkflowUpdate
from spectra_sherpa.app.services.run_params import build_saved_definition_snapshot, build_workflow_version_snapshot
from tests.pack_retention_fixtures import make_retained_registry
from tests.test_pack_manifest import pack


@pytest.fixture
def retained_registry(monkeypatch):
    return make_retained_registry(monkeypatch)


async def test_saved_binding_survives_reload_and_snapshots_then_refuses_changed_build(
    test_session, test_user, retained_registry
):
    detail = await crud.persist_workflow(
        WorkflowCreate(name="Pack provenance", nodes=[{"node_id": "pack", "node_type": "pro.reference.record"}]),
        session=test_session,
        current_user=test_user,
    )
    await test_session.commit()
    workflow = await test_session.scalar(
        select(Workflow)
        .where(Workflow.id == detail.id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.primary_data_source),
            selectinload(Workflow.data_source_links),
        )
    )
    original = deepcopy(workflow.pack_binding)
    assert original["nodes"][0]["required"][0]["build_sha256"] == "a" * 64
    assert build_saved_definition_snapshot(workflow)["pack_binding"] == original
    version = build_workflow_version_snapshot(workflow)
    assert version["pack_binding"] == original
    versions._admit_snapshot_graph(deepcopy(version))

    retained_registry._pack_manifests = (pack(build_sha256="b" * 64),)
    with pytest.raises(HTTPException) as error:
        versions._admit_snapshot_graph(deepcopy(version))
    assert error.value.status_code == 409
    assert error.value.detail["nodes"][0]["reason"] == "changed_binding"
    with pytest.raises(HTTPException) as error:
        await crud.update_workflow(
            workflow.id, WorkflowUpdate(name="No implicit rebind"), session=test_session, current_user=test_user
        )
    assert error.value.status_code == 409
    assert workflow.pack_binding == original
    assert workflow.name == "Pack provenance"
    assert build_saved_definition_snapshot(workflow)["pack_binding"] == original


async def test_stripped_pack_snapshot_is_not_recreated_from_installed_code(test_session, test_user, retained_registry):
    detail = await crud.persist_workflow(
        WorkflowCreate(name="No inferred history", nodes=[{"node_id": "pack", "node_type": "pro.reference.record"}]),
        session=test_session,
        current_user=test_user,
    )
    workflow = await test_session.scalar(
        select(Workflow)
        .where(Workflow.id == detail.id)
        .options(
            selectinload(Workflow.nodes),
            selectinload(Workflow.edges),
            selectinload(Workflow.primary_data_source),
            selectinload(Workflow.data_source_links),
        )
    )
    version = build_workflow_version_snapshot(workflow)
    del version["pack_binding"]
    with pytest.raises(HTTPException) as error:
        versions._admit_snapshot_graph(version)
    assert error.value.detail["nodes"][0]["reason"] == "missing_binding"
    await test_session.rollback()
    assert (
        await test_session.scalar(
            select(Workflow)
            .where(Workflow.id == detail.id)
            .options(
                selectinload(Workflow.nodes),
                selectinload(Workflow.edges),
                selectinload(Workflow.primary_data_source),
                selectinload(Workflow.data_source_links),
            )
        )
        is None
    )
