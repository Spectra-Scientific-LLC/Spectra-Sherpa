"""Sheet-scoped data selection revision and execution custody coverage."""

from __future__ import annotations

import importlib

import numpy as np
import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.api.v1.routes.workflows.execute import (
    _execution_dataset_scientific_receipts,
)
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_data_selection_revision import (
    WorkflowDataSelectionRevision,
)
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.models.workflow_version import WorkflowVersion
from spectra_sherpa.app.services.dag.meta_helpers import add_processing_step
from spectra_sherpa.app.services.workflow_data_selections import (
    execution_selection_revisions,
    workflow_graph_digest,
)

SOURCE_DIGEST = "a" * 64
DEFINITION_DIGEST = "b" * 64
SCIENTIFIC_DIGEST = "c" * 64


def test_execution_receipt_preserves_exact_filter_rows() -> None:
    dataset = SherpaDataset(X=np.arange(18, dtype=float).reshape(6, 3), title="Filtered wine")
    add_processing_step(
        dataset,
        "data.filter_samples",
        {
            "field": "sample_index",
            "pattern": "1-2, 5-6",
            "n_input": 9,
            "n_selected": 6,
            "selected_indices": [0, 1, 4, 5, 7, 8],
            "no_filter": False,
        },
        node_id="filter-1",
        input_shape=(9, 3),
    )

    receipts = _execution_dataset_scientific_receipts({"filter-1": dataset})

    assert receipts[0]["sample_identity"]["count"] == 6
    lineage = receipts[0]["selection_lineage"][0]
    assert lineage["selected_index_ranges"] == [[0, 1], [4, 5], [7, 8]]
    assert len(lineage["selected_indices_sha256"]) == 64
    assert "selected_indices" not in lineage["parameters"]


def _source_parameters(experiment_id: int, *, target: str = "class") -> dict:
    return {
        "experiment_id": experiment_id,
        "stage": "raw",
        "asset_id": "primary",
        "selected_file_ids": ["11", "12"],
        "source_manifest_sha256": SOURCE_DIGEST,
        "collection_definition_sha256": DEFINITION_DIGEST,
        "scientific_collection_sha256": SCIENTIFIC_DIGEST,
        "target_authority": {
            "schema_version": "spectrasherpa-target-authority/1",
            "column": target,
            "target_type": "categorical",
            "units": None,
            "source_digest": SCIENTIFIC_DIGEST,
        },
        "group_column": "batch",
        "group_title": "Wine classes",
    }


async def _workflow_with_source(
    session: AsyncSession,
    user: User,
    *,
    name: str,
    node_id: str = "source",
) -> Workflow:
    workflow = Workflow(user_id=user.id, name=name, status="draft")
    session.add(workflow)
    await session.flush()
    session.add(
        WorkflowNode(
            workflow_id=workflow.id,
            node_id=node_id,
            node_type="data.collection_load",
            label="Training cohort",
            parameters=_source_parameters(7),
            position_x=0,
            position_y=0,
        )
    )
    await session.commit()
    await session.refresh(workflow, attribute_names=["nodes", "edges"])
    return workflow


def _apply_payload(*, expected_revision: int | None, key: str, target: str) -> dict:
    return {
        "expected_revision": expected_revision,
        "idempotency_key": key,
        "origin": "data_page",
        "reason": f"Use {target} for this sheet",
        "selection": {
            "experiment_id": 7,
            "dataset_name": "Wine classes",
            "stage": "raw",
            "selected_file_ids": [11],
            "asset_id": "primary",
            "source_manifest_sha256": SOURCE_DIGEST,
            "collection_definition_sha256": DEFINITION_DIGEST,
            "scientific_collection_sha256": SCIENTIFIC_DIGEST,
            "target_authority": {
                "schema_version": "spectrasherpa-target-authority/1",
                "column": target,
                "target_type": "categorical",
                "units": None,
                "source_digest": SCIENTIFIC_DIGEST,
            },
            "group_column": "batch",
        },
    }


