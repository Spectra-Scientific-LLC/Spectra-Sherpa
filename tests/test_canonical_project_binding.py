"""M4.10e3c tests for local source binding and durable canonical execution."""

from __future__ import annotations

import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import spectra_sherpa.app.services.dag.nodes.data  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.modeling  # noqa: F401
import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset, SpectralAxis
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.services.canonical_project_binding import (
    CANONICAL_LOCAL_SOURCE_NODE_ID,
    CanonicalProjectBindingError,
    bind_canonical_project_source,
)
from spectra_sherpa.app.services.canonical_project_dependencies import CanonicalProjectDependencyReadiness
from spectra_sherpa.app.services.canonical_project_import import import_canonical_project
from spectra_sherpa.app.services.dag.executor import DAGExecutor
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge as DAGEdge
from spectra_sherpa.app.services.dag.executor_types import WorkflowNode as DAGNode
from spectra_sherpa.app.services.dag.managed_optimization_profile import managed_optimization_profile
from spectra_sherpa.app.services.experiments import experiment_dir
from spectra_sherpa.app.services.workflow_access import validate_canonical_application_graph
from tests.test_canonical_project_import import _PACKAGE, _factory

MANAGED_OPTIMIZATION_PROFILE = managed_optimization_profile()


@pytest.fixture(autouse=True)
def _canonical_project_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Make custody's server-owned root match this isolated test import."""

    import spectra_sherpa.app.services.canonical_project_custody as custody

    monkeypatch.setattr(custody, "settings", replace(custody.settings, data_dir=tmp_path))


async def _owned_input_file(
    session: AsyncSession,
    *,
    user_id: int,
    project_id: int,
) -> tuple[Experiment, ExperimentFile]:
    experiment = Experiment(
        user_id=user_id,
        project_id=project_id,
        name="Canonical local input",
        metadata_path="",
    )
    session.add(experiment)
    await session.flush()
    file_record = ExperimentFile(
        experiment_id=experiment.id,
        file_path="raw/local-input.csv",
        file_type="csv",
        stage="raw",
    )
    session.add(file_record)
    await session.commit()
    source = experiment_dir(experiment.id) / file_record.file_path
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("sample,1000,1100\nlocal,1.0,2.0\n", encoding="utf-8")
    return experiment, file_record


@pytest.mark.asyncio
async def test_binding_adds_one_visible_local_source_without_altering_application_nodes(
    test_engine,
    test_session: AsyncSession,
    test_user,
    tmp_path: Path,
) -> None:
    imported = await import_canonical_project(
        _factory(test_engine),
        user_id=test_user.id,
        archive=_PACKAGE.archive,
        data_dir=tmp_path,
        max_uncompressed_bytes=1024 * 1024,
    )
    workflow = await test_session.get(Workflow, imported.workflow_id)
    assert workflow is not None and workflow.project_id is not None
    experiment, file_record = await _owned_input_file(
        test_session, user_id=test_user.id, project_id=workflow.project_id
    )

    bound = await bind_canonical_project_source(
        test_session,
        user_id=test_user.id,
        workflow_id=workflow.id,
        experiment_id=experiment.id,
        file_id=file_record.id,
        stage="raw",
    )
    await test_session.commit()

    stored = await test_session.scalar(
        select(Workflow).where(Workflow.id == workflow.id).execution_options(populate_existing=True)
    )
    assert stored is not None
    await test_session.refresh(stored, attribute_names=["nodes", "edges", "data_source_links"])
    source = next(node for node in stored.nodes if node.node_id == CANONICAL_LOCAL_SOURCE_NODE_ID)
    assert source.node_type == "data.file_load"
    assert source.parameters == {"experiment_id": experiment.id, "file_id": file_record.id, "stage": "raw"}
    assert source.execution_order == 0
    assert {(edge.from_node_id, edge.to_node_id) for edge in stored.edges} >= {
        (CANONICAL_LOCAL_SOURCE_NODE_ID, "scale"),
        ("scale", "model"),
    }
    assert stored.integrity_hash == bound.integrity_hash
    assert stored.primary_data_source_id is not None
    assert bound.artifact_read_grant.artifact_digest == _PACKAGE.artifact.artifact_digest


