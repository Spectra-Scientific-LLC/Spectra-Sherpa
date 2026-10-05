from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.lib.sherpa_dataset import DomainContext
from spectra_sherpa.app.models.project import Project
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.collection_definitions import (
    collection_definition_path,
    read_collection_definition,
    remove_collection_definition,
    write_collection_definition,
)
from spectra_sherpa.app.services.experiments import experiment_dir

_FIXTURE = Path(__file__).parent / "fixtures" / "omnic" / "openspecy-polyethylene-reflectance.spa"
_SOURCE_SHA256 = "042c53feb30cb7328318b8c426203720da455be3f948f41ee5e39119b9d86288"


def _bytes_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _definition(file_names: list[str]) -> dict[str, object]:
    rows = []
    for index, file_name in enumerate(file_names, start=1):
        sample_id = f"sample-{index}"
        rows.append(
            {
                "file_name": file_name,
                "sha256": _SOURCE_SHA256,
                "asset_id": "spectrum",
                "source_row_index": 0,
                "sample_id": sample_id,
                "annotations": {
                    "sample_id": sample_id,
                    "specimen_id": f"specimen-{index}",
                    "block": index,
                    "operator_note": f"verified-{index}",
                },
            }
        )
    return {
        "schema_version": "spectrasherpa-collection-definition/1",
        "columns": ["sample_id", "specimen_id", "block", "operator_note"],
        "collection": {
            "dataset_id": "test-collection/1",
            "title": "Verified two-source collection",
            "units": "reflectance",
            "data_role": "X_spectra",
            "domain": DomainContext(
                technique="IR",
                expected_units="cm-1",
                data_quantity="Reflectance",
            ).model_dump(mode="json", exclude_none=False),
            "sample_axis": {"title": "Verified samples", "units": None, "values_policy": "omit"},
        },
        "rows": rows,
    }


def _lavender_distribution_archive(tmp_path: Path) -> Path:
    package_root = "lavender-essential-oil-v1"
    files = []
    rows = []
    payloads: dict[str, bytes] = {}
    archive_path = tmp_path / "lavender-essential-oil-v1.zip"
    for index in range(1, 34):
        name = f"lavender-{index:03d}.spa"
        content = f"qualified lavender source {index}\n".encode()
        payloads[f"data/{name}"] = content
        digest = _bytes_sha256(content)
        files.append(
            {
                "path": f"data/{name}",
                "size_bytes": len(content),
                "sha256": digest,
            }
        )
        sample_id = f"lavender-{index:03d}"
        rows.append(
            {
                "file_name": f"raw/{name}",
                "sha256": digest,
                "asset_id": "spectrum",
                "source_row_index": 0,
                "sample_id": sample_id,
                "annotations": {
                    "sample_id": sample_id,
                    "specimen_id": f"specimen-{((index - 1) % 11) + 1:02d}",
                    "block": ((index - 1) % 3) + 1,
                    "claimed_botanical_group": "Lavandula angustifolia",
                    "author_reported_authenticity_status": "authentic",
                },
            }
        )
    definition = {
        "schema_version": "spectrasherpa-collection-definition/1",
        "columns": [
            "sample_id",
            "specimen_id",
            "block",
            "claimed_botanical_group",
            "author_reported_authenticity_status",
        ],
        "collection": {
            "dataset_id": "avatar-essential-oils/1",
            "title": "Lavender Essential Oil FTIR Corpus v1",
            "units": "absorbance",
            "data_role": "X_spectra",
            "domain": DomainContext(
                technique="FTIR",
                expected_units="cm-1",
                data_quantity="Absorbance",
            ).model_dump(mode="json", exclude_none=False),
            "sample_axis": {"title": "Lavender samples", "units": None, "values_policy": "omit"},
        },
        "rows": rows,
    }
    manifest = {
        "schema_version": "spectrasherpa-avatar-essential-oils-distribution/2",
        "dataset_id": "avatar-essential-oils/1",
        "dataset_version": 1,
        "dataset_title": "Lavender Essential Oil FTIR Corpus v1",
        "counts": {"files": 33, "specimens": 11, "blocks": 3},
        "files": files,
    }

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr(f"{package_root}/manifest.json", json.dumps(manifest))
        archive.writestr(f"{package_root}/collection-definition.json", json.dumps(definition))
        for path, content in payloads.items():
            archive.writestr(f"{package_root}/{path}", content)
    return archive_path


