"""Portable editable collection bindings retain the exact admitted file subset."""

import io
import json
import zipfile
from copy import deepcopy

import numpy as np
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from spectra_sherpa.app.api.v1.routes.projects import _remap_workflow_parameters


@pytest.mark.parametrize("selected", [["1034", "1032"], ["1033"], []])
def test_selected_file_remap_preserves_declared_subset_and_order(selected):
    source = {"experiment_id": 209, "selected_file_ids": selected, "source_manifest_sha256": "a" * 64}
    original = deepcopy(source)
    result = _remap_workflow_parameters(
        source, {}, {209: 2}, {1032: 5, 1033: 6, 1034: 7}, file_experiments={1032: 209, 1033: 209, 1034: 209}
    )
    assert result["experiment_id"] == 2
    assert result["selected_file_ids"] == [str({1032: 5, 1033: 6, 1034: 7}[int(value)]) for value in selected]
    assert result["source_manifest_sha256"] == source["source_manifest_sha256"]
    assert source == original


@pytest.mark.parametrize("selected", [["9999"], ["1033"], ["1032", "1032"], [True], [1.5], ["bad"], None])
def test_selected_file_remap_refuses_foreign_or_malformed_ids(selected):
    with pytest.raises(HTTPException) as refused:
        _remap_workflow_parameters(
            {"experiment_id": 209, "selected_file_ids": selected},
            {},
            {209: 2},
            {1032: 5, 1033: 6},
            file_experiments={1032: 209, 1033: 210},
        )
    assert refused.value.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", [[2, 0], [1]])
async def test_project_import_collection_node_executes_exact_subset_after_id_remap(
    selection, auth_client, test_session, test_engine, test_user, monkeypatch
):
    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.models.experiment_file import ExperimentFile
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.models.workflow_node import WorkflowNode
    from spectra_sherpa.app.services import dataset_source_resolver
    from spectra_sherpa.app.services.dag.node_base import node_registry
    from spectra_sherpa.app.services.dataset_source_resolver import ApplicationDatasetSourceResolver
    from spectra_sherpa.app.services.experiments import (
        ensure_experiment_dirs,
        experiment_dir,
        metadata_path_for,
        relative_to_data_dir,
        write_metadata,
    )
    from spectra_sherpa.app.services.model_application import load_project_dataset
    from spectra_sherpa.core.execution_runtime import ExecutionRuntime

    project = Project(user_id=test_user.id, name="Subset portability")
    test_session.add(project)
    await test_session.flush()
    experiment = Experiment(user_id=test_user.id, project_id=project.id, name="Three sources", metadata_path="")
    workflow = Workflow(user_id=test_user.id, project_id=project.id, name="Bound collection")
    test_session.add_all([experiment, workflow])
    await test_session.flush()
    ensure_experiment_dirs(experiment.id)
    meta = metadata_path_for(experiment.id)
    write_metadata(meta, {})
    experiment.metadata_path = relative_to_data_dir(meta)
    records = []
    for index, name in enumerate(("a", "b", "c")):
        path = experiment_dir(experiment.id) / f"raw/{name}/source.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"Wavenumber (cm-1),sample_{name}\n1000,{index+1}\n1001,{index+4}\n")
        record = ExperimentFile(
            experiment_id=experiment.id,
            file_path=f"raw/{name}/source.csv",
            file_type="csv",
            stage="raw",
            file_size_bytes=path.stat().st_size,
        )
        test_session.add(record)
        records.append(record)
    await test_session.commit()
    selected_ids = [records[index].id for index in selection]
    loaded = await load_project_dataset(
        test_session, user_id=test_user.id, experiment_id=experiment.id, stage="raw", file_ids=selected_ids
    )
    parameters = node_registry.create_node(
        "data.collection_load",
        "source",
        {
            "experiment_id": experiment.id,
            "selected_file_ids": [str(value) for value in selected_ids],
            "stage": "raw",
            "source_manifest_sha256": loaded.source_manifest_sha256,
            "collection_definition_sha256": loaded.collection_definition_sha256 or "",
            "scientific_collection_sha256": loaded.scientific_collection_sha256 or "",
        },
    )._resolve_params()
    test_session.add(
        WorkflowNode(
            workflow_id=workflow.id,
            node_id="source",
            node_type="data.collection_load",
            parameters=parameters,
            position_x=0,
            position_y=0,
        )
    )
    await test_session.commit()
    original_project_id = project.id
    exported = await auth_client.get(f"/api/v1/projects/{project.id}/export/sherpa")
    assert exported.status_code == 200, exported.text
    if selection == [2, 0]:
        from spectra_sherpa.app.services.sherpa_object import ArchiveMember, build_archive

        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            snapshot = json.loads(archive.read("project.json"))
            members = [
                ArchiveMember(name, archive.read(name))
                for name in archive.namelist()
                if name not in {"project.json", "sherpa-object.json"}
            ]
        for failure in ("foreign_file", "scientific_receipt"):
            changed = deepcopy(snapshot)
            bad = changed["workflows"][0]["nodes"][0]["parameters"]
            if failure == "foreign_file":
                bad["selected_file_ids"] = ["99999999"]
            else:
                bad["scientific_collection_sha256"] = "0" * 64
            rejected = await auth_client.post(
                "/api/v1/projects/import",
                files={
                    "file": (
                        "bad-subset.sherpa",
                        build_archive(project_payload=changed, members=members),
                        "application/zip",
                    )
                },
            )
            assert rejected.status_code == 400
            assert (
                "outside experiment custody" if failure == "foreign_file" else "cannot be restored exactly"
            ) in rejected.text
            for record in (test_user, project, experiment, workflow, *records):
                await test_session.refresh(record)
    imported_response = await auth_client.post(
        "/api/v1/projects/import", files={"file": ("subset.sherpa", io.BytesIO(exported.content), "application/zip")}
    )
    assert imported_response.status_code == 201, imported_response.text
    imported_id = imported_response.json()["id"]
    assert imported_id != original_project_id
    imported_workflow = await test_session.scalar(select(Workflow).where(Workflow.project_id == imported_id))
    imported_node = await test_session.scalar(
        select(WorkflowNode).where(WorkflowNode.workflow_id == imported_workflow.id)
    )
    imported_files = list(
        await test_session.scalars(select(ExperimentFile).join(Experiment).where(Experiment.project_id == imported_id))
    )
    mapped = {item.file_path: item.id for item in imported_files}
    expected_ids = [mapped[records[index].file_path] for index in selection]
    assert imported_node.parameters["selected_file_ids"] == [str(value) for value in expected_ids]
    assert set(expected_ids).isdisjoint(selected_ids)
    assert imported_node.parameters["source_manifest_sha256"] == loaded.source_manifest_sha256
    assert imported_node.parameters["scientific_collection_sha256"] == (loaded.scientific_collection_sha256 or "")
    # Exercise the same collection resolver and node used by a normal workflow Run.
    monkeypatch.setattr(
        dataset_source_resolver, "async_session", async_sessionmaker(test_engine, expire_on_commit=False)
    )
    node = node_registry.create_node("data.collection_load", "source", imported_node.parameters)
    node.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=ApplicationDatasetSourceResolver()))
    result = await node.execute()
    output = result.outputs if hasattr(result, "outputs") else result
    np.testing.assert_array_equal(output["default"].X, loaded.dataset.X)
    assert output["default"].sample_axis.labels == loaded.dataset.sample_axis.labels