@pytest.mark.asyncio
async def test_binding_refuses_a_canonical_application_graph_edited_after_import(
    test_engine,
    test_session: AsyncSession,
    test_user,
    tmp_path: Path,
) -> None:
    """The local source is editable; the admitted application recipe is not."""

    imported = await import_canonical_project(
        _factory(test_engine),
        user_id=test_user.id,
        archive=_PACKAGE.archive,
        data_dir=tmp_path,
        max_uncompressed_bytes=1024 * 1024,
    )
    workflow = await test_session.get(Workflow, imported.workflow_id)
    assert workflow is not None and workflow.project_id is not None
    await test_session.refresh(workflow, attribute_names=["nodes", "edges"])
    model = next(node for node in workflow.nodes if node.node_id == "model")
    model.parameters = {**model.parameters, "tampered": True}
    await test_session.commit()
    experiment, file_record = await _owned_input_file(
        test_session, user_id=test_user.id, project_id=workflow.project_id
    )

    with pytest.raises(CanonicalProjectBindingError, match="application graph is unavailable"):
        await bind_canonical_project_source(
            test_session,
            user_id=test_user.id,
            workflow_id=workflow.id,
            experiment_id=experiment.id,
            file_id=file_record.id,
            stage="raw",
        )


@pytest.mark.asyncio
async def test_binding_preserves_dependency_blocked_status_when_exact_runtime_is_unavailable(
    test_engine,
    test_session: AsyncSession,
    test_user,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scientist may select local data without turning a blocked package active."""

    import spectra_sherpa.app.services.canonical_project_binding as canonical_binding

    imported = await import_canonical_project(
        _factory(test_engine),
        user_id=test_user.id,
        archive=_PACKAGE.archive,
        data_dir=tmp_path,
        max_uncompressed_bytes=1024 * 1024,
    )
    workflow = await test_session.get(Workflow, imported.workflow_id)
    assert workflow is not None and workflow.project_id is not None
    experiment, file_record = await _owned_input_file(
        test_session, user_id=test_user.id, project_id=workflow.project_id
    )
    blocked = CanonicalProjectDependencyReadiness(
        ready=False,
        source_operation_ids=("baseline.rubberband",),
        blockers=("canonical_runtime_unavailable_or_unpinned",),
        remediation=("Install the exact certified runtime, then restart and revalidate.",),
    )
    monkeypatch.setattr(canonical_binding, "canonical_project_dependency_readiness", lambda _plan: blocked)

    bound = await bind_canonical_project_source(
        test_session,
        user_id=test_user.id,
        workflow_id=workflow.id,
        experiment_id=experiment.id,
        file_id=file_record.id,
        stage="raw",
    )
    await test_session.commit()
    stored = await test_session.get(Workflow, workflow.id)

    assert bound.status == "dependency_blocked"
    assert stored is not None and stored.status == "dependency_blocked"


@pytest.mark.asyncio
async def test_binding_route_accepts_only_the_owner_project_source(
    auth_client: AsyncClient,
    test_engine,
    test_session: AsyncSession,
    test_user,
    tmp_path: Path,
) -> None:
    """The user-facing route persists the same closed binding as the service."""

    imported = await import_canonical_project(
        _factory(test_engine),
        user_id=test_user.id,
        archive=_PACKAGE.archive,
        data_dir=tmp_path,
        max_uncompressed_bytes=1024 * 1024,
    )
    workflow = await test_session.get(Workflow, imported.workflow_id)
    assert workflow is not None and workflow.project_id is not None
    experiment, file_record = await _owned_input_file(
        test_session, user_id=test_user.id, project_id=workflow.project_id
    )

    response = await auth_client.put(
        f"/api/v1/workflows/{workflow.id}/canonical-source",
        json={"experiment_id": experiment.id, "file_id": file_record.id, "stage": "raw"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["workflow_id"] == workflow.id
    assert payload["source_node_id"] == CANONICAL_LOCAL_SOURCE_NODE_ID
    assert payload["status"] == "ready_for_application"
    assert len(payload["integrity_hash"]) == 64


@pytest.mark.asyncio
async def test_execution_guard_rejects_a_noncanonical_source_shape(
    test_engine,
    test_session: AsyncSession,
    test_user,
    tmp_path: Path,
) -> None:
    imported = await import_canonical_project(
        _factory(test_engine),
        user_id=test_user.id,
        archive=_PACKAGE.archive,
        data_dir=tmp_path,
        max_uncompressed_bytes=1024 * 1024,
    )
    workflow = await test_session.get(Workflow, imported.workflow_id)
    assert workflow is not None and workflow.project_id is not None
    experiment, file_record = await _owned_input_file(
        test_session, user_id=test_user.id, project_id=workflow.project_id
    )
    bound = await bind_canonical_project_source(
        test_session,
        user_id=test_user.id,
        workflow_id=workflow.id,
        experiment_id=experiment.id,
        file_id=file_record.id,
        stage="raw",
    )
    await test_session.commit()
    await test_session.refresh(workflow, attribute_names=["nodes", "edges"])
    source = next(node for node in workflow.nodes if node.node_id == CANONICAL_LOCAL_SOURCE_NODE_ID)
    source.parameters = {**source.parameters, "path": "/not-an-authorized-source"}

    with pytest.raises(HTTPException, match="Canonical application graph is unavailable"):
        validate_canonical_application_graph(
            workflow.nodes,
            workflow.edges,
            bound.artifact_read_grant.application_integrity_hash,
        )


@pytest.mark.asyncio
async def test_execution_route_rejects_any_runtime_override_for_canonical_workflow(
    auth_client: AsyncClient,
    test_engine,
    test_session: AsyncSession,
    test_user,
    tmp_path: Path,
) -> None:
    """A request cannot replace an admitted apply-node state binding transiently."""

    imported = await import_canonical_project(
        _factory(test_engine),
        user_id=test_user.id,
        archive=_PACKAGE.archive,
        data_dir=tmp_path,
        max_uncompressed_bytes=1024 * 1024,
    )
    workflow = await test_session.get(Workflow, imported.workflow_id)
    assert workflow is not None and workflow.project_id is not None
    experiment, file_record = await _owned_input_file(
        test_session, user_id=test_user.id, project_id=workflow.project_id
    )
    await bind_canonical_project_source(
        test_session,
        user_id=test_user.id,
        workflow_id=workflow.id,
        experiment_id=experiment.id,
        file_id=file_record.id,
        stage="raw",
    )
    await test_session.commit()

    response = await auth_client.post(
        f"/api/v1/workflows/{workflow.id}/execute",
        json={"initial_data": {"model": {"artifact_digest": "0" * 64}}},
    )

    assert response.status_code == 422, response.text
    assert "persisted workflow state" in response.json()["detail"]


@pytest.mark.asyncio
async def test_execution_route_refuses_a_dependency_blocked_canonical_project_before_worker_grant(
    auth_client: AsyncClient,
    test_engine,
    test_session: AsyncSession,
    test_user,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unpinned runtime may not reach artifact-capable execution."""

    import spectra_sherpa.app.api.v1.routes.workflows.execute as execute_route

    imported = await import_canonical_project(
        _factory(test_engine),
        user_id=test_user.id,
        archive=_PACKAGE.archive,
        data_dir=tmp_path,
        max_uncompressed_bytes=1024 * 1024,
    )
    workflow = await test_session.get(Workflow, imported.workflow_id)
    assert workflow is not None and workflow.project_id is not None
    experiment, file_record = await _owned_input_file(
        test_session, user_id=test_user.id, project_id=workflow.project_id
    )
    await bind_canonical_project_source(
        test_session,
        user_id=test_user.id,
        workflow_id=workflow.id,
        experiment_id=experiment.id,
        file_id=file_record.id,
        stage="raw",
    )
    await test_session.commit()
    blocked = CanonicalProjectDependencyReadiness(
        ready=False,
        source_operation_ids=("baseline.rubberband",),
        blockers=("canonical_runtime_unavailable_or_unpinned",),
        remediation=("Install the exact certified runtime, then restart and revalidate.",),
    )
    monkeypatch.setattr(execute_route, "canonical_project_dependency_readiness", lambda _plan: blocked)

    async def _grant_must_not_be_resolved(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("dependency-blocked execution must not resolve an artifact read grant")

    import spectra_sherpa.app.services.canonical_project_custody as custody

    monkeypatch.setattr(custody, "resolve_canonical_artifact_read_grant", _grant_must_not_be_resolved)

    response = await auth_client.post(f"/api/v1/workflows/{workflow.id}/execute", json={})

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == {
        "code": "canonical_dependency_blocked",
        "message": "Canonical project runtime dependencies are unavailable or do not match the certified pins.",
        "remediation": ["Install the exact certified runtime, then restart and revalidate."],
    }

    validation = await auth_client.post(f"/api/v1/workflows/{workflow.id}/validate")

    assert validation.status_code == 200, validation.text
    assert validation.json()["is_valid"] is False
    assert {issue["code"] for issue in validation.json()["issues"] if issue["level"] == "error"} >= {
        "canonical_dependency_blocked"
    }


@pytest.mark.asyncio
async def test_bound_project_executes_canonical_application_in_spawned_worker(
    test_engine,
    test_session: AsyncSession,
    test_user,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The persistent source and custody grant are sufficient after a pool restart."""

    imported = await import_canonical_project(
        _factory(test_engine),
        user_id=test_user.id,
        archive=_PACKAGE.archive,
        data_dir=tmp_path,
        max_uncompressed_bytes=1024 * 1024,
    )
    workflow = await test_session.get(Workflow, imported.workflow_id)
    assert workflow is not None and workflow.project_id is not None
    experiment, file_record = await _owned_input_file(
        test_session, user_id=test_user.id, project_id=workflow.project_id
    )
    bound = await bind_canonical_project_source(
        test_session,
        user_id=test_user.id,
        workflow_id=workflow.id,
        experiment_id=experiment.id,
        file_id=file_record.id,
        stage="raw",
    )
    await test_session.commit()
    await test_session.refresh(workflow, attribute_names=["nodes", "edges"])

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
    try:
        pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    except (NotImplementedError, PermissionError, OSError) as exc:
        pytest.skip(f"spawn worker unavailable: {exc}")
    try:

        async def _execute_once() -> tuple[np.ndarray, dict[str, object]]:
            from spectra_sherpa.core.canonical_artifact import ReadOnlyCanonicalArtifactReader
            from spectra_sherpa.core.execution_runtime import ExecutionRuntime

            grant = bound.artifact_read_grant
            executor = DAGExecutor(
                process_pool=pool,
                runtime=ExecutionRuntime(
                    canonical_artifact_reader=ReadOnlyCanonicalArtifactReader(
                        grant.artifact_dir.parent,
                        allowed_artifact_digests=(grant.artifact_digest,),
                        artifact_root=grant.artifact_dir.parent,
                    )
                ),
            )
            for node in workflow.nodes:
                executor.add_node(DAGNode(node.node_id, node.node_type, node.parameters))
            for edge in workflow.edges:
                executor.add_edge(DAGEdge(edge.from_node_id, edge.to_node_id, edge.from_output, edge.to_input))
            results = await executor.execute()
            return np.asarray(results["model"]["default"]), executor.diagnostics["model"]["worker_execution"]

        first_predictions, first_provenance = await _execute_once()
        assert first_provenance["mode"] == "spawned_worker"
        assert first_provenance["origin_pid"] == os.getpid()
        assert first_provenance["worker_pid"] != os.getpid()
    finally:
        pool.shutdown(wait=True)

    # A fresh process pool repeats the same artifact-bound application without
    # carrying an in-memory reader or any fitted state across the restart.
    pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    try:
        second_predictions, second_provenance = await _execute_once()
    finally:
        pool.shutdown(wait=True)
    np.testing.assert_allclose(second_predictions, first_predictions)
    assert second_provenance["mode"] == "spawned_worker"