async def _project_experiment_with_two_sources(
    auth_client: AsyncClient,
) -> tuple[int, int, list[dict[str, object]]]:
    from spectra_sherpa.app.services.prepared_data import sidecar_path

    project = (await auth_client.post("/api/v1/projects", json={"name": "Collection UI project"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Collection UI dataset", "metadata": {}, "project_id": project["id"]},
        )
    ).json()
    remove_collection_definition(int(experiment["id"]))
    source = _FIXTURE.read_bytes()
    for name in ("member-one.spa", "member-two.spa"):
        response = await auth_client.post(
            f"/api/v1/experiments/{experiment['id']}/files",
            data={"stage": "raw"},
            files={"file": (name, source, "application/octet-stream")},
        )
        assert response.status_code == 201
    files = (await auth_client.get(f"/api/v1/experiments/{experiment['id']}/files")).json()
    for file_record in files:
        source = experiment_dir(int(experiment["id"])) / str(file_record["file_path"])
        sidecar_path(file_path=str(source), source=None, name=None).unlink(missing_ok=True)
    return int(project["id"]), int(experiment["id"]), files


async def _experiment_with_two_sources(auth_client: AsyncClient) -> tuple[int, list[dict[str, object]]]:
    _, experiment_id, files = await _project_experiment_with_two_sources(auth_client)
    return experiment_id, files


def _definition_upload(payload: dict[str, object]) -> dict[str, tuple[str, bytes, str]]:
    return {
        "file": (
            "collection-definition.json",
            (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(),
            "application/json",
        )
    }


@pytest.mark.anyio
async def test_builtin_lavender_reference_import_materializes_mounted_archive(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive_path = _lavender_distribution_archive(tmp_path)
    monkeypatch.setenv("TRIAL_AVATAR_ARCHIVE_PATH", str(archive_path))
    project = (await auth_client.post("/api/v1/projects", json={"name": "Lavender project"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={
                "name": "Lavender Essential Oil FTIR Corpus v1",
                "metadata": {"source_kind": "builtin_reference"},
                "project_id": project["id"],
            },
        )
    ).json()

    response = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/import-reference",
        json={"datasets": [{"source": "builtin", "name": "lavender-essential-oil-v1"}]},
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["imported"] == 33
    assert payload["experiment_id"] == experiment["id"]
    assert len(payload["files"]) == 33
    assert payload["files"][0]["file_path"] == "raw/lavender-001.spa"
    assert payload["files"][-1]["file_path"] == "raw/lavender-033.spa"

    definition = collection_definition_path(int(experiment["id"]))
    assert definition.exists()
    current = read_collection_definition(int(experiment["id"]))
    assert current is not None
    assert current.payload["collection"]["dataset_id"] == "avatar-essential-oils/1"
    assert len(current.payload["rows"]) == 33


@pytest.mark.anyio
async def test_demo_builtin_lavender_reference_import_bypasses_generic_reference_block(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from spectra_sherpa.app.contracts.demo_policy import (
        DemoPolicy,
        set_demo_policy_provider,
        set_trial_reference_grant_provider,
    )
    from spectra_sherpa.app.core.config import app_config

    archive_path = _lavender_distribution_archive(tmp_path)
    monkeypatch.setenv("TRIAL_AVATAR_ARCHIVE_PATH", str(archive_path))
    monkeypatch.setattr(app_config, "site_profile", "demo")
    set_demo_policy_provider(lambda: DemoPolicy(disabled_capabilities=frozenset({"reference_data_import"})))
    grant_calls: list[dict[str, object]] = []

    async def _grant_provider(**kwargs):
        grant_calls.append(kwargs)
        return object()

    set_trial_reference_grant_provider(_grant_provider)
    try:
        project = (await auth_client.post("/api/v1/projects", json={"name": "Lavender project"})).json()
        experiment = (
            await auth_client.post(
                "/api/v1/experiments",
                json={
                    "name": "Lavender Essential Oil FTIR Corpus v1",
                    "metadata": {"source_kind": "builtin_reference"},
                    "project_id": project["id"],
                },
            )
        ).json()

        response = await auth_client.post(
            f"/api/v1/experiments/{experiment['id']}/import-reference",
            json={"datasets": [{"source": "builtin", "name": "lavender-essential-oil-v1"}]},
        )
    finally:
        set_trial_reference_grant_provider(None)
        set_demo_policy_provider(lambda: DemoPolicy())

    assert response.status_code == 201, response.text
    assert response.json()["imported"] == 33
    assert grant_calls
    assert grant_calls[0]["dataset_key"] == "avatar-lavender-essential-oils-v1"
    assert grant_calls[0]["project_id"] == project["id"]
    assert grant_calls[0]["experiment_id"] == experiment["id"]


@pytest.mark.anyio
async def test_demo_sklearn_import_persists_target_contract_and_requests_catalog_grant(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spectra_sherpa.app.contracts.demo_policy import (
        DemoPolicy,
        set_demo_policy_provider,
        set_trial_reference_grant_provider,
    )
    from spectra_sherpa.app.core.config import app_config
    from spectra_sherpa.app.services.prepared_data import load_prepared_data_overrides_strict

    monkeypatch.setattr(app_config, "site_profile", "demo")
    set_demo_policy_provider(lambda: DemoPolicy(disabled_capabilities=frozenset({"reference_data_import"})))
    grant_calls: list[dict[str, object]] = []

    async def _grant_provider(**kwargs):
        grant_calls.append(kwargs)
        return SimpleNamespace(experiment_id=kwargs["experiment_id"], file_id=kwargs["file_id"])

    set_trial_reference_grant_provider(_grant_provider)
    try:
        project = (await auth_client.post("/api/v1/projects", json={"name": "Iris PCA"})).json()
        experiment = (
            await auth_client.post(
                "/api/v1/experiments",
                json={"name": "Iris", "metadata": {}, "project_id": project["id"]},
            )
        ).json()
        response = await auth_client.post(
            f"/api/v1/experiments/{experiment['id']}/import-reference",
            json={"datasets": [{"source": "sklearn", "name": "iris"}]},
        )
    finally:
        set_trial_reference_grant_provider(None)
        set_demo_policy_provider(lambda: DemoPolicy())

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["imported"] == 1
    assert payload["initial_file_ids"] == [payload["files"][0]["id"]]
    prepared = load_prepared_data_overrides_strict(
        file_path=str(experiment_dir(int(experiment["id"])) / payload["files"][0]["file_path"])
    )
    assert prepared.data_role == "X_features"
    assert prepared.target_column == "target"
    assert prepared.target_type == "categorical"
    assert grant_calls[0]["dataset_key"] is None
    assert grant_calls[0]["reference_source"] == "sklearn"
    assert grant_calls[0]["reference_name"] == "iris"
    assert grant_calls[0]["file_id"] == payload["files"][0]["id"]


@pytest.mark.anyio
async def test_local_sklearn_import_preserves_target_contract_for_dataset_readiness(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Local OSS imports must retain built-in class labels for My Dataset."""

    from spectra_sherpa.app.core.config import app_config
    from spectra_sherpa.app.services.prepared_data import load_prepared_data_overrides_strict

    monkeypatch.setattr(app_config, "site_profile", "local")
    project = (await auth_client.post("/api/v1/projects", json={"name": "Wine target handoff"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Wine", "metadata": {}, "project_id": project["id"]},
        )
    ).json()

    response = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/import-reference",
        json={"datasets": [{"source": "sklearn", "name": "wine"}]},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    file_record = payload["files"][0]
    prepared = load_prepared_data_overrides_strict(
        file_path=str(experiment_dir(int(experiment["id"])) / file_record["file_path"])
    )
    assert prepared.data_role == "X_features"
    assert prepared.target_column == "target"
    assert prepared.target_type == "categorical"

    available = await auth_client.get(f"/api/v1/datasets/available?project_id={project['id']}")
    assert available.status_code == 200, available.text
    dataset = available.json()["experiments"][0]
    assert dataset["target_names"] == ["target"]
    assert dataset["target_types"] == {"target": "categorical"}
    assert dataset["selected_target"] == "target"


@pytest.mark.anyio
async def test_demo_builtin_lavender_reimport_returns_existing_durable_dataset(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from spectra_sherpa.app.contracts.demo_policy import (
        DemoPolicy,
        set_demo_policy_provider,
        set_trial_reference_grant_provider,
    )
    from spectra_sherpa.app.core.config import app_config

    archive_path = _lavender_distribution_archive(tmp_path)
    monkeypatch.setenv("TRIAL_AVATAR_ARCHIVE_PATH", str(archive_path))
    monkeypatch.setattr(app_config, "site_profile", "demo")
    set_demo_policy_provider(lambda: DemoPolicy(disabled_capabilities=frozenset({"reference_data_import"})))
    authoritative_experiment_id: int | None = None

    async def _grant_provider(**kwargs):
        nonlocal authoritative_experiment_id
        if authoritative_experiment_id is None:
            authoritative_experiment_id = int(kwargs["experiment_id"])
        return SimpleNamespace(experiment_id=authoritative_experiment_id)

    set_trial_reference_grant_provider(_grant_provider)
    try:
        project = (await auth_client.post("/api/v1/projects", json={"name": "Lavender project"})).json()
        first = (
            await auth_client.post(
                "/api/v1/experiments",
                json={"name": "Lavender", "metadata": {}, "project_id": project["id"]},
            )
        ).json()
        first_response = await auth_client.post(
            f"/api/v1/experiments/{first['id']}/import-reference",
            json={"datasets": [{"source": "builtin", "name": "lavender-essential-oil-v1"}]},
        )
        duplicate = (
            await auth_client.post(
                "/api/v1/experiments",
                json={"name": "Lavender duplicate", "metadata": {}, "project_id": project["id"]},
            )
        ).json()
        duplicate_response = await auth_client.post(
            f"/api/v1/experiments/{duplicate['id']}/import-reference",
            json={"datasets": [{"source": "builtin", "name": "lavender-essential-oil-v1"}]},
        )
    finally:
        set_trial_reference_grant_provider(None)
        set_demo_policy_provider(lambda: DemoPolicy())

    assert first_response.status_code == 201, first_response.text
    assert duplicate_response.status_code == 201, duplicate_response.text
    payload = duplicate_response.json()
    assert payload["imported"] == 0
    assert payload["reused_existing"] is True
    assert payload["experiment_id"] == first["id"]
    assert len(payload["files"]) == 33
    assert not collection_definition_path(int(duplicate["id"])).exists()


@pytest.mark.anyio
async def test_builtin_lavender_reference_requires_an_empty_experiment(
    auth_client: AsyncClient,
) -> None:
    project = (await auth_client.post("/api/v1/projects", json={"name": "Occupied project"})).json()
    experiment = (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Occupied dataset", "metadata": {}, "project_id": project["id"]},
        )
    ).json()
    source = _FIXTURE.read_bytes()
    uploaded = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/files",
        data={"stage": "raw"},
        files={"file": ("existing.spa", source, "application/octet-stream")},
    )
    assert uploaded.status_code == 201

    response = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/import-reference",
        json={"datasets": [{"source": "builtin", "name": "lavender-essential-oil-v1"}]},
    )

    assert response.status_code == 409
    assert "empty My Dataset" in response.json()["detail"]
    files = (await auth_client.get(f"/api/v1/experiments/{experiment['id']}/files")).json()
    assert [item["file_path"] for item in files] == ["raw/existing.spa"]


@pytest.mark.anyio
async def test_collection_definition_preview_attach_receipt_stale_and_remove(auth_client: AsyncClient) -> None:
    experiment_id, files = await _experiment_with_two_sources(auth_client)
    definition = _definition([str(file["file_path"]) for file in files])

    absent = await auth_client.get(f"/api/v1/experiments/{experiment_id}/collection-definition")
    assert absent.status_code == 200
    assert absent.json()["status"] == "absent"

    preview = await auth_client.post(
        f"/api/v1/experiments/{experiment_id}/collection-definition/preview",
        files=_definition_upload(definition),
    )
    assert preview.status_code == 200
    preview_payload = preview.json()
    assert preview_payload["status"] == "preview"
    assert preview_payload["file_count"] == 2
    assert preview_payload["row_count"] == 2
    assert preview_payload["column_count"] == 4
    assert preview_payload["shape"] == [2, 1738]
    assert preview_payload["dataset_id"] == "test-collection/1"
    assert preview_payload["target_present"] is False
    assert preview_payload["sample_classes_present"] is False
    assert preview_payload["source_manifest_sha256"]
    assert preview_payload["scientific_collection_sha256"]
    assert not collection_definition_path(experiment_id).exists()

    attached = await auth_client.put(
        f"/api/v1/experiments/{experiment_id}/collection-definition",
        files=_definition_upload(definition),
    )
    assert attached.status_code == 200
    attached_payload = attached.json()
    assert attached_payload["status"] == "attached"
    assert attached_payload["definition_sha256"] == preview_payload["definition_sha256"]
    assert attached_payload["scientific_collection_sha256"] == preview_payload["scientific_collection_sha256"]
    if os.name != "nt":
        assert collection_definition_path(experiment_id).stat().st_mode & 0o777 == 0o600

    current = await auth_client.get(f"/api/v1/experiments/{experiment_id}/collection-definition")
    assert current.status_code == 200
    assert current.json() == attached_payload | {
        "message": "The definition is attached and matches the current scientific collection."
    }

    inspected = await auth_client.post("/api/v1/builder/file-info", json={"experiment_id": experiment_id})
    assert inspected.status_code == 200
    body = inspected.json()
    assert body["dataset_id"] == "test-collection/1"
    assert body["y_axis"]["labels"] == ["sample-1", "sample-2"]
    assert body["y_axis"]["sample_table"]["specimen_id"] == ["specimen-1", "specimen-2"]

    deleted = await auth_client.delete(f"/api/v1/experiments/{experiment_id}/files/{files[1]['id']}")
    assert deleted.status_code == 200
    stale = await auth_client.get(f"/api/v1/experiments/{experiment_id}/collection-definition")
    assert stale.status_code == 200
    assert stale.json()["status"] == "stale"
    assert stale.json()["definition_sha256"] == attached_payload["definition_sha256"]
    assert stale.json()["scientific_collection_sha256"] is None

    refused = await auth_client.post("/api/v1/builder/file-info", json={"experiment_id": experiment_id})
    assert refused.status_code == 400

    removed = await auth_client.delete(f"/api/v1/experiments/{experiment_id}/collection-definition")
    assert removed.status_code == 200
    assert removed.json()["status"] == "absent"
    assert not collection_definition_path(experiment_id).exists()


@pytest.mark.anyio
async def test_collection_definition_replacement_failure_preserves_attached_bytes(auth_client: AsyncClient) -> None:
    experiment_id, files = await _experiment_with_two_sources(auth_client)
    definition = _definition([str(file["file_path"]) for file in files])
    attached = await auth_client.put(
        f"/api/v1/experiments/{experiment_id}/collection-definition",
        files=_definition_upload(definition),
    )
    assert attached.status_code == 200
    path = collection_definition_path(experiment_id)
    before = path.read_bytes()

    wrong = deepcopy(definition)
    wrong["rows"][0]["sha256"] = "0" * 64  # type: ignore[index]
    response = await auth_client.put(
        f"/api/v1/experiments/{experiment_id}/collection-definition",
        files=_definition_upload(wrong),
    )
    assert response.status_code == 422
    assert path.read_bytes() == before

    current = await auth_client.get(f"/api/v1/experiments/{experiment_id}/collection-definition")
    assert current.status_code == 200
    assert current.json()["status"] == "attached"
    assert current.json()["definition_sha256"] == attached.json()["definition_sha256"]


@pytest.mark.anyio
async def test_collection_definition_endpoints_are_owner_scoped(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    test_user: User,
    swap_user,
) -> None:
    experiment_id, files = await _experiment_with_two_sources(auth_client)
    definition = _definition([str(file["file_path"]) for file in files])
    other_user = User(username="other-collection-owner")
    test_session.add(other_user)
    await test_session.commit()
    await test_session.refresh(other_user)
    swap_user(other_user)
    for method, suffix, kwargs in (
        (auth_client.get, "", {}),
        (auth_client.post, "/preview", {"files": _definition_upload(definition)}),
        (auth_client.put, "", {"files": _definition_upload(definition)}),
        (auth_client.delete, "", {}),
    ):
        response = await method(f"/api/v1/experiments/{experiment_id}/collection-definition{suffix}", **kwargs)
        assert response.status_code == 404
    swap_user(test_user)


@pytest.mark.anyio
async def test_collection_definition_upload_refuses_over_limit(auth_client: AsyncClient) -> None:
    experiment_id, _ = await _experiment_with_two_sources(auth_client)
    oversized = b"{" + b" " * (4 * 1024 * 1024) + b"}"
    response = await auth_client.post(
        f"/api/v1/experiments/{experiment_id}/collection-definition/preview",
        files={"file": ("too-large.json", oversized, "application/json")},
    )
    assert response.status_code == 422
    assert "4 MiB" in response.json()["detail"]


@pytest.mark.anyio
async def test_collection_definition_attach_never_claims_current_after_source_race(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_id, files = await _experiment_with_two_sources(auth_client)
    definition = _definition([str(file["file_path"]) for file in files])

    from spectra_sherpa.app.api.v1.routes import experiments as route_module

    real_write = route_module.write_collection_definition
    changed_source = experiment_dir(experiment_id) / str(files[1]["file_path"])

    def _write_then_change(*args, **kwargs):
        result = real_write(*args, **kwargs)
        changed_source.unlink()
        return result

    monkeypatch.setattr(route_module, "write_collection_definition", _write_then_change)
    response = await auth_client.put(
        f"/api/v1/experiments/{experiment_id}/collection-definition",
        files=_definition_upload(definition),
    )

    assert response.status_code == 200
    receipt = response.json()
    assert receipt["status"] == "stale"
    assert receipt["scientific_collection_sha256"] is None
    assert "changed during verification" in receipt["message"]
    assert collection_definition_path(experiment_id).exists()


@pytest.mark.anyio
async def test_collection_definition_attach_refuses_concurrent_remove(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_id, files = await _experiment_with_two_sources(auth_client)
    definition = _definition([str(file["file_path"]) for file in files])

    from spectra_sherpa.app.api.v1.routes import experiments as route_module

    real_write = route_module.write_collection_definition

    def _write_then_remove(*args, **kwargs):
        result = real_write(*args, **kwargs)
        remove_collection_definition(experiment_id)
        return result

    monkeypatch.setattr(route_module, "write_collection_definition", _write_then_remove)
    response = await auth_client.put(
        f"/api/v1/experiments/{experiment_id}/collection-definition",
        files=_definition_upload(definition),
    )

    assert response.status_code == 409
    assert "changed during verification" in response.json()["detail"]
    assert not collection_definition_path(experiment_id).exists()


@pytest.mark.anyio
async def test_collection_definition_attach_refuses_concurrent_replacement(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_id, files = await _experiment_with_two_sources(auth_client)
    definition = _definition([str(file["file_path"]) for file in files])
    replacement = deepcopy(definition)
    replacement["collection"]["title"] = "Concurrent replacement"  # type: ignore[index]

    from spectra_sherpa.app.api.v1.routes import experiments as route_module

    real_write = route_module.write_collection_definition

    def _write_then_replace(*args, **kwargs):
        result = real_write(*args, **kwargs)
        real_write(experiment_id, replacement)
        return result

    monkeypatch.setattr(route_module, "write_collection_definition", _write_then_replace)
    response = await auth_client.put(
        f"/api/v1/experiments/{experiment_id}/collection-definition",
        files=_definition_upload(definition),
    )

    assert response.status_code == 409
    current = await auth_client.get(f"/api/v1/experiments/{experiment_id}/collection-definition")
    assert current.status_code == 200
    assert current.json()["status"] == "attached"
    assert current.json()["title"] == "Concurrent replacement"


@pytest.mark.anyio
async def test_collection_definition_get_refuses_mixed_revision_receipt(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_id, files = await _experiment_with_two_sources(auth_client)
    definition = _definition([str(file["file_path"]) for file in files])
    attached = await auth_client.put(
        f"/api/v1/experiments/{experiment_id}/collection-definition",
        files=_definition_upload(definition),
    )
    assert attached.status_code == 200
    replacement = deepcopy(definition)
    replacement["collection"]["title"] = "Replacement during GET"  # type: ignore[index]

    from spectra_sherpa.app.api.v1.routes import experiments as route_module

    real_load = route_module.load_project_dataset
    replaced = False

    async def _replace_then_load(*args, **kwargs):
        nonlocal replaced
        if not replaced:
            replaced = True
            route_module.write_collection_definition(experiment_id, replacement)
        return await real_load(*args, **kwargs)

    monkeypatch.setattr(route_module, "load_project_dataset", _replace_then_load)
    response = await auth_client.get(f"/api/v1/experiments/{experiment_id}/collection-definition")

    assert response.status_code == 409
    assert "changed during verification" in response.json()["detail"]


@pytest.mark.anyio
async def test_saved_project_roundtrip_restores_exact_collection_definition_and_science(
    auth_client: AsyncClient,
) -> None:
    project_id, experiment_id, files = await _project_experiment_with_two_sources(auth_client)
    definition = _definition([str(file["file_path"]) for file in files])
    attached = await auth_client.put(
        f"/api/v1/experiments/{experiment_id}/collection-definition",
        files=_definition_upload(definition),
    )
    assert attached.status_code == 200, attached.text
    receipt = attached.json()

    saved = await auth_client.post(
        f"/api/v1/projects/{project_id}/save",
        json={"change_description": "Exact collection definition"},
    )
    assert saved.status_code == 201, saved.text
    exported = await auth_client.get(f"/api/v1/projects/{project_id}/export/sherpa?version_id={saved.json()['id']}")
    assert exported.status_code == 200, exported.text

    with zipfile.ZipFile(io.BytesIO(exported.content), "r") as archive:
        project_payload = json.loads(archive.read("project.json"))
        assert project_payload["archive_format"]["version"] == "0.5"
        archived_experiment = project_payload["experiments"][0]
        definition_member = archived_experiment["collection_definition_archive_member"]
        assert definition_member == f"data/experiments/{experiment_id}/collection-definition.json"
        assert archive.read(definition_member) == collection_definition_path(experiment_id).read_bytes()
        assert archived_experiment["collection_definition"] == definition
        assert archived_experiment["collection_definition_sha256"] == receipt["definition_sha256"]
        assert archived_experiment["collection_source_manifest_sha256"] == receipt["source_manifest_sha256"]
        assert archived_experiment["scientific_collection_sha256"] == receipt["scientific_collection_sha256"]
        assert archived_experiment["storage_snapshot_schema_version"] == ("spectrasherpa-project-storage-snapshot/2")

    imported = await auth_client.post(
        "/api/v1/projects/import",
        files={"file": ("collection-roundtrip.sherpa", io.BytesIO(exported.content), "application/zip")},
    )
    assert imported.status_code == 201, imported.text
    imported_experiment_id = int(imported.json()["experiments"][0]["id"])
    assert imported_experiment_id != experiment_id

    restored = await auth_client.get(f"/api/v1/experiments/{imported_experiment_id}/collection-definition")
    assert restored.status_code == 200, restored.text
    restored_receipt = restored.json()
    assert restored_receipt["status"] == "attached"
    assert restored_receipt["definition_sha256"] == receipt["definition_sha256"]
    assert restored_receipt["source_manifest_sha256"] == receipt["source_manifest_sha256"]
    assert restored_receipt["scientific_collection_sha256"] == receipt["scientific_collection_sha256"]

    inspected = await auth_client.post(
        "/api/v1/builder/file-info",
        json={"experiment_id": imported_experiment_id},
    )
    assert inspected.status_code == 200, inspected.text
    body = inspected.json()
    assert body["dataset_id"] == "test-collection/1"
    assert body["shape"] == [2, 1738]
    assert body["y_axis"]["labels"] == ["sample-1", "sample-2"]
    assert body["y_axis"]["sample_table"] == {
        "sample_id": ["sample-1", "sample-2"],
        "specimen_id": ["specimen-1", "specimen-2"],
        "block": [1, 2],
        "operator_note": ["verified-1", "verified-2"],
    }
    assert (
        body["metadata"]["source_collection"]["scientific_collection_sha256"] == receipt["scientific_collection_sha256"]
    )

    imported_versions = await auth_client.get(f"/api/v1/projects/{imported.json()['id']}/versions")
    assert imported_versions.status_code == 200
    imported_version_id = imported_versions.json()["versions"][0]["id"]
    reexported = await auth_client.get(
        f"/api/v1/projects/{imported.json()['id']}/export/sherpa?version_id={imported_version_id}"
    )
    assert reexported.status_code == 200, reexported.text
    with zipfile.ZipFile(io.BytesIO(reexported.content), "r") as archive:
        reexported_payload = json.loads(archive.read("project.json"))
        reexported_experiment = reexported_payload["experiments"][0]
        assert reexported_experiment["id"] == imported_experiment_id
        assert reexported_experiment["collection_definition_sha256"] == receipt["definition_sha256"]
        assert reexported_experiment["scientific_collection_sha256"] == receipt["scientific_collection_sha256"]
        assert reexported_experiment["collection_definition_archive_member"] == (
            f"data/experiments/{imported_experiment_id}/collection-definition.json"
        )


@pytest.mark.anyio
async def test_saved_project_export_refuses_source_prepared_or_definition_drift(
    auth_client: AsyncClient,
) -> None:
    from spectra_sherpa.app.core.config import settings
    from spectra_sherpa.app.services.prepared_data import (
        PreparedDataOverrides,
        save_prepared_data_overrides,
    )

    project_id, experiment_id, files = await _project_experiment_with_two_sources(auth_client)
    definition = _definition([str(file["file_path"]) for file in files])
    attached = await auth_client.put(
        f"/api/v1/experiments/{experiment_id}/collection-definition",
        files=_definition_upload(definition),
    )
    assert attached.status_code == 200, attached.text
    source_path = experiment_dir(experiment_id) / str(files[0]["file_path"])
    source_bytes = source_path.read_bytes()
    source_path.write_bytes(source_bytes + b"changed-before-save")
    stale_save = await auth_client.post(
        f"/api/v1/projects/{project_id}/save",
        json={"change_description": "Must refuse stale definition"},
    )
    assert stale_save.status_code == 409
    assert "Collection definition does not match" in stale_save.json()["detail"]
    source_path.write_bytes(source_bytes)
    saved = await auth_client.post(
        f"/api/v1/projects/{project_id}/save",
        json={"change_description": "Bound storage"},
    )
    assert saved.status_code == 201, saved.text
    export_url = f"/api/v1/projects/{project_id}/export/sherpa?version_id={saved.json()['id']}"

    source_path.write_bytes(source_bytes + b"changed")
    changed_source = await auth_client.get(export_url)
    assert changed_source.status_code == 409
    assert "source bytes changed" in changed_source.json()["detail"]
    source_path.write_bytes(source_bytes)

    backup_path = source_path.with_name(f"{source_path.name}.backup")
    source_path.rename(backup_path)
    source_path.symlink_to(backup_path.name)
    linked_source = await auth_client.get(export_url)
    assert linked_source.status_code == 409
    assert "source file changed" in linked_source.json()["detail"]
    source_path.unlink()
    backup_path.rename(source_path)

    with source_path.open("wb") as oversized_file:
        oversized_file.truncate((settings.max_file_size_mb * 1024 * 1024) + 1)
    oversized_source = await auth_client.get(export_url)
    assert oversized_source.status_code == 409
    assert "file-size limit" in oversized_source.json()["detail"]
    source_path.write_bytes(source_bytes)

    save_prepared_data_overrides(
        PreparedDataOverrides(title="Changed after save"),
        file_path=str(source_path),
    )
    changed_prepared = await auth_client.get(export_url)
    assert changed_prepared.status_code == 409
    assert "collection source identity is inconsistent" in changed_prepared.json()["detail"]
    save_prepared_data_overrides(PreparedDataOverrides(), file_path=str(source_path))

    replacement = deepcopy(definition)
    replacement["collection"]["title"] = "Changed after save"  # type: ignore[index]
    write_collection_definition(experiment_id, replacement)
    changed_definition = await auth_client.get(export_url)
    assert changed_definition.status_code == 409
    assert "collection definition changed" in changed_definition.json()["detail"]
    write_collection_definition(experiment_id, definition)

    remove_collection_definition(experiment_id)
    removed_definition = await auth_client.get(export_url)
    assert removed_definition.status_code == 409
    assert "collection definition changed" in removed_definition.json()["detail"]
    write_collection_definition(experiment_id, definition)

    exact = await auth_client.get(export_url)
    assert exact.status_code == 200, exact.text


@pytest.mark.anyio
async def test_project_save_refuses_prepared_sidecar_race_and_unsafe_sidecars(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spectra_sherpa.app.api.v1.routes import projects as project_routes
    from spectra_sherpa.app.services.prepared_data import (
        PREPARED_DATA_SIDECAR_MAX_BYTES,
        PreparedDataOverrides,
        save_prepared_data_overrides,
        sidecar_path,
    )

    project_id, experiment_id, files = await _project_experiment_with_two_sources(auth_client)
    definition = _definition([str(file["file_path"]) for file in files])
    attached = await auth_client.put(
        f"/api/v1/experiments/{experiment_id}/collection-definition",
        files=_definition_upload(definition),
    )
    assert attached.status_code == 200, attached.text
    source_path = experiment_dir(experiment_id) / str(files[0]["file_path"])
    prepared_path = sidecar_path(file_path=str(source_path), source=None, name=None)
    prepared_path.parent.mkdir(parents=True, exist_ok=True)

    prepared_path.write_bytes(b"{not-json")
    invalid = await auth_client.post(
        f"/api/v1/projects/{project_id}/save",
        json={"change_description": "Invalid sidecar"},
    )
    assert invalid.status_code == 409
    assert "sidecar" in invalid.json()["detail"]
    prepared_path.unlink()

    target = prepared_path.with_name(f"{prepared_path.name}.target")
    target.write_text("{}\n")
    prepared_path.symlink_to(target.name)
    linked = await auth_client.post(
        f"/api/v1/projects/{project_id}/save",
        json={"change_description": "Linked sidecar"},
    )
    assert linked.status_code == 409
    assert "sidecar" in linked.json()["detail"]
    prepared_path.unlink()
    target.unlink()

    with prepared_path.open("wb") as oversized:
        oversized.truncate(PREPARED_DATA_SIDECAR_MAX_BYTES + 1)
    too_large = await auth_client.post(
        f"/api/v1/projects/{project_id}/save",
        json={"change_description": "Oversized sidecar"},
    )
    assert too_large.status_code == 409
    assert "sidecar" in too_large.json()["detail"]
    prepared_path.unlink()

    real_bind = project_routes._bind_experiment_storage_snapshot
    raced = False

    def _bind_then_change(*args, **kwargs):
        nonlocal raced
        bound = real_bind(*args, **kwargs)
        if not raced:
            raced = True
            save_prepared_data_overrides(
                PreparedDataOverrides(title="Changed between capture and scientific load"),
                file_path=str(source_path),
            )
        return bound

    monkeypatch.setattr(project_routes, "_bind_experiment_storage_snapshot", _bind_then_change)
    changed_during_save = await auth_client.post(
        f"/api/v1/projects/{project_id}/save",
        json={"change_description": "Prepared-data race"},
    )
    assert changed_during_save.status_code == 409
    assert "while the snapshot was being created" in changed_during_save.json()["detail"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "payload",
    [
        {"unknown_science": 42},
        {"is_time_series": "false"},
        {"title": {"nested": True}},
        {"title": "x" * 4097},
    ],
)
async def test_project_save_refuses_noncanonical_prepared_sidecar_before_scientific_load(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
) -> None:
    from spectra_sherpa.app.api.v1.routes import projects as project_routes
    from spectra_sherpa.app.services.prepared_data import sidecar_path

    project_id, experiment_id, files = await _project_experiment_with_two_sources(auth_client)
    definition = _definition([str(file["file_path"]) for file in files])
    attached = await auth_client.put(
        f"/api/v1/experiments/{experiment_id}/collection-definition",
        files=_definition_upload(definition),
    )
    assert attached.status_code == 200, attached.text
    source_path = experiment_dir(experiment_id) / str(files[0]["file_path"])
    prepared_path = sidecar_path(file_path=str(source_path), source=None, name=None)
    prepared_path.parent.mkdir(parents=True, exist_ok=True)
    prepared_path.write_text(json.dumps(payload), encoding="utf-8")

    load_calls: list[bool] = []

    async def _unexpected_load(*args, **kwargs):
        del args, kwargs
        load_calls.append(True)
        raise AssertionError("invalid persisted preparation must refuse before scientific loading")

    monkeypatch.setattr(project_routes, "load_project_dataset", _unexpected_load)
    response = await auth_client.post(
        f"/api/v1/projects/{project_id}/save",
        json={"change_description": "Reject noncanonical prepared data"},
    )
    assert response.status_code == 409
    assert "sidecar" in response.json()["detail"]
    assert load_calls == []
    prepared_path.unlink()


@pytest.mark.anyio
async def test_project_save_aggregate_budget_refuses_before_source_materialization(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spectra_sherpa.app.api.v1.routes import projects as project_routes

    project_id, _, _ = await _project_experiment_with_two_sources(auth_client)
    source_reads: list[Path] = []

    def _unexpected_read(path: Path, *, expected_size: int | None = None) -> bytes:
        del expected_size
        source_reads.append(path)
        raise AssertionError("aggregate admission must run before source materialization")

    monkeypatch.setattr(project_routes, "PROJECT_ARCHIVE_RETAINED_BYTES_MAX", 1)
    monkeypatch.setattr(project_routes, "_read_bounded_regular_source", _unexpected_read)
    response = await auth_client.post(
        f"/api/v1/projects/{project_id}/save",
        json={"change_description": "Aggregate refusal"},
    )
    assert response.status_code == 409
    assert "aggregate-byte limit" in response.json()["detail"]
    assert source_reads == []


@pytest.mark.anyio
async def test_current_archive_cannot_strip_storage_identity(
    auth_client: AsyncClient,
    test_session: AsyncSession,
) -> None:
    from spectra_sherpa.app.services.sherpa_object import ArchiveMember, build_archive

    project_id, experiment_id, files = await _project_experiment_with_two_sources(auth_client)
    definition = _definition([str(file["file_path"]) for file in files])
    attached = await auth_client.put(
        f"/api/v1/experiments/{experiment_id}/collection-definition",
        files=_definition_upload(definition),
    )
    assert attached.status_code == 200, attached.text
    saved = await auth_client.post(
        f"/api/v1/projects/{project_id}/save",
        json={"change_description": "Closed portable science"},
    )
    assert saved.status_code == 201, saved.text
    exported = await auth_client.get(f"/api/v1/projects/{project_id}/export/sherpa?version_id={saved.json()['id']}")
    assert exported.status_code == 200, exported.text
    with zipfile.ZipFile(io.BytesIO(exported.content), "r") as archive:
        project_payload = json.loads(archive.read("project.json"))
        members = {
            name: archive.read(name)
            for name in archive.namelist()
            if name not in {"project.json", "sherpa-object.json"}
        }

    stripped = deepcopy(project_payload)
    stripped_experiment = stripped["experiments"][0]
    for key in list(stripped_experiment):
        if key.startswith(("collection_", "scientific_", "storage_snapshot_")):
            stripped_experiment.pop(key)
    for file_data in stripped_experiment["files"]:
        for key in (
            "archive_member",
            "archive_status",
            "prepared_data_archive_member",
            "prepared_data_sha256",
            "saved_prepared_data_sha256",
            "saved_sha256",
            "saved_size_bytes",
            "sha256",
        ):
            file_data.pop(key, None)
    stripped_archive = build_archive(
        project_payload=stripped,
        members=[ArchiveMember(name, data) for name, data in sorted(members.items())],
    )
    project_count = await test_session.scalar(select(func.count(Project.id)))
    stripped_response = await auth_client.post(
        "/api/v1/projects/import",
        files={"file": ("stripped.sherpa", io.BytesIO(stripped_archive), "application/zip")},
    )
    assert stripped_response.status_code == 400
    assert "storage snapshot" in stripped_response.json()["detail"]
    assert await test_session.scalar(select(func.count(Project.id))) == project_count


@pytest.mark.anyio
async def test_current_archive_rejects_changed_decoded_science(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spectra_sherpa.app.api.v1.routes import projects as project_routes

    project_id, experiment_id, files = await _project_experiment_with_two_sources(auth_client)
    definition = _definition([str(file["file_path"]) for file in files])
    attached = await auth_client.put(
        f"/api/v1/experiments/{experiment_id}/collection-definition",
        files=_definition_upload(definition),
    )
    assert attached.status_code == 200, attached.text
    saved = await auth_client.post(
        f"/api/v1/projects/{project_id}/save",
        json={"change_description": "Decoded science authority"},
    )
    assert saved.status_code == 201, saved.text
    exported = await auth_client.get(f"/api/v1/projects/{project_id}/export/sherpa?version_id={saved.json()['id']}")
    assert exported.status_code == 200, exported.text
    project_count = await test_session.scalar(select(func.count(Project.id)))
    real_load = project_routes.load_project_dataset

    async def _mutate_decoded_science(*args, **kwargs):
        loaded = await real_load(*args, **kwargs)
        loaded.dataset.X[0, 0] = float(loaded.dataset.X[0, 0]) + 1.0
        return loaded

    monkeypatch.setattr(project_routes, "load_project_dataset", _mutate_decoded_science)
    changed_science = await auth_client.post(
        "/api/v1/projects/import",
        files={"file": ("changed-science.sherpa", io.BytesIO(exported.content), "application/zip")},
    )
    assert changed_science.status_code == 400
    assert "decoded scientific projection" in changed_science.json()["detail"]
    assert await test_session.scalar(select(func.count(Project.id))) == project_count


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case",
    [
        "multi-experiment-count",
        "aggregate-bytes",
        "unbound-data-member",
        "prepared-unknown-field",
        "prepared-string-bool",
        "prepared-structured-title",
    ],
)
async def test_current_archive_admits_complete_tree_budget_before_restore(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    from spectra_sherpa.app.api.v1.routes import projects as project_routes
    from spectra_sherpa.app.services.prepared_data import PreparedDataOverrides
    from spectra_sherpa.app.services.sherpa_object import ArchiveMember, build_archive, sha256_bytes

    source = b"x"
    invalid_prepared = {
        "prepared-unknown-field": {"unknown_science": 42},
        "prepared-string-bool": {"is_time_series": "false"},
        "prepared-structured-title": {"title": {"nested": True}},
    }
    prepared = (
        json.dumps(invalid_prepared[case], sort_keys=True, separators=(",", ":")).encode()
        if case in invalid_prepared
        else project_routes._canonical_prepared_data_bytes(PreparedDataOverrides())
    )

    def _experiment_record(experiment_id: int) -> tuple[dict[str, object], list[ArchiveMember]]:
        rel_path = "raw/member.csv"
        source_member = project_routes._project_data_archive_member(experiment_id, rel_path)
        prepared_member = project_routes._project_prepared_data_archive_member(experiment_id, rel_path)
        return (
            {
                "id": experiment_id,
                "name": f"Experiment {experiment_id}",
                "description": None,
                "metadata": {},
                "file_count": 1,
                "files": [
                    {
                        "id": experiment_id,
                        "file_path": rel_path,
                        "stage": "raw",
                        "file_type": "csv",
                        "file_size_bytes": len(source),
                        "saved_size_bytes": len(source),
                        "saved_sha256": sha256_bytes(source),
                        "saved_prepared_data_sha256": sha256_bytes(prepared),
                        "sha256": sha256_bytes(source),
                        "prepared_data_sha256": sha256_bytes(prepared),
                        "archive_member": source_member,
                        "prepared_data_archive_member": prepared_member,
                        "archive_status": "included",
                    }
                ],
                "storage_snapshot_schema_version": project_routes.PROJECT_STORAGE_SNAPSHOT_SCHEMA_VERSION,
                "collection_definition": None,
                "collection_definition_sha256": None,
                "collection_definition_size_bytes": 0,
                "collection_definition_archive_member": None,
                "collection_source_manifest_sha256": None,
                "scientific_dataset_projection": None,
                "scientific_dataset_projection_sha256": None,
                "scientific_collection_schema_version": None,
                "scientific_collection_sha256": None,
            },
            [ArchiveMember(source_member, source), ArchiveMember(prepared_member, prepared)],
        )

    experiment_count = 2 if case == "multi-experiment-count" else 1
    records = [_experiment_record(index) for index in range(1, experiment_count + 1)]
    project_payload = {
        "name": "Adversarial portable project",
        "archive_format": {
            "schema": "spectra_sherpa_project_archive",
            "version": project_routes.PROJECT_ARCHIVE_FORMAT_VERSION,
            "data_members": project_routes.PROJECT_DATA_PREFIX,
        },
        "experiments": [record for record, _ in records],
        "children": [],
    }
    archive_members = [member for _, record_members in records for member in record_members]
    if case == "unbound-data-member":
        archive_members.append(ArchiveMember("data/experiments/999/raw/unbound.csv", b"unbound"))
    archive = build_archive(
        project_payload=project_payload,
        members=archive_members,
    )
    if case == "multi-experiment-count":
        monkeypatch.setattr(project_routes, "MAX_COLLECTION_MEMBERS", 1)
    elif case == "aggregate-bytes":
        monkeypatch.setattr(project_routes, "PROJECT_ARCHIVE_RETAINED_BYTES_MAX", 1)

    restore_calls: list[bool] = []

    async def _unexpected_restore(*args, **kwargs):
        del args, kwargs
        restore_calls.append(True)
        raise AssertionError("tree admission must refuse before restore")

    monkeypatch.setattr(project_routes, "_restore_project_tree_from_snapshot", _unexpected_restore)
    response = await auth_client.post(
        "/api/v1/projects/import",
        files={"file": (f"{case}.sherpa", io.BytesIO(archive), "application/zip")},
    )
    assert response.status_code == (413 if case in {"multi-experiment-count", "aggregate-bytes"} else 400)
    assert restore_calls == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case",
    [
        "aggregate-model-bytes",
        "decoded-model-bytes",
        "missing-model-member",
        "unbound-model-member",
        "invalid-model-manifest",
        "equivalent-model-identity",
        "wrong-model-integrity",
        "wrong-model-inventory",
        "wrong-model-identity",
        "wrong-model-type",
    ],
)
async def test_current_archive_admits_model_members_before_materialization(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    import uuid

    import numpy as np

    from spectra_sherpa.app.api.v1.routes import projects as project_routes
    from spectra_sherpa.app.services.sherpa_object import ArchiveMember, build_archive

    artifact_uid = str(uuid.uuid4())
    arrays = io.BytesIO()
    if case == "decoded-model-bytes":
        np.savez_compressed(arrays, values=np.zeros(100_000, dtype=np.float64))
    else:
        np.savez(arrays, values=np.asarray([1.0]))
    arrays_payload = arrays.getvalue()
    integrity_hash = project_routes.sha256_bytes(arrays_payload)
    declared_shape = [100_000] if case == "decoded-model-bytes" else [1]
    model_record = {
        "artifact_uid": artifact_uid,
        "model_type": "pca",
        "integrity_hash": integrity_hash,
    }
    models = [] if case == "unbound-model-member" else [model_record]
    manifest_record = {
        "artifact_uid": artifact_uid,
        "model_type": "pca",
        "integrity_hash": integrity_hash,
        "arrays": {"values": {"shape": declared_shape, "dtype": "float64"}},
    }
    if case == "wrong-model-integrity":
        model_record["integrity_hash"] = "0" * 64
        manifest_record["integrity_hash"] = "0" * 64
    elif case == "wrong-model-inventory":
        manifest_record["arrays"] = {"values": {"shape": [2], "dtype": "float64"}}
    elif case == "wrong-model-identity":
        manifest_record["artifact_uid"] = str(uuid.uuid4())
    elif case == "wrong-model-type":
        manifest_record["model_type"] = "pls"
    manifest = b"{" if case == "invalid-model-manifest" else json.dumps(manifest_record).encode()
    members = [ArchiveMember(f"models/{artifact_uid}/manifest.json", manifest)]
    if case != "missing-model-member":
        members.append(ArchiveMember(f"models/{artifact_uid}/arrays.npz", arrays_payload))
    if case == "equivalent-model-identity":
        equivalent_uid = artifact_uid.upper()
        models.append(
            {
                "artifact_uid": equivalent_uid,
                "model_type": "pca",
                "integrity_hash": integrity_hash,
            }
        )
        equivalent_manifest = dict(manifest_record, artifact_uid=equivalent_uid)
        members.extend(
            [
                ArchiveMember(
                    f"models/{equivalent_uid}/manifest.json",
                    json.dumps(equivalent_manifest).encode(),
                ),
                ArchiveMember(f"models/{equivalent_uid}/arrays.npz", arrays_payload),
            ]
        )
    project_payload = {
        "name": "Adversarial model archive",
        "archive_format": {
            "schema": "spectra_sherpa_project_archive",
            "version": project_routes.PROJECT_ARCHIVE_FORMAT_VERSION,
            "data_members": project_routes.PROJECT_DATA_PREFIX,
        },
        "experiments": [],
        "models": models,
        "children": [],
    }
    archive = build_archive(project_payload=project_payload, members=members)
    if case == "aggregate-model-bytes":
        monkeypatch.setattr(project_routes, "PROJECT_ARCHIVE_RETAINED_BYTES_MAX", 1)
    elif case == "decoded-model-bytes":
        monkeypatch.setattr(project_routes, "PROJECT_ARCHIVE_RETAINED_BYTES_MAX", 4096)

    materialization_calls: list[bool] = []

    def _unexpected_load(*args, **kwargs):
        del args, kwargs
        materialization_calls.append(True)
        raise AssertionError("model admission must refuse before array materialization")

    async def _unexpected_restore(*args, **kwargs):
        del args, kwargs
        materialization_calls.append(True)
        raise AssertionError("model admission must refuse before restore")

    monkeypatch.setattr(np, "load", _unexpected_load)
    monkeypatch.setattr(project_routes, "_restore_project_tree_from_snapshot", _unexpected_restore)
    response = await auth_client.post(
        "/api/v1/projects/import",
        files={"file": (f"{case}.sherpa", io.BytesIO(archive), "application/zip")},
    )
    assert response.status_code == (413 if case in {"aggregate-model-bytes", "decoded-model-bytes"} else 400)
    assert materialization_calls == []


@pytest.mark.anyio
async def test_current_archive_model_store_failure_rolls_back_project_and_artifact(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import uuid

    import numpy as np

    from spectra_sherpa.app.api.v1.routes import projects as project_routes
    from spectra_sherpa.app.services.model_store import get_model_store
    from spectra_sherpa.app.services.sherpa_object import ArchiveMember, build_archive

    artifact_uid = str(uuid.uuid4())
    arrays = io.BytesIO()
    np.savez(arrays, values=np.asarray([1.0]))
    archive = build_archive(
        project_payload={
            "name": "Model store rollback",
            "archive_format": {
                "schema": "spectra_sherpa_project_archive",
                "version": project_routes.PROJECT_ARCHIVE_FORMAT_VERSION,
                "data_members": project_routes.PROJECT_DATA_PREFIX,
            },
            "experiments": [],
            "models": [
                {
                    "artifact_uid": artifact_uid,
                    "model_type": "pca",
                    "integrity_hash": project_routes.sha256_bytes(arrays.getvalue()),
                }
            ],
            "children": [],
        },
        members=[
            ArchiveMember(
                f"models/{artifact_uid}/manifest.json",
                json.dumps(
                    {
                        "artifact_uid": artifact_uid,
                        "model_type": "pca",
                        "integrity_hash": project_routes.sha256_bytes(arrays.getvalue()),
                        "arrays": {"values": {"shape": [1], "dtype": "float64"}},
                    }
                ).encode(),
            ),
            ArchiveMember(f"models/{artifact_uid}/arrays.npz", arrays.getvalue()),
        ],
    )
    project_count = await test_session.scalar(select(func.count(Project.id)))
    store = get_model_store()

    original_promote_new = store._promote_new

    def _failed_promote(staging, artifact_dir):
        original_promote_new(staging, artifact_dir)
        raise OSError("injected post-promotion failure")

    monkeypatch.setattr(store, "_promote_new", _failed_promote)
    response = await auth_client.post(
        "/api/v1/projects/import",
        files={"file": ("store-failure.sherpa", io.BytesIO(archive), "application/zip")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Project model artifact could not be imported"
    assert await test_session.scalar(select(func.count(Project.id))) == project_count
    assert not store._artifact_dir(artifact_uid).exists()


@pytest.mark.anyio
@pytest.mark.parametrize("case", ["missing", "redirected", "tampered-bytes", "wrong-source-binding"])
async def test_collection_definition_archive_tampering_fails_closed_and_rolls_back(
    auth_client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    from spectra_sherpa.app.api.v1.routes import projects as project_routes
    from spectra_sherpa.app.lib.collection_definition import validate_collection_definition
    from spectra_sherpa.app.services.sherpa_object import ArchiveMember, build_archive

    project_id, experiment_id, files = await _project_experiment_with_two_sources(auth_client)
    definition = _definition([str(file["file_path"]) for file in files])
    attached = await auth_client.put(
        f"/api/v1/experiments/{experiment_id}/collection-definition",
        files=_definition_upload(definition),
    )
    assert attached.status_code == 200, attached.text
    saved = await auth_client.post(
        f"/api/v1/projects/{project_id}/save",
        json={"change_description": "Tamper authority"},
    )
    assert saved.status_code == 201, saved.text
    exported = await auth_client.get(f"/api/v1/projects/{project_id}/export/sherpa?version_id={saved.json()['id']}")
    assert exported.status_code == 200, exported.text

    with zipfile.ZipFile(io.BytesIO(exported.content), "r") as archive:
        original_project = json.loads(archive.read("project.json"))
        original_members = {
            name: archive.read(name)
            for name in archive.namelist()
            if name not in {"project.json", "sherpa-object.json"}
        }
    definition_member = original_project["experiments"][0]["collection_definition_archive_member"]

    wrong_source_project = deepcopy(original_project)
    wrong_payload = deepcopy(definition)
    wrong_payload["rows"][0]["sha256"] = "0" * 64  # type: ignore[index]
    wrong_definition = validate_collection_definition(wrong_payload)
    wrong_source_project["experiments"][0]["collection_definition"] = wrong_payload
    wrong_source_project["experiments"][0]["collection_definition_sha256"] = wrong_definition.sha256
    wrong_source_project["experiments"][0]["collection_definition_size_bytes"] = len(wrong_definition.canonical_bytes)

    redirected_project = deepcopy(original_project)
    redirected_project["experiments"][0][
        "collection_definition_archive_member"
    ] = f"data/experiments/{experiment_id}/redirected-definition.json"

    cases: dict[str, tuple[dict[str, object], dict[str, bytes]]] = {
        "missing": (
            deepcopy(original_project),
            {name: data for name, data in original_members.items() if name != definition_member},
        ),
        "redirected": (redirected_project, dict(original_members)),
        "tampered-bytes": (
            deepcopy(original_project),
            {**original_members, definition_member: b"{}\n"},
        ),
        "wrong-source-binding": (
            wrong_source_project,
            {**original_members, definition_member: wrong_definition.canonical_bytes},
        ),
    }

    deleted_experiment_ids: list[int] = []
    real_delete = project_routes.delete_experiment_files

    def _record_delete(experiment_id_to_delete: int) -> None:
        deleted_experiment_ids.append(experiment_id_to_delete)
        real_delete(experiment_id_to_delete)

    monkeypatch.setattr(project_routes, "delete_experiment_files", _record_delete)
    project_count = await test_session.scalar(select(func.count(Project.id)))

    project_payload, members = cases[case]
    archive_bytes = build_archive(
        project_payload=project_payload,
        members=[ArchiveMember(name, data) for name, data in sorted(members.items())],
    )
    response = await auth_client.post(
        "/api/v1/projects/import",
        files={"file": (f"{case}.sherpa", io.BytesIO(archive_bytes), "application/zip")},
    )
    assert response.status_code == 400, (case, response.text)
    assert deleted_experiment_ids == [], case
    assert all(not experiment_dir(item).exists() for item in deleted_experiment_ids)
    assert await test_session.scalar(select(func.count(Project.id))) == project_count
