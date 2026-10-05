"""Imported canonical model application remains valid in a spawn worker."""

from __future__ import annotations

import io
import json
import multiprocessing
import os
import zipfile
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

import spectra_sherpa.app.services.dag.nodes.data  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
from spectra_sherpa.app.api.v1.routes import projects as projects_route
from spectra_sherpa.app.lib.pca import PCAExtract
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset, SpectralAxis
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.services.canonical_project_binding import CANONICAL_LOCAL_SOURCE_NODE_ID
from spectra_sherpa.app.services.dag.executor import DAGExecutor, WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.executor_pool import (
    WorkerExecutionContext,
    _run_node_in_worker,
    set_default_pool,
)
from spectra_sherpa.app.services.execution_runtime import ApplicationModelArtifactReplay
from spectra_sherpa.app.services.model_store import ModelStore
from spectra_sherpa.core.execution_runtime import ExecutionRuntime
from spectra_sherpa.core.model_artifact import ReadOnlyModelArtifactReader
from tests.test_canonical_project_binding import _owned_input_file
from tests.test_canonical_project_import import _PACKAGE, _REVIEW_ANCHORS, _REVIEW_PACKAGE, _factory


def _save_pca_artifact(base_dir: Path) -> str:
    uid = "m3c1-pca-artifact"
    ModelStore(base_dir).save(
        uid,
        {
            "model_type": "pca",
            "serializer": PCAExtract.SERIALIZER,
            "n_features": 3,
            "n_components": 2,
            "standardized": False,
            "scaled": False,
            "scale_mode": None,
        },
        {
            "loadings": np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]),
            "mean": np.zeros(3),
            "explained_variance_ratio": np.array([0.7, 0.2]),
            "explained_variance": np.array([2.0, 1.0]),
        },
    )
    return uid


def test_imported_file_to_apply_edge_is_semantically_valid() -> None:
    executor = DAGExecutor(process_pool=None)
    executor.add_node(WorkflowNode("source", "data.file_load", {"experiment_id": 1, "file_id": 1}))
    executor.add_node(WorkflowNode("apply", "model.load_apply", {"model_id": "m3c1-pca-artifact"}))
    executor.add_edge(WorkflowEdge("source", "apply", "default", "X_new"))

    assert executor.validate() == []


def test_read_only_worker_capability_has_no_mutation_surface(tmp_path: Path) -> None:
    uid = _save_pca_artifact(tmp_path)
    reader = ReadOnlyModelArtifactReader(tmp_path)

    manifest, arrays = reader.load(uid)
    assert manifest["model_type"] == "pca"
    assert set(arrays) >= {"loadings", "mean"}
    assert not hasattr(reader, "save")
    assert not hasattr(reader, "delete")
    with pytest.raises(ValueError, match="Invalid model artifact identifier"):
        reader.load("../outside")


def test_model_apply_requires_context_when_called_in_worker(tmp_path: Path) -> None:
    uid = _save_pca_artifact(tmp_path)
    dataset = SherpaDataset(X=np.ones((2, 3)))

    with pytest.raises(PermissionError, match="execution context"):
        _run_node_in_worker("model.load_apply", "apply", {"model_id": uid}, (), {"X_new": dataset})


def test_model_apply_runs_in_fresh_spawned_worker_with_read_only_context(tmp_path: Path) -> None:
    uid = _save_pca_artifact(tmp_path)
    context = WorkerExecutionContext(
        execution_id="m3c1-test",
        runtime=ExecutionRuntime(
            model_artifact_reader=ReadOnlyModelArtifactReader(tmp_path),
            model_artifact_replay=ApplicationModelArtifactReplay(),
        ),
        capabilities=("read_model_artifact",),
        origin_pid=os.getpid(),
    )
    dataset = SherpaDataset(X=np.array([[2.0, 3.0, 4.0]]))
    try:
        pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    except (NotImplementedError, PermissionError, OSError) as exc:
        pytest.skip(f"spawn worker unavailable: {exc}")
    try:
        result = pool.submit(
            _run_node_in_worker,
            "model.load_apply",
            "apply",
            {"model_id": uid},
            (),
            {"X_new": dataset},
            context,
        ).result(timeout=30)
    finally:
        pool.shutdown(wait=True)

    np.testing.assert_allclose(result.outputs["result"], [[2.0, 3.0]])
    assert result.outputs["model_id"] == uid
    provenance = result.diagnostics["worker_execution"]
    assert provenance["mode"] == "spawned_worker"
    assert provenance["origin_pid"] == os.getpid()
    assert provenance["worker_pid"] != os.getpid()


