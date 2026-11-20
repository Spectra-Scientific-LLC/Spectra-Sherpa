"""Admission records and the canonical run share one snapshot transaction."""

import hashlib
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from spectra_sherpa.app.api.v1.routes.workflows.execute import execute_saved_workflow
from spectra_sherpa.app.contracts import saved_workflow_access
from spectra_sherpa.app.contracts.scientific_access import ScientificAccessDenied
from spectra_sherpa.app.models.execution_run import ExecutionRun
from spectra_sherpa.app.models.workflow import Workflow
from spectra_sherpa.app.models.workflow_node import WorkflowNode
from spectra_sherpa.app.schemas.workflows import WorkflowExecuteRequest
from spectra_sherpa.app.types import ensure_type_registry_loaded
from tests.test_frozen_workflow_sources import source  # noqa: F401


class Admission:
    def __init__(self, path, *, fail=False, withdrawn=False):
        self.path = path
        self.original_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.fail = fail
        self.withdrawn = withdrawn
        self.run_id = None
        self.events = []

    async def lock_authority(self, session, **kwargs):
        self.events.append("authority")

    async def admit(self, session, snapshot):
        self.events.append("snapshot")
        self.snapshot = snapshot
        from spectra_sherpa.app.services.dag.nodes.data.file_load_node import FileLoadNode
        from spectra_sherpa.core.execution_runtime import ExecutionRuntime

        definition = snapshot.definition["nodes"][0]
        node = FileLoadNode(definition["node_id"], definition["parameters"])
        node.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=snapshot.sources))
        data = (await node.execute())["default"]
        assert data.X.tolist() == [[1, 2, 3], [4, 5, 6]]
        envelope = await snapshot.sources.resolve_experiment_file(
            **{key: definition["parameters"][key] for key in ("experiment_id", "file_id", "stage")}
        )
        assert envelope.sha256 == self.original_digest
        # An unrelated row makes rollback/commit of caller-owned work observable.
        row = Workflow(user_id=snapshot.actor_id, name="admission-owned marker")
        session.add(row)
        await session.flush()
        self.marker_id = row.id
        self.path.write_text("1000,1001,1002\n90,80,70\n60,50,40\n")

    async def bind_run(self, session, *, run_id):
        self.events.append("run")
        self.run_id = run_id
        if self.fail:
            raise ValueError("synthetic binding failure")

    async def verify_current(self, session):
        if self.withdrawn:
            raise ValueError("synthetic authority withdrawal")


@pytest.fixture
async def saved(test_session, test_user, source):  # noqa: F811
    ensure_type_registry_loaded()
    node, path = source
    workflow = Workflow(user_id=test_user.id, name="Saved source")
    test_session.add(workflow)
    await test_session.flush()
    test_session.add(
        WorkflowNode(
            workflow_id=workflow.id,
            node_id="source",
            node_type=node.node_type,
            parameters=node.parameters,
            position_x=0,
            position_y=0,
        )
    )
    await test_session.commit()
    return workflow.id, path


@pytest.mark.parametrize("fail", [False, True])
async def test_atomic_marker_and_canonical_run(test_session, test_user, saved, fail):
    workflow_id, path = saved
    admission = Admission(path, fail=fail)
    async with async_sessionmaker(test_session.bind, expire_on_commit=False)() as session:
        if fail:
            with pytest.raises(ValueError, match="binding failure"):
                await execute_saved_workflow(
                    workflow_id, WorkflowExecuteRequest(), session, test_user, "admission_key_1", admission=admission
                )
        else:
            response = await execute_saved_workflow(
                workflow_id, WorkflowExecuteRequest(), session, test_user, "admission_key_1", admission=admission
            )
            assert response.run_id == admission.run_id and response.status == "completed"
    assert admission.events == ["authority", "snapshot", "run"]
    async with async_sessionmaker(test_session.bind, expire_on_commit=False)() as check:
        runs = list((await check.scalars(select(ExecutionRun))).all())
        markers = list((await check.scalars(select(Workflow).where(Workflow.name == "admission-owned marker"))).all())
        assert len(runs) == len(markers) == (0 if fail else 1)
        if not fail:
            assert runs[0].id == admission.run_id
            result = runs[0].results_summary["source"]["default"]
            assert result["data"] == [[1, 2, 3], [4, 5, 6]]
            assert admission.original_digest in json.dumps(result)


