"""Admission records and the canonical run share one snapshot transaction."""

import hashlib
import json

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from spectra_sherpa.app.api.v1.routes.workflows.execute import execute_saved_workflow
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