@pytest.mark.asyncio
async def test_sheet_selection_is_versioned_idempotent_and_conflict_checked(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = await _workflow_with_source(test_session, test_user, name="PLS-DA sheet")
    route_module = importlib.import_module("spectra_sherpa.app.api.v1.routes.workflows.data_selections")

    async def admit_selection(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(route_module, "validate_selection", admit_selection)

    context = await auth_client.get(f"/api/v1/workflows/{workflow.id}/data-selections/source")
    assert context.status_code == 200
    assert context.json()["current_revision"] is None
    assert context.json()["saved_selection"]["target_authority"]["column"] == "class"

    payload = _apply_payload(expected_revision=None, key="sheet-edit-0001", target="cultivar")
    applied = await auth_client.put(f"/api/v1/workflows/{workflow.id}/data-selections/source", json=payload)
    assert applied.status_code == 200, applied.text
    assert applied.json()["revision_number"] == 1
    assert applied.json()["selection"]["target_authority"]["column"] == "cultivar"

    replay = await auth_client.put(f"/api/v1/workflows/{workflow.id}/data-selections/source", json=payload)
    assert replay.status_code == 200
    assert replay.json()["id"] == applied.json()["id"]

    changed_replay = await auth_client.put(
        f"/api/v1/workflows/{workflow.id}/data-selections/source",
        json={**payload, "reason": "A different request"},
    )
    assert changed_replay.status_code == 409
    assert "already used" in changed_replay.json()["detail"]

    stale = await auth_client.put(
        f"/api/v1/workflows/{workflow.id}/data-selections/source",
        json=_apply_payload(expected_revision=None, key="sheet-edit-0002", target="region"),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["current_revision"] == 1

    await test_session.refresh(workflow, attribute_names=["nodes", "edges"])
    assert workflow.nodes[0].parameters["target_authority"]["column"] == "cultivar"
    revisions = list(
        (
            await test_session.execute(
                select(WorkflowDataSelectionRevision).where(WorkflowDataSelectionRevision.workflow_id == workflow.id)
            )
        )
        .scalars()
        .all()
    )
    versions = list(
        (await test_session.execute(select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id)))
        .scalars()
        .all()
    )
    assert len(revisions) == 1
    assert len(versions) == 1


@pytest.mark.asyncio
async def test_unbound_collection_load_can_open_data_selection_and_receive_first_revision(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow = Workflow(user_id=test_user.id, name="Blank analysis", status="draft")
    test_session.add(workflow)
    await test_session.flush()
    test_session.add(
        WorkflowNode(
            workflow_id=workflow.id,
            node_id="source",
            node_type="data.collection_load",
            label="Collection Load",
            parameters={},
            position_x=0,
            position_y=0,
        )
    )
    await test_session.commit()
    route_module = importlib.import_module("spectra_sherpa.app.api.v1.routes.workflows.data_selections")

    async def admit_selection(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(route_module, "validate_selection", admit_selection)

    context = await auth_client.get(f"/api/v1/workflows/{workflow.id}/data-selections/source")
    assert context.status_code == 200
    assert context.json()["saved_selection"] is None
    assert context.json()["current_revision"] is None

    applied = await auth_client.put(
        f"/api/v1/workflows/{workflow.id}/data-selections/source",
        json=_apply_payload(expected_revision=None, key="blank-source-0001", target="class"),
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["revision_number"] == 1
    assert applied.json()["selection"]["experiment_id"] == 7


@pytest.mark.asyncio
async def test_partially_bound_collection_load_is_not_misrepresented_as_blank(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
) -> None:
    workflow = Workflow(user_id=test_user.id, name="Damaged source", status="draft")
    test_session.add(workflow)
    await test_session.flush()
    test_session.add(
        WorkflowNode(
            workflow_id=workflow.id,
            node_id="source",
            node_type="data.collection_load",
            label="Collection Load",
            parameters={"experiment_id": 7, "stage": "raw"},
            position_x=0,
            position_y=0,
        )
    )
    await test_session.commit()

    context = await auth_client.get(f"/api/v1/workflows/{workflow.id}/data-selections/source")

    assert context.status_code == 409
    assert context.json()["detail"] == "Workflow source has incomplete data-selection custody"


@pytest.mark.asyncio
async def test_selection_revisions_are_isolated_and_follow_an_unchanged_source_binding(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = await _workflow_with_source(test_session, test_user, name="Sheet A")
    second = await _workflow_with_source(test_session, test_user, name="Sheet B")
    route_module = importlib.import_module("spectra_sherpa.app.api.v1.routes.workflows.data_selections")

    async def admit_selection(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(route_module, "validate_selection", admit_selection)

    for workflow, target, key in (
        (first, "cultivar", "sheet-a-0001"),
        (second, "region", "sheet-b-0001"),
    ):
        response = await auth_client.put(
            f"/api/v1/workflows/{workflow.id}/data-selections/source",
            json=_apply_payload(expected_revision=None, key=key, target=target),
        )
        assert response.status_code == 200, response.text

    first_context = await auth_client.get(f"/api/v1/workflows/{first.id}/data-selections/source")
    second_context = await auth_client.get(f"/api/v1/workflows/{second.id}/data-selections/source")
    assert first_context.json()["saved_selection"]["target_authority"]["column"] == "cultivar"
    assert second_context.json()["saved_selection"]["target_authority"]["column"] == "region"

    await test_session.refresh(first, attribute_names=["nodes", "edges"])
    exact_digest = workflow_graph_digest(first)
    frozen = await execution_selection_revisions(
        test_session,
        workflow_id=first.id,
        graph_digest=exact_digest,
        source_nodes=list(first.nodes),
    )
    assert len(frozen) == 1
    assert frozen[0]["selection"]["target_authority"]["column"] == "cultivar"
    unrelated_graph_edit = await execution_selection_revisions(
        test_session,
        workflow_id=first.id,
        graph_digest="f" * 64,
        source_nodes=list(first.nodes),
    )
    assert unrelated_graph_edit[0]["revision_id"] == frozen[0]["revision_id"]
    assert unrelated_graph_edit[0]["graph_digest"] == "f" * 64

    first.nodes[0].parameters = {
        **first.nodes[0].parameters,
        "selected_file_ids": ["12"],
    }
    with pytest.raises(HTTPException) as changed_source:
        await execution_selection_revisions(
            test_session,
            workflow_id=first.id,
            graph_digest="e" * 64,
            source_nodes=list(first.nodes),
        )
    assert changed_source.value.status_code == 409


@pytest.mark.asyncio
async def test_saved_dataset_view_claim_requires_a_recorded_source_revision(
    test_session: AsyncSession, test_user: User
) -> None:
    workflow = await _workflow_with_source(test_session, test_user, name="Unrecorded saved view")
    workflow.nodes[0].parameters = {
        **workflow.nodes[0].parameters,
        "dataset_view_id": 41,
        "dataset_view_sha256": "d" * 64,
    }

    with pytest.raises(HTTPException) as refusal:
        await execution_selection_revisions(
            test_session,
            workflow_id=workflow.id,
            graph_digest=workflow_graph_digest(workflow),
            source_nodes=list(workflow.nodes),
            user_id=test_user.id,
        )

    assert refusal.value.status_code == 409
    assert "without a data-selection revision" in refusal.value.detail

    with pytest.raises(HTTPException) as missing_graph:
        await execution_selection_revisions(
            test_session,
            workflow_id=workflow.id,
            graph_digest=None,
            source_nodes=list(workflow.nodes),
            user_id=test_user.id,
        )

    assert missing_graph.value.status_code == 409
    assert "exact workflow graph" in missing_graph.value.detail


@pytest.mark.asyncio
async def test_restored_version_retains_append_only_selection_custody(
    auth_client: AsyncClient, test_session: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow = await _workflow_with_source(test_session, test_user, name="Restorable selections")
    route_module = importlib.import_module("spectra_sherpa.app.api.v1.routes.workflows.data_selections")

    async def admit_selection(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(route_module, "validate_selection", admit_selection)
    service_module = importlib.import_module("spectra_sherpa.app.services.workflow_data_selections")
    monkeypatch.setattr(service_module, "validate_selection", admit_selection)
    first = await auth_client.put(
        f"/api/v1/workflows/{workflow.id}/data-selections/source",
        json=_apply_payload(expected_revision=None, key="restore-selection-1", target="cultivar"),
    )
    assert first.status_code == 200, first.text
    version = await test_session.scalar(select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id))
    second = await auth_client.put(
        f"/api/v1/workflows/{workflow.id}/data-selections/source",
        json=_apply_payload(expected_revision=1, key="restore-selection-2", target="region"),
    )
    assert second.status_code == 200, second.text
    restored = await auth_client.post(f"/api/v1/workflows/{workflow.id}/versions/{version.id}/restore")
    assert restored.status_code == 200, restored.text
    await test_session.refresh(workflow, attribute_names=["nodes", "edges", "integrity_hash"])
    assert workflow.nodes[0].parameters["target_authority"]["column"] == "cultivar"
    frozen = await execution_selection_revisions(
        test_session,
        workflow_id=workflow.id,
        graph_digest=workflow_graph_digest(workflow),
        source_nodes=list(workflow.nodes),
    )
    assert frozen[0]["selection"]["target_authority"]["column"] == "cultivar"
    assert frozen[0]["revision_number"] == 3
    assert frozen[0]["origin"] == "version_restore"
    assert workflow.integrity_hash == workflow_graph_digest(workflow)
    history = await auth_client.get(f"/api/v1/workflows/{workflow.id}/data-selections/source/revisions")
    assert [row["selection"]["target_authority"]["column"] for row in history.json()] == [
        "cultivar",
        "region",
        "cultivar",
    ]


@pytest.mark.asyncio
async def test_restore_reconciles_source_links_and_refuses_cross_project_dataset(
    auth_client: AsyncClient, test_session: AsyncSession, test_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.project_data_source import ProjectDataSource

    project = Project(user_id=test_user.id, name="Selection project")
    other = Project(user_id=test_user.id, name="Other project")
    test_session.add_all([project, other])
    await test_session.flush()
    experiments = [
        Experiment(user_id=test_user.id, project_id=project.id, name=name, metadata_path="synthetic")
        for name in ("Source A", "Source B")
    ]
    test_session.add_all(experiments)
    await test_session.flush()
    workflow = await _workflow_with_source(test_session, test_user, name="Rebind source")
    workflow.project_id = project.id
    await test_session.commit()
    service = importlib.import_module("spectra_sherpa.app.services.workflow_data_selections")

    async def load_synthetic(*args, **kwargs):
        return SimpleNamespace(
            source_manifest_sha256=SOURCE_DIGEST,
            collection_definition_sha256=DEFINITION_DIGEST,
            scientific_collection_sha256=SCIENTIFIC_DIGEST,
        )

    monkeypatch.setattr(service, "load_project_dataset", load_synthetic)
    path = f"/api/v1/workflows/{workflow.id}/data-selections/source"
    first_version = None
    first_source_id = None
    for index, experiment in enumerate(experiments):
        payload = _apply_payload(expected_revision=index or None, key=f"source-{index}", target="unused")
        payload["selection"].update(experiment_id=experiment.id, target_authority=None, group_column=None)
        response = await auth_client.put(path, json=payload)
        assert response.status_code == 200, response.text
        await test_session.refresh(workflow, attribute_names=["primary_data_source_id", "data_source_links"])
        source_id = workflow.primary_data_source_id
        assert workflow.data_source_ids == [source_id]
        source = await test_session.get(ProjectDataSource, source_id)
        assert source.metadata_["experiment_id"] == experiment.id
        if index == 0:
            first_source_id = source_id
            first_version = await test_session.scalar(
                select(WorkflowVersion).where(WorkflowVersion.workflow_id == workflow.id)
            )
        else:
            assert source_id != first_source_id
    restored = await auth_client.post(f"/api/v1/workflows/{workflow.id}/versions/{first_version.id}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["primary_data_source_id"] == first_source_id
    assert restored.json()["data_source_ids"] == [first_source_id]
    history = await auth_client.get(path + "/revisions")
    assert [row["selection"]["experiment_id"] for row in history.json()] == [
        experiments[0].id,
        experiments[1].id,
        experiments[0].id,
    ]
    # A historical version cannot move its dataset back across current project custody.
    experiments[0].project_id = other.id
    await test_session.commit()
    refused = await auth_client.post(f"/api/v1/workflows/{workflow.id}/versions/{first_version.id}/restore")
    assert refused.status_code == 409, refused.text
    await test_session.rollback()