@pytest.mark.parametrize("node_id", [None, "source"])
async def test_host_workflow_policy_precedes_run_reservation(test_session, test_user, saved, monkeypatch, node_id):
    workflow_id, path = saved
    trusted = Admission(path)

    async def require_admission(session, actor_id, workflow, operation, admission):
        assert actor_id == test_user.id and workflow.id == workflow_id
        assert operation == "run"
        if admission is not trusted:
            raise HTTPException(409, "Workflow approval required")

    monkeypatch.setattr(saved_workflow_access, "_policy", None)
    saved_workflow_access.set_saved_workflow_policy(require_admission)
    sessions = async_sessionmaker(test_session.bind, expire_on_commit=False)
    async with sessions() as session:
        with pytest.raises(HTTPException, match="Workflow approval required"):
            await execute_saved_workflow(
                workflow_id, WorkflowExecuteRequest(node_id=node_id), session, test_user, "policy_check_1"
            )
        assert not (await session.scalars(select(ExecutionRun))).all()
    async with sessions() as session:
        result = await execute_saved_workflow(
            workflow_id, WorkflowExecuteRequest(), session, test_user, "policy_check_1", admission=trusted
        )
    assert result.status == "completed"
    async with sessions() as session:
        with pytest.raises(HTTPException, match="Workflow approval required"):
            await execute_saved_workflow(workflow_id, WorkflowExecuteRequest(), session, test_user, "policy_check_1")


async def test_existing_transaction_is_not_implicitly_committed(test_session, test_user, saved):
    workflow_id, path = saved
    marker = Workflow(user_id=test_user.id, name="unrelated staged mutation")
    test_session.add(marker)
    await test_session.flush()
    with pytest.raises(ValueError, match="fresh dedicated session"):
        await execute_saved_workflow(
            workflow_id, WorkflowExecuteRequest(), test_session, test_user, "admission_key_2", admission=Admission(path)
        )
    await test_session.rollback()
    assert not (await test_session.scalars(select(Workflow).where(Workflow.name == "unrelated staged mutation"))).all()


async def test_withdrawal_never_retains_partial_output(test_session, test_user, saved):
    workflow_id, path = saved
    admission = Admission(path, withdrawn=True)
    async with async_sessionmaker(test_session.bind, expire_on_commit=False)() as session:
        with pytest.raises(ScientificAccessDenied):
            await execute_saved_workflow(
                workflow_id, WorkflowExecuteRequest(), session, test_user, "admission_key_3", admission=admission
            )
    row = await test_session.get(ExecutionRun, admission.run_id)
    assert row.status == "cancelled" and row.results_summary == {}


@pytest.fixture(params=["sqlite", "postgres"])
async def test_engine(request):
    """Opt-in real PostgreSQL schema; ordinary test runs keep SQLite coverage."""
    import os
    import uuid

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import StaticPool

    from spectra_sherpa.app.db.base import Base

    schema = None
    admin = None
    if request.param == "postgres":
        url = os.environ.get("SPECTRA_ADMISSION_TEST_DATABASE_URL")
        if not url:
            pytest.skip("Set SPECTRA_ADMISSION_TEST_DATABASE_URL for real PostgreSQL qualification")
        schema = "admission_" + uuid.uuid4().hex
        admin = create_async_engine(url)
        async with admin.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    else:
        engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield engine
    finally:
        await engine.dispose()
        if admin is not None:
            async with admin.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            await admin.dispose()


@pytest.mark.parametrize("invalid", ["custom_reader", "extra_model"])
async def test_invalid_captured_models_refused_before_reservation(test_session, test_user, saved, invalid):
    from spectra_sherpa.core.captured_model_artifacts import CapturedModelArtifacts
    from tests.test_captured_model_artifacts import envelope

    workflow_id, path = saved

    class CapturingAdmission(Admission):
        async def admit(self, session, snapshot):
            await super().admit(session, snapshot)
            return object() if invalid == "custom_reader" else CapturedModelArtifacts((envelope(),))

    admission = CapturingAdmission(path)
    async with async_sessionmaker(test_session.bind, expire_on_commit=False)() as session:
        with pytest.raises(ValueError, match="captured model|Captured models"):
            await execute_saved_workflow(
                workflow_id, WorkflowExecuteRequest(), session, test_user, "captured_invalid", admission=admission
            )
    assert admission.run_id is None
    async with async_sessionmaker(test_session.bind, expire_on_commit=False)() as check:
        assert not (await check.scalars(select(ExecutionRun))).all()
        assert not (await check.scalars(select(Workflow).where(Workflow.name == "admission-owned marker"))).all()