@pytest.mark.anyio
async def test_canonical_campaign_project_imports_and_applies_in_spawned_workflow_worker(
    auth_client: AsyncClient,
    test_engine,
    test_session: AsyncSession,
    test_user,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the sealed canonical package through the real OSS routes.

    A managed campaign produces a data-free package.  An OSS scientist binds
    an owned local source, runs the exact fitted-state application DAG, and
    retains the package identities through restart and re-export.
    """
    import spectra_sherpa.app.services.canonical_project_custody as custody

    monkeypatch.setattr(projects_route, "async_session", _factory(test_engine))
    # The import route authenticates the publisher attestation against the
    # recipient's configured anchors, so this journey provisions the exact
    # anchors that sealed the fixture package.
    anchors_path = tmp_path / "campaign-review-trust-anchors.json"
    anchors_path.write_text(json.dumps(_REVIEW_ANCHORS.as_dict()), encoding="utf-8")
    monkeypatch.setattr(
        projects_route,
        "settings",
        replace(
            projects_route.settings,
            data_dir=tmp_path,
            campaign_review_publisher_trust_anchors_path=str(anchors_path),
        ),
    )
    monkeypatch.setattr(custody, "settings", replace(custody.settings, data_dir=tmp_path))

    imported = await auth_client.post(
        "/api/v1/projects/canonical-import",
        files={"file": ("campaign-review.sherpa", _REVIEW_PACKAGE.archive, "application/octet-stream")},
    )
    assert imported.status_code == 201, imported.text
    imported_payload = imported.json()
    assert imported_payload["status"] == "awaiting_local_data_binding"
    assert imported_payload["artifact_digest"] == _PACKAGE.artifact.artifact_digest

    workflow = await test_session.get(Workflow, imported_payload["workflow_id"])
    assert workflow is not None and workflow.project_id == imported_payload["project_id"]
    experiment, file_record = await _owned_input_file(
        test_session,
        user_id=test_user.id,
        project_id=workflow.project_id,
    )
    bound = await auth_client.put(
        f"/api/v1/workflows/{workflow.id}/canonical-source",
        json={"experiment_id": experiment.id, "file_id": file_record.id, "stage": "raw"},
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["source_node_id"] == CANONICAL_LOCAL_SOURCE_NODE_ID

    async def _load_selected_local_source(self, *args):
        del self, args
        return SherpaDataset(
            X=np.arange(24, dtype=float).reshape(3, 8),
            domain=DomainContext(technique="NIR", measurement_mode="reflectance"),
            feature_axis=SpectralAxis(values=np.arange(8, dtype=float), units="cm-1"),
        )

    monkeypatch.setattr(
        "spectra_sherpa.app.services.dag.nodes.data.file_load_node.FileLoadNode.execute",
        _load_selected_local_source,
    )

    pool: ProcessPoolExecutor | None = None
    try:
        pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    except (NotImplementedError, PermissionError, OSError) as exc:
        pytest.skip(f"spawn worker unavailable: {exc}")
    set_default_pool(pool)
    try:
        validation = await auth_client.post(f"/api/v1/workflows/{workflow.id}/validate")
        assert validation.status_code == 200, validation.text
        assert validation.json()["is_valid"] is True
        assert len(validation.json()["semantic_edges"]) == 2
        assert {edge["status"] for edge in validation.json()["semantic_edges"]} == {"typed_valid"}

        preflight = await auth_client.post(f"/api/v1/workflows/{workflow.id}/preflight")
        assert preflight.status_code == 200, preflight.text
        assert preflight.json()["semantic_edges"] == validation.json()["semantic_edges"]

        workflow_response = await auth_client.get(f"/api/v1/workflows/{workflow.id}")
        assert workflow_response.status_code == 200, workflow_response.text
        workflow_payload = workflow_response.json()
        source_node = next(node for node in workflow_payload["nodes"] if node["node_type"] == "data.file_load")
        scale_node = next(
            node for node in workflow_payload["nodes"] if node["node_type"] == "preprocess.apply_fitted_scale"
        )
        model_node = next(node for node in workflow_payload["nodes"] if node["node_type"] == "model.apply_fitted_pls")
        source_node_id = source_node["node_id"]
        scale_node_id = scale_node["node_id"]
        model_node_id = model_node["node_id"]
        assert source_node_id == CANONICAL_LOCAL_SOURCE_NODE_ID
        assert {node["node_type"] for node in workflow_payload["nodes"]} == {
            "data.file_load",
            "preprocess.apply_fitted_scale",
            "model.apply_fitted_pls",
        }
        assert {
            (edge["from_node_id"], edge["to_node_id"], edge["from_output"], edge["to_input"])
            for edge in workflow_payload["edges"]
        } == {
            (source_node_id, scale_node_id, "default", "default"),
            (scale_node_id, model_node_id, "default", "default"),
        }

        executed = await auth_client.post(f"/api/v1/workflows/{workflow.id}/execute", json={})
        assert executed.status_code == 200, executed.text
        response = executed.json()
        assert response["status"] == "completed", response["error"]
        assert response["node_statuses"] == {
            source_node_id: "completed",
            scale_node_id: "completed",
            model_node_id: "completed",
        }
        first_predictions = np.asarray(response["results"][model_node_id]["default"])
        assert first_predictions.shape == (3, 1)
        assert np.isfinite(first_predictions).all()

        # The exact presentation authority exported with the admitted
        # application DAG must survive import and bind the live execution.
        portable_model_presentation = next(
            node for node in _PACKAGE.presentation_manifest["nodes"] if node["operation_id"] == "model.apply_fitted_pls"
        )
        executed_model_presentation = response["result_presentations"][model_node_id]
        assert executed_model_presentation["contract_digest"] == portable_model_presentation["contract_digest"]
        assert executed_model_presentation["contract"] == portable_model_presentation["contract"]
        assert executed_model_presentation["presentations"]
        assert all(presentation["content_categories"] for presentation in executed_model_presentation["presentations"])
        for node_id in (scale_node_id, model_node_id):
            provenance = response["diagnostics"][node_id]["worker_execution"]
            assert provenance["mode"] == "spawned_worker"
            assert provenance["origin_pid"] != provenance["worker_pid"]
            assert (
                response["diagnostics"][node_id]["canonical_artifact"]["artifact_digest"]
                == _PACKAGE.artifact.artifact_digest
            )

        # A new pool must resolve the sealed fitted-state custody again; no
        # model state is carried in worker memory between the executions.
        set_default_pool(None)
        pool.shutdown(wait=True)
        pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
        set_default_pool(pool)

        rerun = await auth_client.post(f"/api/v1/workflows/{workflow.id}/execute", json={})
        assert rerun.status_code == 200, rerun.text
        rerun_response = rerun.json()
        assert rerun_response["status"] == "completed", rerun_response["error"]
        np.testing.assert_allclose(rerun_response["results"][model_node_id]["default"], first_predictions)
        assert rerun_response["result_presentations"][model_node_id] == executed_model_presentation

        # The ordinary OSS export retains the sealed package identity and
        # contains only the current canonical application operations.
        reexport = await auth_client.get(f"/api/v1/projects/{imported_payload['project_id']}/export/sherpa")
        assert reexport.status_code == 200, reexport.text
        with zipfile.ZipFile(io.BytesIO(reexport.content)) as archive:
            exported = json.loads(archive.read("project.json"))
        assert exported["metadata"]["canonical_project"]["artifact_digest"] == _PACKAGE.artifact.artifact_digest
        exported_node_types = {
            node["node_type"] for exported_workflow in exported["workflows"] for node in exported_workflow["nodes"]
        }
        assert exported_node_types == {
            "data.file_load",
            "preprocess.apply_fitted_scale",
            "model.apply_fitted_pls",
        }
    finally:
        set_default_pool(None)
        if pool is not None:
            pool.shutdown(wait=True)
