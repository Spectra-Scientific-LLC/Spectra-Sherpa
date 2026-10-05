from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from spectra_sherpa.app.lib.reference_artifacts import ReferenceArtifactRegistryError
from spectra_sherpa.app.lib.reference_materialization import ReferenceMaterializationError
from spectra_sherpa.app.services.experiments import experiment_dir

pytestmark = pytest.mark.asyncio


class _Record:
    def __init__(self, value: dict[str, object]) -> None:
        self._value = value

    def as_dict(self) -> dict[str, object]:
        return dict(self._value)


class _Registry:
    projection_id = "fixture-reference-v1"

    def projection(self, projection_id: str) -> _Record:
        if projection_id != self.projection_id:
            raise ReferenceArtifactRegistryError("unknown registered reference projection")
        return _Record(
            {
                "projection_id": self.projection_id,
                "artifact_id": "fixture-artifact-v1",
                "member_path": "fixture.mat",
                "scientific_sha256": "c" * 64,
            }
        )

    def artifact(self, artifact_id: str) -> _Record:
        assert artifact_id == "fixture-artifact-v1"
        return _Record(
            {
                "artifact_id": artifact_id,
                "expected_size_bytes": 6,
                "sha256": hashlib.sha256(b"ABCDEF").hexdigest(),
            }
        )


async def _experiment(auth_client: AsyncClient, *, project_id: int | None = None) -> dict:
    if project_id is None:
        project = (await auth_client.post("/api/v1/projects", json={"name": "Reference import"})).json()
        project_id = project["id"]
    return (
        await auth_client.post(
            "/api/v1/experiments",
            json={"name": "Imported reference", "project_id": project_id},
        )
    ).json()


@pytest.fixture
def reference_import_fakes(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    from spectra_sherpa.app.contracts import demo_policy
    from spectra_sherpa.app.lib import (
        reference_artifacts,
        reference_materialization,
        registered_reference_storage,
    )

    staged_paths: list[Path] = []
    grants: list[dict[str, object]] = []
    authority: list[SimpleNamespace] = []
    portable = {
        "schema_version": "spectra-sherpa-external-reference/1",
        "projection_id": _Registry.projection_id,
        "artifact_id": "fixture-artifact-v1",
        "artifact_size_bytes": 6,
        "artifact_sha256": hashlib.sha256(b"ABCDEF").hexdigest(),
        "member_path": "fixture.mat",
        "member_size_bytes": 13,
        "member_sha256": "b" * 64,
        "native_reader_contract": "spectrasherpa.matlab-dso/1",
        "scientific_sha256": "c" * 64,
        "provider": "Fixture Provider",
        "provider_page": "https://example.test",
        "download_url": "https://example.test/file.zip",
        "redistribution": "upstream_only_not_redistributed",
    }

    def _materialize(source: Path, projection_id: str, **kwargs):
        assert projection_id == _Registry.projection_id
        assert Path(source).read_bytes() == b"ABCDEF"
        staged_paths.append(Path(source))
        destination = Path(kwargs["persist_member_to"])
        destination.write_bytes(b"native-member")
        return SimpleNamespace(portable_reference=dict(portable))

    def _write_sidecar(member_path: Path, identity: dict) -> Path:
        sidecar = registered_reference_storage.registered_reference_sidecar_path(member_path)
        sidecar.write_text(json.dumps({"portable_reference": identity}))
        return sidecar

    async def _issue_grant(**kwargs):
        grants.append(dict(kwargs))
        if not authority:
            authority.append(
                SimpleNamespace(
                    experiment_id=kwargs["experiment_id"],
                    file_id=kwargs["file_id"],
                )
            )
        return authority[0]

    monkeypatch.setattr(reference_artifacts, "load_reference_artifact_registry", lambda: _Registry())
    monkeypatch.setattr(reference_materialization, "materialize_reference_projection", _materialize)
    monkeypatch.setattr(registered_reference_storage, "write_registered_reference_sidecar", _write_sidecar)
    monkeypatch.setattr(demo_policy, "_trial_reference_grant_provider", _issue_grant)
    monkeypatch.setattr(demo_policy, "_demo_policy_provider", None)
    return SimpleNamespace(staged_paths=staged_paths, grants=grants, authority=authority)


async def test_registered_reference_import_accepts_renamed_exact_file_and_deletes_upload_snapshot(
    auth_client: AsyncClient,
    reference_import_fakes: SimpleNamespace,
) -> None:
    experiment = await _experiment(auth_client)

    response = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/import-registered-reference",
        data={"projection_id": _Registry.projection_id},
        files={"file": ("scientist-renamed-without-extension.bin", b"ABCDEF", "application/octet-stream")},
    )

    assert response.status_code == 201, response.text
    assert response.json()["imported"] == 1
    assert response.json()["experiment_id"] == experiment["id"]
    assert response.json()["reused_existing"] is False
    assert response.json()["initial_file_ids"] == [response.json()["files"][0]["id"]]
    retained_path = Path(response.json()["files"][0]["file_path"])
    assert retained_path.parent.parent == Path("raw")
    assert retained_path.name == f"{_Registry.projection_id}.mat"
    assert reference_import_fakes.staged_paths
    assert all(not path.exists() for path in reference_import_fakes.staged_paths)
    assert len(reference_import_fakes.grants) == 1
    assert reference_import_fakes.grants[0]["dataset_key"] == _Registry.projection_id
    assert reference_import_fakes.grants[0]["asset_id"] == _Registry.projection_id