async def test_captured_model_survives_live_deletion_in_saved_execution(
    test_session, test_user, saved, tmp_path, monkeypatch
):
    import shutil
    from pathlib import Path

    import numpy as np

    from spectra_sherpa.app.lib.sherpa_dataset import TargetContext
    from spectra_sherpa.app.models.workflow_edge import WorkflowEdge as StoredEdge
    from spectra_sherpa.app.services import model_store
    from spectra_sherpa.app.services.dag.executor import DAGExecutor
    from spectra_sherpa.app.services.dag.executor_pool import IsolatedWorkerPool, get_default_pool, set_default_pool
    from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge as Edge
    from spectra_sherpa.app.services.dag.executor_types import WorkflowNode as Node
    from spectra_sherpa.app.services.execution_runtime import build_application_execution_runtime
    from spectra_sherpa.app.services.frozen_workflow_sources import freeze_workflow_sources
    from spectra_sherpa.app.services.model_store import ModelStore, persist_model_artifact_records
    from spectra_sherpa.core.captured_model_artifacts import CapturedModelArtifact, CapturedModelArtifacts
    from spectra_sherpa.core.execution_runtime import ExecutionRuntime

    workflow_id, _ = saved
    source_node = await test_session.scalar(select(WorkflowNode).where(WorkflowNode.workflow_id == workflow_id))
    store = ModelStore(tmp_path)
    monkeypatch.setattr(model_store, "_store", store)
    old_pool = get_default_pool()
    set_default_pool(None)
    pool = IsolatedWorkerPool(1)
    try:
        async with freeze_workflow_sources(
            test_session, nodes=[source_node], actor_id=test_user.id, project_id=None
        ) as sources:
            source_executor = DAGExecutor(runtime=build_application_execution_runtime(dataset_source_resolver=sources))
            source_executor.add_node(Node("source", source_node.node_type, source_node.parameters))
            dataset = (await source_executor.execute())["source"]["default"]
        dataset.target = np.array([1.0, 2.0])
        dataset.target_context = TargetContext(target_type="continuous", target_names=["response"])
        trainer = DAGExecutor(runtime=ExecutionRuntime(model_artifact_writer=store))
        trainer.add_node(Node("training", "deploy.input", {"stream_name": "training"}))
        trainer.add_node(Node("fit", "model.fitted_pls", {"n_components": 1}))
        trainer.add_edge(Edge("training", "fit", "default", "default"))
        trainer.inject_deployment_input("training", dataset, stream_name="training")
        await trainer.execute()
        await persist_model_artifact_records(test_session, trainer.saved_artifacts, test_user.id)
        uid = trainer.saved_artifacts[0]["artifact_uid"]
        directory = Path(store.artifact_directory(uid))
        captured = CapturedModelArtifacts(
            (
                CapturedModelArtifact(
                    uid, (directory / "manifest.json").read_bytes(), (directory / "arrays.npz").read_bytes()
                ),
            )
        )
        test_session.add(
            WorkflowNode(
                workflow_id=workflow_id,
                node_id="apply",
                node_type="model.load_apply",
                parameters={"model_id": uid},
                position_x=1,
                position_y=0,
            )
        )
        test_session.add(
            StoredEdge(
                workflow_id=workflow_id,
                from_node_id="source",
                to_node_id="apply",
                from_output="default",
                to_input="X_new",
            )
        )
        await test_session.commit()

        class CapturingAdmission:
            async def lock_authority(self, session, **kwargs):
                pass

            async def admit(self, session, snapshot):
                assert snapshot.actor_id == test_user.id
                assert snapshot.definition["nodes"][1]["parameters"]["model_id"] == uid
                return captured

            async def bind_run(self, session, *, run_id):
                self.run_id = run_id

            async def verify_current(self, session):
                pass  # This test's trusted caller authorizes the captured bytes.

        original = DAGExecutor.execute

        async def remove_live_before_compute(executor, *args, **kwargs):
            if "apply" in executor.nodes and directory.exists():
                shutil.rmtree(directory)
            return await original(executor, *args, **kwargs)

        monkeypatch.setattr(DAGExecutor, "execute", remove_live_before_compute)
        set_default_pool(pool)
        admission = CapturingAdmission()
        async with async_sessionmaker(test_session.bind, expire_on_commit=False)() as session:
            response = await execute_saved_workflow(
                workflow_id,
                WorkflowExecuteRequest(),
                session,
                test_user,
                "captured_saved_positive",
                admission=admission,
            )
        assert response.status == "completed" and response.run_id == admission.run_id
        assert not directory.exists()
        async with async_sessionmaker(test_session.bind, expire_on_commit=False)() as check:
            run = await check.get(ExecutionRun, admission.run_id)
            assert run.status == "completed" and run.results_summary["apply"]["model_id"] == uid
            assert run.results_summary["apply"]["result"]
    finally:
        pool.shutdown()
        set_default_pool(old_pool)
