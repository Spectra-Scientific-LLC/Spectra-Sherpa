"""Route-level qualification for the unified Eigenvector DSO customer journey."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import h5py
import numpy as np
import pytest
from httpx import AsyncClient
from scipy.io import loadmat, savemat
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.dataset_registry import dataset_registry
from spectra_sherpa.io import ingest
from spectra_sherpa.io.formats.dso import scipy_struct_fields
from tests.test_native_matlab_dso import _dso_struct
from tests.test_native_matlab_v73_dso import _write_v73


async def _second_user(session: AsyncSession) -> User:
    user = User(username="dso-journey-other-owner")
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


def _dso_pair(tmp_path: Path) -> tuple[Path, Path]:
    dso = _dso_struct(np.arange(24, dtype=np.float64).reshape(2, 3, 4))
    v5 = tmp_path / "customer-dso-v5.mat"
    savemat(v5, {"calibration": dso}, do_compression=True)
    fields = scipy_struct_fields(loadmat(v5, squeeze_me=False, struct_as_record=True)["calibration"])
    v73 = _write_v73(tmp_path / "customer-dso-v73.mat", calibration=fields)
    with h5py.File(v73, "r+") as file:
        file["calibration"].attrs["MATLAB_class"] = np.bytes_("DataSet")
    return v5, v73


def _tamper_first_dso_member(archive_bytes: bytes) -> bytes:
    source = io.BytesIO(archive_bytes)
    output = io.BytesIO()
    with zipfile.ZipFile(source, "r") as original, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as rebuilt:
        changed = False
        for info in original.infolist():
            payload = original.read(info.filename)
            if not changed and info.filename.endswith(".mat") and "/raw/" in info.filename:
                payload = bytes([payload[0] ^ 1]) + payload[1:]
                changed = True
            rebuilt.writestr(info, payload)
    assert changed
    return output.getvalue()


@pytest.mark.anyio
async def test_unified_dso_workbench_save_restart_export_import_journey(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_engine,
    test_user: User,
    swap_user,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Both MATLAB storage families survive the complete owner-scoped journey."""

    import spectra_sherpa.app.db.session as db_session

    monkeypatch.setattr(
        db_session,
        "async_session",
        async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False),
    )
    v5, v73 = _dso_pair(tmp_path)
    admitted = [ingest(v5).assets[0].dataset, ingest(v73).assets[0].dataset]
    assert admitted[0].scientific_projection() == admitted[1].scientific_projection()
    assert admitted[0].scientific_digest == admitted[1].scientific_digest

    project_response = await auth_client.post(
        "/api/v1/projects",
        json={"name": "Unified DSO Journey", "technique": "NIR", "sample_type": "qualification"},
    )
    assert project_response.status_code == 201, project_response.text
    project_id = int(project_response.json()["id"])

    original_handles: list[str] = []
    source_manifests: dict[str, str] = {}
    for storage, path in (("v5", v5), ("v73", v73)):
        experiment_response = await auth_client.post(
            "/api/v1/experiments",
            json={
                "name": f"DSO {storage}",
                "metadata": {"qualification_storage": storage},
                "project_id": project_id,
            },
        )
        assert experiment_response.status_code == 201, experiment_response.text
        experiment_id = int(experiment_response.json()["id"])

        staged_response = await auth_client.post(
            "/api/v1/builder/upload/stage",
            files={"file": (path.name, path.read_bytes(), "application/octet-stream")},
        )
        assert staged_response.status_code == 200, staged_response.text
        staged = staged_response.json()
        assert staged["format_id"] == "matlab"
        assert [asset["asset_id"] for asset in staged["assets"]] == ["calibration"]

        preview_response = await auth_client.post(
            "/api/v1/builder/data-matrix",
            json={"kind": "staged", "staging_id": staged["staging_id"], "asset_id": "calibration"},
        )
        assert preview_response.status_code == 200, preview_response.text
        preview = preview_response.json()
        assert preview["shape"] == [2, 3, 4]
        assert preview["kind"] == "nd_dataset"
        assert preview["dimension_roles"] == ["sample", "inner", "feature"]
        assert preview["projection_required"] is True
        assert preview["matrix"] == []
        assert preview["dataset_preview"]["scientific_projection"] == admitted[0].scientific_projection(
            include_data=False,
            include_sample_table=False,
        )

        committed_response = await auth_client.post(
            "/api/v1/builder/upload/commit",
            json={
                "experiment_id": experiment_id,
                "stage": "raw",
                "files": [{"staging_id": staged["staging_id"]}],
            },
        )
        assert committed_response.status_code == 200, committed_response.text
        files_response = await auth_client.get(f"/api/v1/experiments/{experiment_id}/files")
        assert files_response.status_code == 200
        files = files_response.json()
        assert len(files) == 1

        asset_response = await auth_client.get(
            f"/api/v1/experiments/{experiment_id}/files/{files[0]['id']}/scientific-assets"
        )
        assert asset_response.status_code == 200, asset_response.text
        inventory = asset_response.json()
        assert inventory["format_id"] == "matlab"
        assert [asset["asset_id"] for asset in inventory["assets"]] == ["calibration"]
        assert inventory["assets"][0]["shape"] == [2, 3, 4]

        inspected_response = await auth_client.post(
            "/api/v1/builder/file-info",
            json={
                "experiment_id": experiment_id,
                "file_path": files[0]["file_path"],
                "asset_id": "calibration",
            },
        )
        assert inspected_response.status_code == 200, inspected_response.text
        inspected = inspected_response.json()
        assert inspected["shape"] == [2, 3, 4]
        assert inspected["manifest"]["scientific_digest"] == admitted[0].scientific_digest
        handle = str(inspected["dataset_id"])
        original_handles.append(handle)

        axes_response = await auth_client.get(f"/api/v1/datasets/{handle}/axes")
        assert axes_response.status_code == 200, axes_response.text
        axes = axes_response.json()
        assert [record["dimension"] for record in axes["axes"]] == [0, 1, 2]
        assert [item["name"] for item in axes["axes"][0]["axis"]["class_sets"]] == ["group", "sequence"]
        assert axes["axes"][0]["axis"]["include_mask"] == [True, False]
        assert axes["axes"][1]["axis"]["include_mask"] == [True, False, True]
        assert axes["axes"][2]["axis"]["include_mask"] == [True, False, True, False]

        collection_response = await auth_client.post(
            "/api/v1/builder/file-info",
            json={"experiment_id": experiment_id, "asset_id": "calibration"},
        )
        assert collection_response.status_code == 200, collection_response.text
        source_manifest = collection_response.json()["metadata"]["source_collection"]["manifest_digest"]
        source_manifests[storage] = source_manifest

        workflow_response = await auth_client.post(
            "/api/v1/workflows",
            json={
                "name": f"Load DSO {storage}",
                "project_id": project_id,
                "technique": "NIR",
                "nodes": [
                    {
                        "node_id": "source_1",
                        "node_type": "data.load_group",
                        "label": f"DSO {storage} calibration",
                        "parameters": {
                            "source_mode": "experiment_collection",
                            "experiment_id": experiment_id,
                            "stage": "raw",
                            "asset_id": "calibration",
                            "source_manifest_sha256": source_manifest,
                        },
                    }
                ],
                "edges": [],
            },
        )
        assert workflow_response.status_code == 201, workflow_response.text
        workflow_id = int(workflow_response.json()["id"])
        execution_response = await auth_client.post(f"/api/v1/workflows/{workflow_id}/execute", json={})
        assert execution_response.status_code == 200, execution_response.text
        source_result = execution_response.json()["results"]["source_1"]["default"]
        assert source_result["shape"] == [2, 3, 4]
        assert source_result["inner_axes"]["1"]["class_sets"][0]["name"] == "group"

    other_user = await _second_user(test_session)
    swap_user(other_user)
    assert (await auth_client.get(f"/api/v1/projects/{project_id}")).status_code == 404
    for handle in original_handles:
        assert (await auth_client.get(f"/api/v1/datasets/{handle}/axes")).status_code == 403
    swap_user(test_user)

    saved_response = await auth_client.post(
        f"/api/v1/projects/{project_id}/save",
        json={"change_description": "Unified v5/v7.3 DSO qualification"},
    )
    assert saved_response.status_code == 201, saved_response.text
    exported_response = await auth_client.get(
        f"/api/v1/projects/{project_id}/export/sherpa?version_id={saved_response.json()['id']}"
    )
    assert exported_response.status_code == 200, exported_response.text

    project_count = await test_session.scalar(select(func.count(Project.id)))
    tampered_response = await auth_client.post(
        "/api/v1/projects/import",
        files={
            "file": (
                "tampered-dso.sherpa",
                io.BytesIO(_tamper_first_dso_member(exported_response.content)),
                "application/zip",
            )
        },
    )
    assert tampered_response.status_code == 400
    assert await test_session.scalar(select(func.count(Project.id))) == project_count

    # The route deliberately rolls back the shared test session on archive
    # tampering. Re-admit the authenticated row before exercising the next
    # independent process boundary.
    await test_session.refresh(test_user)
    dataset_registry.clear()
    for handle in original_handles:
        assert (await auth_client.get(f"/api/v1/datasets/{handle}/axes")).status_code == 404

    imported_response = await auth_client.post(
        "/api/v1/projects/import",
        files={"file": ("unified-dso.sherpa", io.BytesIO(exported_response.content), "application/zip")},
    )
    assert imported_response.status_code == 201, imported_response.text
    imported = imported_response.json()
    assert len(imported["experiments"]) == 2
    assert len(imported["workflows"]) == 2

    imported_sample_axes: list[dict[str, object]] = []
    for experiment in sorted(imported["experiments"], key=lambda item: item["name"]):
        storage = "v5" if experiment["name"].endswith("v5") else "v73"
        inspection_response = await auth_client.post(
            "/api/v1/builder/file-info",
            json={"experiment_id": experiment["id"], "asset_id": "calibration"},
        )
        assert inspection_response.status_code == 200, inspection_response.text
        inspection = inspection_response.json()
        assert inspection["shape"] == [2, 3, 4]
        assert inspection["metadata"]["source_collection"]["manifest_digest"] == source_manifests[storage]
        imported_sample_axes.append(inspection["scientific_projection"]["axes"][0])

    assert imported_sample_axes[0] == imported_sample_axes[1]
    for workflow in imported["workflows"]:
        execution_response = await auth_client.post(f"/api/v1/workflows/{workflow['id']}/execute", json={})
        assert execution_response.status_code == 200, execution_response.text
        source_result = execution_response.json()["results"]["source_1"]["default"]
        assert source_result["shape"] == [2, 3, 4]
        assert source_result["version"] == "3.0"
