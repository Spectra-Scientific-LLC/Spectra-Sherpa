"""Captured envelopes retain the actual scientific source after live changes."""

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.models.experiment import Experiment
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.services import frozen_workflow_sources as frozen
from spectra_sherpa.app.services.dag.nodes.data.file_load_node import FileLoadNode
from spectra_sherpa.core.execution_runtime import ExecutionRuntime


@pytest.fixture
async def source(test_session, test_user):
    experiment = Experiment(user_id=test_user.id, name="Snapshot spectra", metadata_path="metadata.json")
    test_session.add(experiment)
    await test_session.flush()
    path = settings.data_dir / "experiments" / f"exp_{experiment.id:03d}" / "raw" / "spectra.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("1000,1001,1002\n1,2,3\n4,5,6\n")
    record = ExperimentFile(experiment_id=experiment.id, file_path="raw/spectra.csv", stage="raw")
    test_session.add(record)
    await test_session.commit()
    params = {"experiment_id": experiment.id, "file_id": record.id, "stage": "raw"}
    node = SimpleNamespace(node_id="source", node_type="data.file_load", parameters=params)
    return node, path


async def test_canonical_source_identity_survives_disk_change(test_session, test_user, source):
    node, path = source
    original = path.read_bytes()
    async with frozen.freeze_workflow_sources(
        test_session, nodes=[node], actor_id=test_user.id, project_id=None
    ) as resolver:
        envelope = await resolver.resolve_experiment_file(**node.parameters)
        captured = Path(envelope.path)
        assert captured.name == path.name and captured.read_bytes() == original
        assert envelope.sha256 == hashlib.sha256(original).hexdigest()
        canonical = FileLoadNode("source", node.parameters)
        canonical.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=resolver))
        first = (await canonical.execute())["default"]
        path.write_text("1000,1001,1002\n90,80,70\n60,50,40\n")
        second = (await canonical.execute())["default"]
        # Node execution appends a fresh timestamped processing entry; compare
        # the canonical data/axis/target/source projection separately.
        assert first.scientific_projection(include_provenance=False) == second.scientific_projection(
            include_provenance=False
        )
        assert second.X.tolist() == [[1, 2, 3], [4, 5, 6]]
        with pytest.raises(ValueError, match="outside"):
            await resolver.resolve_experiment_file(
                experiment_id=node.parameters["experiment_id"], file_id=999, stage="raw"
            )
        with pytest.raises(ValueError, match="outside"):
            await resolver.resolve_nist_library_entry(library_id=1)
    assert not captured.exists()


async def test_exact_collection_does_not_expand_or_reread(test_session, test_user, source):
    node, path = source
    params = {
        "experiment_id": node.parameters["experiment_id"],
        "stage": "raw",
        "selected_file_ids": [node.parameters["file_id"]],
    }
    collection = SimpleNamespace(node_id="collection", node_type="data.collection_load", parameters=params)
    async with frozen.freeze_workflow_sources(
        test_session, nodes=[collection], actor_id=test_user.id, project_id=None
    ) as resolver:
        before = await resolver.resolve_experiment_collection(experiment_id=params["experiment_id"])
        path.unlink()
        extra = ExperimentFile(experiment_id=params["experiment_id"], file_path="raw/new.csv", stage="raw")
        test_session.add(extra)
        await test_session.commit()
        after = await resolver.resolve_experiment_collection(experiment_id=params["experiment_id"])
        assert after == before and len(after.files) == 1
        assert Path(after.files[0].path).exists()


async def test_capture_budget_and_access_refuse(test_session, test_user, source, monkeypatch):
    node, _ = source
    monkeypatch.setattr(frozen, "_MAX_BYTES", 4)
    with pytest.raises(ValueError, match="byte limit"):
        async with frozen.freeze_workflow_sources(test_session, nodes=[node], actor_id=test_user.id, project_id=None):
            pytest.fail("oversized source admitted")
    from spectra_sherpa.app.services.dataset_access import DatasetAccessError

    with pytest.raises(DatasetAccessError):
        async with frozen.freeze_workflow_sources(
            test_session, nodes=[node], actor_id=test_user.id + 999, project_id=None
        ):
            pytest.fail("foreign source admitted")


async def test_cancel_drains_owned_reader_before_return():
    import threading

    started, finish, ended = threading.Event(), threading.Event(), threading.Event()

    def reader():
        started.set()
        finish.wait(5)
        ended.set()

    task = asyncio.create_task(frozen._drained_read(reader))
    await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert ended.is_set()