async def test_registered_reference_retry_in_same_experiment_preserves_first_member_and_sidecar(
    auth_client: AsyncClient,
    reference_import_fakes: SimpleNamespace,
) -> None:
    experiment = await _experiment(auth_client)
    endpoint = f"/api/v1/experiments/{experiment['id']}/import-registered-reference"
    request = {
        "data": {"projection_id": _Registry.projection_id},
        "files": {"file": ("fixture.zip", b"ABCDEF", "application/zip")},
    }
    first = await auth_client.post(endpoint, **request)
    assert first.status_code == 201, first.text
    first_file = first.json()["files"][0]
    retained = experiment_dir(experiment["id"]) / first_file["file_path"]
    sidecar = retained.with_name(f"{retained.name}.reference.json")
    first_bytes, first_sidecar = retained.read_bytes(), sidecar.read_bytes()

    retry = await auth_client.post(endpoint, **request)
    assert retry.status_code == 201, retry.text
    assert retry.json()["reused_existing"] is True
    assert retry.json()["files"] == [first_file]
    assert retained.read_bytes() == first_bytes
    assert sidecar.read_bytes() == first_sidecar
    assert len(list(retained.parent.parent.glob("*"))) == 1


async def test_reference_grant_refusal_is_not_misreported_as_file_mismatch_or_delete_prior_import(
    auth_client: AsyncClient,
    reference_import_fakes: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spectra_sherpa.app.contracts import demo_policy

    experiment = await _experiment(auth_client)
    endpoint = f"/api/v1/experiments/{experiment['id']}/import-registered-reference"
    request = {
        "data": {"projection_id": _Registry.projection_id},
        "files": {"file": ("fixture.zip", b"ABCDEF", "application/zip")},
    }
    first = await auth_client.post(endpoint, **request)
    assert first.status_code == 201, first.text
    retained = experiment_dir(experiment["id"]) / first.json()["files"][0]["file_path"]
    sidecar = retained.with_name(f"{retained.name}.reference.json")
    first_bytes, first_sidecar = retained.read_bytes(), sidecar.read_bytes()

    async def refuse_grant(**_kwargs):
        raise ValueError("state-dependent grant conflict")

    monkeypatch.setattr(demo_policy, "_trial_reference_grant_provider", refuse_grant)
    failed = await auth_client.post(endpoint, **request)
    assert failed.status_code == 409, failed.text
    assert failed.json()["detail"]["code"] == "registered_reference_retention_failed"
    assert "file was verified" in failed.json()["detail"]["message"]
    assert retained.read_bytes() == first_bytes
    assert sidecar.read_bytes() == first_sidecar
    assert len(list(retained.parent.parent.glob("*"))) == 1


async def test_registered_reference_package_imports_all_views_and_selects_only_declared_initial_view(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spectra_sherpa.app.contracts import demo_policy
    from spectra_sherpa.app.lib import (
        reference_artifacts,
        reference_dataset_packages,
        reference_materialization,
        registered_reference_storage,
    )

    projection_ids = ["fixture-m5-v1", "fixture-mp5-v1", "fixture-mp6-v1"]
    view_ids = ["corn-m5", "corn-mp5", "corn-mp6"]

    class _PackageArtifactRegistry:
        def projection(self, projection_id: str) -> _Record:
            if projection_id not in projection_ids:
                raise ReferenceArtifactRegistryError("unknown registered reference projection")
            return _Record(
                {
                    "projection_id": projection_id,
                    "artifact_id": "fixture-corn-archive-v1",
                    "member_path": "corn.mat",
                    "scientific_sha256": projection_id[-2:].ljust(64, "c"),
                }
            )

        def artifact(self, artifact_id: str) -> _Record:
            assert artifact_id == "fixture-corn-archive-v1"
            return _Record(
                {
                    "artifact_id": artifact_id,
                    "expected_size_bytes": 6,
                    "sha256": hashlib.sha256(b"ABCDEF").hexdigest(),
                }
            )

    package = {
        "package_id": "eigenvector-corn-v1",
        "assembly_mode": "homogeneous_collection",
        "artifact_ids": ["fixture-corn-archive-v1"],
        "initial_view_ids": ["corn-m5"],
        "views": [
            {"view_id": view_id, "projection_id": projection_id}
            for view_id, projection_id in zip(view_ids, projection_ids, strict=True)
        ],
    }
    artifact_registry = _PackageArtifactRegistry()
    package_registry = SimpleNamespace(package=lambda _package_id: _Record(package))
    materialized: list[str] = []
    grants: list[dict[str, object]] = []

    def _materialize(source: Path, projection_id: str, **kwargs):
        assert source.read_bytes() == b"ABCDEF"
        destination = Path(kwargs["persist_member_to"])
        destination.write_bytes(projection_id.encode("ascii"))
        materialized.append(projection_id)
        return SimpleNamespace(
            portable_reference={
                "projection_id": projection_id,
                "member_sha256": "b" * 64,
            }
        )

    def _write_sidecar(member_path: Path, identity: dict) -> Path:
        sidecar = registered_reference_storage.registered_reference_sidecar_path(member_path)
        sidecar.write_text(json.dumps({"portable_reference": identity}))
        return sidecar

    async def _issue_grant(**kwargs):
        grants.append(dict(kwargs))
        return SimpleNamespace(experiment_id=kwargs["experiment_id"], file_id=None)

    monkeypatch.setattr(reference_artifacts, "load_reference_artifact_registry", lambda: artifact_registry)
    monkeypatch.setattr(
        reference_dataset_packages,
        "load_reference_dataset_package_registry",
        lambda **_kwargs: package_registry,
    )
    monkeypatch.setattr(reference_materialization, "materialize_reference_projection", _materialize)
    monkeypatch.setattr(registered_reference_storage, "write_registered_reference_sidecar", _write_sidecar)
    monkeypatch.setattr(demo_policy, "_trial_reference_grant_provider", _issue_grant)
    monkeypatch.setattr(demo_policy, "_demo_policy_provider", None)

    experiment = await _experiment(auth_client)
    response = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/import-registered-reference",
        data={"package_id": "eigenvector-corn-v1"},
        files={"file": ("scientist-corn.zip", b"ABCDEF", "application/zip")},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["imported"] == 3
    assert payload["reused_existing"] is False
    assert [Path(item["file_path"]).stem for item in payload["files"]] == view_ids
    assert payload["initial_file_ids"] == [payload["files"][0]["id"]]
    assert materialized == projection_ids
    assert len(grants) == 1
    assert grants[0]["dataset_key"] == "eigenvector-corn-v1"
    assert grants[0]["file_id"] is None
    assert grants[0]["asset_id"] is None


async def test_single_view_package_issues_managed_grant_for_underlying_projection(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spectra_sherpa.app.contracts import demo_policy
    from spectra_sherpa.app.lib import (
        reference_artifacts,
        reference_dataset_packages,
        reference_materialization,
        registered_reference_storage,
    )

    projection_id = "public-art-image-paint-demo-v1"
    package_id = "eigenvector-art-image-demo-v1"
    package = {
        "package_id": package_id,
        "assembly_mode": "single_view",
        "artifact_ids": ["fixture-artifact-v1"],
        "initial_view_ids": ["art-image-paint"],
        "views": [{"view_id": "art-image-paint", "projection_id": projection_id}],
    }
    grants: list[dict[str, object]] = []

    class _SingleViewRegistry(_Registry):
        pass

    _SingleViewRegistry.projection_id = projection_id

    def _materialize(source: Path, selected_projection_id: str, **kwargs):
        assert source.read_bytes() == b"ABCDEF"
        assert selected_projection_id == projection_id
        destination = Path(kwargs["persist_member_to"])
        destination.write_bytes(b"native-member")
        return SimpleNamespace(portable_reference={"member_sha256": "b" * 64})

    async def _managed_issue_grant(**kwargs):
        # Mirror the server boundary: this projection is allowlisted, while
        # the target-free package identifier deliberately is not.
        assert kwargs["dataset_key"] == projection_id
        grants.append(dict(kwargs))
        return SimpleNamespace(experiment_id=kwargs["experiment_id"], file_id=kwargs["file_id"])

    monkeypatch.setattr(reference_artifacts, "load_reference_artifact_registry", lambda: _SingleViewRegistry())
    monkeypatch.setattr(
        reference_dataset_packages,
        "load_reference_dataset_package_registry",
        lambda **_kwargs: SimpleNamespace(package=lambda _package_id: _Record(package)),
    )
    monkeypatch.setattr(reference_materialization, "materialize_reference_projection", _materialize)
    monkeypatch.setattr(
        registered_reference_storage,
        "write_registered_reference_sidecar",
        lambda member_path, _identity: member_path,
    )
    monkeypatch.setattr(demo_policy, "_trial_reference_grant_provider", _managed_issue_grant)
    monkeypatch.setattr(demo_policy, "_demo_policy_provider", None)

    experiment = await _experiment(auth_client)
    response = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/import-registered-reference",
        data={"package_id": package_id},
        files={"file": ("scientist-art-image.zip", b"ABCDEF", "application/zip")},
    )

    assert response.status_code == 201, response.text
    assert len(grants) == 1
    assert grants[0]["dataset_key"] == projection_id
    assert grants[0]["asset_id"] == projection_id
    assert grants[0]["file_id"] == response.json()["files"][0]["id"]


async def test_heterogeneous_package_maps_renamed_files_by_digest_and_grants_each_view(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spectra_sherpa.app.contracts import demo_policy
    from spectra_sherpa.app.lib import (
        reference_artifacts,
        reference_dataset_packages,
        reference_materialization,
        registered_reference_storage,
    )

    sources = {
        "machine": b"MACHINE",
        "oes": b"OES-DATA",
        "rfm": b"RFM-DATA-SET",
    }
    projection_ids = {name: f"fixture-metal-{name}-v1" for name in sources}
    artifact_ids = {name: f"fixture-metal-{name}-archive-v1" for name in sources}
    view_ids = {name: f"metal-etch-{name}" for name in sources}

    class _MetalRegistry:
        def projection(self, projection_id: str) -> _Record:
            name = next((name for name, value in projection_ids.items() if value == projection_id), None)
            if name is None:
                raise ReferenceArtifactRegistryError("unknown registered reference projection")
            return _Record(
                {
                    "projection_id": projection_id,
                    "artifact_id": artifact_ids[name],
                    "member_path": f"{name}.mat",
                    "scientific_sha256": name.ljust(64, "c"),
                }
            )

        def artifact(self, artifact_id: str) -> _Record:
            name = next((name for name, value in artifact_ids.items() if value == artifact_id), None)
            if name is None:
                raise ReferenceArtifactRegistryError("unknown registered reference artifact")
            value = sources[name]
            return _Record(
                {
                    "artifact_id": artifact_id,
                    "expected_size_bytes": len(value),
                    "sha256": hashlib.sha256(value).hexdigest(),
                }
            )

    package = {
        "package_id": "eigenvector-metal-etch-v1",
        "assembly_mode": "heterogeneous_views",
        "artifact_ids": list(artifact_ids.values()),
        "initial_view_ids": ["metal-etch-oes"],
        "views": [{"view_id": view_ids[name], "projection_id": projection_ids[name]} for name in sources],
    }
    registry = _MetalRegistry()
    package_registry = SimpleNamespace(package=lambda _package_id: _Record(package))
    grants: list[dict[str, object]] = []

    def _materialize(source: Path, projection_id: str, **kwargs):
        name = next(name for name, value in projection_ids.items() if value == projection_id)
        assert source.read_bytes() == sources[name]
        destination = Path(kwargs["persist_member_to"])
        destination.write_bytes(f"native-{name}".encode("ascii"))
        return SimpleNamespace(portable_reference={"member_sha256": name.ljust(64, "b")})

    def _write_sidecar(member_path: Path, identity: dict) -> Path:
        sidecar = registered_reference_storage.registered_reference_sidecar_path(member_path)
        sidecar.write_text(json.dumps({"portable_reference": identity}))
        return sidecar

    async def _issue_grant(**kwargs):
        grants.append(dict(kwargs))
        return SimpleNamespace(experiment_id=kwargs["experiment_id"], file_id=kwargs["file_id"])

    monkeypatch.setattr(reference_artifacts, "load_reference_artifact_registry", lambda: registry)
    monkeypatch.setattr(
        reference_dataset_packages,
        "load_reference_dataset_package_registry",
        lambda **_kwargs: package_registry,
    )
    monkeypatch.setattr(reference_materialization, "materialize_reference_projection", _materialize)
    monkeypatch.setattr(registered_reference_storage, "write_registered_reference_sidecar", _write_sidecar)
    monkeypatch.setattr(demo_policy, "_trial_reference_grant_provider", _issue_grant)
    monkeypatch.setattr(demo_policy, "_demo_policy_provider", None)

    experiment = await _experiment(auth_client)
    incomplete = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/import-registered-reference",
        data={"package_id": "eigenvector-metal-etch-v1"},
        files=[
            ("file", ("first-renamed.zip", sources["machine"], "application/zip")),
            ("file", ("second-renamed.zip", sources["oes"], "application/zip")),
        ],
    )

    assert incomplete.status_code == 400, incomplete.text
    assert incomplete.json()["detail"] == {
        "code": "registered_reference_file_count_invalid",
        "message": "registered reference import requires exactly 3 provider file(s)",
    }
    assert grants == []

    response = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/import-registered-reference",
        data={"package_id": "eigenvector-metal-etch-v1"},
        files=[
            ("file", ("third-renamed.zip", sources["rfm"], "application/zip")),
            ("file", ("first-renamed.zip", sources["machine"], "application/zip")),
            ("file", ("second-renamed.zip", sources["oes"], "application/zip")),
        ],
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["imported"] == 3
    assert [Path(item["file_path"]).stem for item in payload["files"]] == list(view_ids.values())
    assert payload["initial_file_ids"] == [payload["files"][1]["id"]]
    assert [grant["dataset_key"] for grant in grants] == list(projection_ids.values())
    assert [grant["asset_id"] for grant in grants] == list(projection_ids.values())
    assert all(grant["file_id"] is not None for grant in grants)


async def test_registered_reference_reimport_reuses_exact_durable_dataset_without_duplicate_retention(
    auth_client: AsyncClient,
    reference_import_fakes: SimpleNamespace,
) -> None:
    first_experiment = await _experiment(auth_client)
    first = await auth_client.post(
        f"/api/v1/experiments/{first_experiment['id']}/import-registered-reference",
        data={"projection_id": _Registry.projection_id},
        files={"file": ("first-download.zip", b"ABCDEF", "application/zip")},
    )
    assert first.status_code == 201, first.text
    first_file = first.json()["files"][0]

    duplicate_experiment = await _experiment(auth_client, project_id=first_experiment["project_id"])
    duplicate = await auth_client.post(
        f"/api/v1/experiments/{duplicate_experiment['id']}/import-registered-reference",
        data={"projection_id": _Registry.projection_id},
        files={"file": ("renamed-second-download.bin", b"ABCDEF", "application/octet-stream")},
    )

    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json() == {
        "imported": 0,
        "files": [first_file],
        "experiment_id": first_experiment["id"],
        "reused_existing": True,
        "initial_file_ids": [first_file["id"]],
    }
    duplicate_files = await auth_client.get(f"/api/v1/experiments/{duplicate_experiment['id']}/files")
    assert duplicate_files.status_code == 200, duplicate_files.text
    assert duplicate_files.json() == []
    assert not list((experiment_dir(duplicate_experiment["id"]) / "raw").glob("*"))
    assert len(reference_import_fakes.grants) == 2


async def test_registered_provider_member_is_analysable_but_not_republished_as_a_raw_download(
    auth_client: AsyncClient,
    reference_import_fakes: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spectra_sherpa.app.api.v1.routes import datasets

    experiment = await _experiment(auth_client)
    imported = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/import-registered-reference",
        data={"projection_id": _Registry.projection_id},
        files={"file": ("renamed.zip", b"ABCDEF", "application/zip")},
    )
    assert imported.status_code == 201, imported.text
    file_id = imported.json()["files"][0]["id"]
    monkeypatch.setattr(datasets, "read_registered_reference_sidecar", lambda _path: {"registered": True})

    response = await auth_client.get(f"/api/v1/datasets/download/{file_id}")

    assert response.status_code == 403
    assert "not redistributed" in response.text
    assert "provider" in response.text


async def test_paid_ordinary_supported_upload_remains_downloadable_and_is_not_reclassified(
    auth_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spectra_sherpa.app.api.v1.routes import datasets
    from spectra_sherpa.app.core.config import app_config

    experiment = await _experiment(auth_client)
    source = (
        b"##TITLE=Paid scientist source\n"
        b"##XUNITS=1/CM\n"
        b"##YUNITS=ABSORBANCE\n"
        b"##XYDATA=(X++(Y..Y))\n"
        b"1 0.1 0.2\n"
        b"##END=\n"
    )
    monkeypatch.setattr(app_config, "site_profile", "pro")
    from spectra_sherpa.app.contracts import scientific_access
    from spectra_sherpa.app.models.project import Project

    async def admitted_owned_fixture(session, user_id, project_id, operation):
        # This OSS test verifies ingestion/redistribution, not the server's
        # commercial grant resolver (covered by its real qualification suite).
        project = await session.get(Project, project_id)
        assert project is not None and project.user_id == user_id

    monkeypatch.setattr(scientific_access, "_provider", admitted_owned_fixture)
    monkeypatch.setattr(datasets, "read_registered_reference_sidecar", lambda _path: None)
    uploaded = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/files",
        data={"stage": "raw", "data_role": "X_spectra"},
        files={"file": ("customer-source.jdx", source, "chemical/x-jcamp-dx")},
    )
    assert uploaded.status_code == 201, uploaded.text

    file_id = uploaded.json()["id"]
    inspected = await auth_client.get(f"/api/v1/experiments/{experiment['id']}/files/{file_id}/scientific-assets")
    assert inspected.status_code == 200, inspected.text
    inventory = inspected.json()
    assert inventory["assets"][0]["shape"] == [1, 2]
    assert inventory["assets"][0]["data_quantity"] == "Absorbance"

    response = await auth_client.get(f"/api/v1/datasets/download/{file_id}")

    assert response.status_code == 200
    assert response.content == source


async def test_registered_reference_import_refuses_size_mismatch_without_persisting_file(
    auth_client: AsyncClient,
    reference_import_fakes: SimpleNamespace,
) -> None:
    experiment = await _experiment(auth_client)

    response = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/import-registered-reference",
        data={"projection_id": _Registry.projection_id},
        files={"file": ("fixture.zip", b"SHORT", "application/zip")},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "registered_reference_mismatch"
    assert reference_import_fakes.staged_paths == []
    assert reference_import_fakes.grants == []
    assert not list((experiment_dir(experiment["id"]) / "raw").glob("*"))


async def test_registered_reference_import_refuses_digest_or_science_mismatch_and_cleans_destination(
    auth_client: AsyncClient,
    reference_import_fakes: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from spectra_sherpa.app.lib import reference_materialization

    experiment = await _experiment(auth_client)

    def _refuse(_source: Path, _projection_id: str, **kwargs):
        Path(kwargs["persist_member_to"]).write_bytes(b"partial")
        raise ReferenceMaterializationError("scientific authority mismatch")

    monkeypatch.setattr(reference_materialization, "materialize_reference_projection", _refuse)
    response = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/import-registered-reference",
        data={"projection_id": _Registry.projection_id},
        files={"file": ("fixture.zip", b"ABCDEF", "application/zip")},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "registered_reference_mismatch"
    assert not list((experiment_dir(experiment["id"]) / "raw").glob("*"))
    assert reference_import_fakes.grants == []


async def test_registered_reference_import_refuses_unknown_projection_before_retention(
    auth_client: AsyncClient,
    reference_import_fakes: SimpleNamespace,
) -> None:
    experiment = await _experiment(auth_client)

    response = await auth_client.post(
        f"/api/v1/experiments/{experiment['id']}/import-registered-reference",
        data={"projection_id": "not-registered"},
        files={"file": ("fixture.zip", b"ABCDEF", "application/zip")},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "registered_reference_unknown"
    assert reference_import_fakes.staged_paths == []
    assert reference_import_fakes.grants == []