async def test_prepared_sidecar_frozen_without_changing_parser_identity(test_session, test_user, source):
    from spectra_sherpa.app.services.prepared_data import save_prepared_data_overrides

    node, path = source
    save_prepared_data_overrides({"title": "Approved source"}, file_path=str(path))
    canonical = FileLoadNode("source", node.parameters)
    baseline = canonical._load_file(path, prepared_overrides={"title": "Approved source"})
    async with frozen.freeze_workflow_sources(
        test_session, nodes=[node], actor_id=test_user.id, project_id=None
    ) as resolver:
        envelope = await resolver.resolve_experiment_file(**node.parameters)
        save_prepared_data_overrides({"title": "Later source"}, file_path=str(path))
        captured = canonical._load_file(envelope.path, prepared_overrides=envelope.prepared_overrides)
        assert captured.scientific_digest == baseline.scientific_digest
        assert captured.title == "Approved source"


async def test_conflicting_collection_members_refused(test_session, test_user, source):
    node, path = source
    extra_path = path.with_name("other.csv")
    extra_path.write_bytes(path.read_bytes())
    extra = ExperimentFile(experiment_id=node.parameters["experiment_id"], file_path="raw/other.csv", stage="raw")
    test_session.add(extra)
    await test_session.commit()
    nodes = [
        SimpleNamespace(
            node_id=str(index),
            node_type="data.collection_load",
            parameters={
                "experiment_id": node.parameters["experiment_id"],
                "selected_file_ids": ids,
            },
        )
        for index, ids in enumerate(([node.parameters["file_id"]], [extra.id]))
    ]
    with pytest.raises(ValueError, match="Conflicting"):
        async with frozen.freeze_workflow_sources(test_session, nodes=nodes, actor_id=test_user.id, project_id=None):
            pytest.fail("ambiguous collection admitted")


async def test_collection_definition_and_view_do_not_reread(test_session, test_user, source, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from spectra_sherpa.app.models.dataset_view import DatasetView
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.services import dataset_source_resolver
    from spectra_sherpa.app.services.collection_definitions import collection_definition_path
    from spectra_sherpa.app.services.dataset_views import receipt_sha256

    node, _ = source
    project = Project(user_id=test_user.id, name="Captured selection")
    test_session.add(project)
    await test_session.flush()
    experiment = await test_session.get(Experiment, node.parameters["experiment_id"])
    experiment.project_id = project.id
    receipt = {"schema_version": "synthetic-resolver-receipt", "included_sample_ids": ["sample-a"]}
    digest = receipt_sha256(receipt)
    view = DatasetView(
        project_id=project.id,
        experiment_id=experiment.id,
        created_by_user_id=test_user.id,
        name="Selected",
        name_key="selected",
        selection=receipt,
        selection_sha256=digest,
    )
    test_session.add(view)
    await test_session.commit()
    monkeypatch.setattr(
        dataset_source_resolver, "async_session", async_sessionmaker(test_session.bind, expire_on_commit=False)
    )
    params = {
        "experiment_id": experiment.id,
        "selected_file_ids": [node.parameters["file_id"]],
        "dataset_view_id": view.id,
        "dataset_view_sha256": digest,
    }
    collection = SimpleNamespace(node_id="collection", node_type="data.collection_load", parameters=params)
    async with frozen.freeze_workflow_sources(
        test_session, nodes=[collection], actor_id=test_user.id, project_id=project.id
    ) as resolver:
        definition = collection_definition_path(experiment.id)
        definition.parent.mkdir(parents=True, exist_ok=True)
        definition.write_text("invalid replacement must not be reread")
        view.selection = {"changed": True}
        view.selection_sha256 = "0" * 64
        await test_session.commit()
        captured = await resolver.resolve_experiment_collection(experiment_id=experiment.id)
        assert captured.collection_definition_bytes is None
        value = await resolver.resolve_dataset_view(
            experiment_id=experiment.id, view_id=view.id, selection_sha256=digest
        )
        assert value["selection"] == receipt
        value["selection"]["included_sample_ids"].append("foreign")
        assert (
            await resolver.resolve_dataset_view(experiment_id=experiment.id, view_id=view.id, selection_sha256=digest)
        )["selection"] == receipt
        with pytest.raises(ValueError, match="outside"):
            await resolver.resolve_dataset_view(experiment_id=experiment.id, view_id=view.id, selection_sha256="0" * 64)


async def test_cancel_scope_drains_owned_reader():
    import threading

    import anyio

    started, finish, ended = threading.Event(), threading.Event(), threading.Event()

    def reader():
        started.set()
        finish.wait(5)
        ended.set()

    async def cancel_when_running(scope):
        await asyncio.to_thread(started.wait, 5)
        scope.cancel()
        await asyncio.sleep(0.01)
        assert not ended.is_set()
        finish.set()

    with anyio.CancelScope() as scope:
        cancel = asyncio.create_task(cancel_when_running(scope))
        await frozen._drained_read(reader)
    await cancel
    assert ended.is_set()
