"""Reference imports and restoration keep storage diagnostics server-side."""

import logging
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from spectra_sherpa.app.models.exp_version import ExpVersion
from spectra_sherpa.app.models.experiment_file import ExperimentFile

PRIVATE_PATH = "/private/operator-data/reference.csv"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["missing", "permission", "unknown"])
async def test_registered_reference_registry_privacy_and_upload_closure(
    auth_client, monkeypatch, caplog, tmp_path, kind
):
    from starlette.datastructures import UploadFile

    from spectra_sherpa.app.lib import reference_artifacts

    caplog.set_level(logging.WARNING)
    created = await auth_client.post("/api/v1/experiments", json={"name": "Registry privacy"})
    assert created.status_code == 201
    registry_path = tmp_path / "private-registry" / "reference-artifacts.json"
    load_registry = reference_artifacts.load_reference_artifact_registry
    read_text = Path.read_text
    closed_uploads = []
    close_upload = UploadFile.close

    async def record_close(upload):
        await close_upload(upload)
        closed_uploads.append(upload)

    def registry_read(path, *args, **kwargs):
        if path == registry_path and kind == "permission":
            raise PermissionError(13, "Permission denied", str(path))
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(UploadFile, "close", record_close)
    monkeypatch.setattr(Path, "read_text", registry_read)
    if kind != "unknown":
        monkeypatch.setattr(
            reference_artifacts, "load_reference_artifact_registry", lambda: load_registry(registry_path)
        )
    response = await auth_client.post(
        f"/api/v1/experiments/{created.json()['id']}/import-registered-reference",
        data={"projection_id": "no-such-qualified-projection"},
        files={"file": ("reference.zip", b"fixture", "application/zip")},
    )
    assert closed_uploads and all(upload.file.closed for upload in closed_uploads)
    assert str(registry_path) not in response.text
    if kind == "unknown":
        assert response.status_code == 404
        assert "unknown qualified reference projection" in response.json()["detail"]["message"]
    else:
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "registered_reference_unavailable"
        assert "check the installation" in response.json()["detail"]["message"]
        assert str(registry_path) in caplog.text


def _import_error(kind):
    if kind == "validation":
        return ValueError("The source size does not match its manifest")
    if kind == "wrapped":
        try:
            raise PermissionError(13, "Permission denied", PRIVATE_PATH)
        except OSError as cause:
            try:
                raise ValueError(str(cause)) from cause
            except ValueError as exc:
                return exc
    return (FileNotFoundError if kind == "missing" else PermissionError)(13, "Cannot read", PRIVATE_PATH)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["missing", "permission", "wrapped", "validation"])
async def test_reference_import_refusal_privacy(auth_client, test_session, monkeypatch, caplog, kind):
    from spectra_sherpa.app.api.v1.routes import experiments

    caplog.set_level(logging.WARNING)
    created = await auth_client.post("/api/v1/experiments", json={"name": "Privacy import"})
    assert created.status_code == 201, created.text
    experiment_id = created.json()["id"]
    error = _import_error(kind)
    imported = AsyncMock(side_effect=error)
    monkeypatch.setattr(experiments, "import_reference_dataset", imported)
    response = await auth_client.post(
        f"/api/v1/experiments/{experiment_id}/import-reference",
        json={"datasets": [{"source": "sklearn", "name": "iris"}]},
    )
    imported.assert_awaited_once()
    assert response.status_code == {"missing": 404, "permission": 503, "wrapped": 400, "validation": 400}[kind]
    assert PRIVATE_PATH not in response.text
    if kind == "validation":
        assert response.json()["detail"] == str(error)
    else:
        assert PRIVATE_PATH in caplog.text
    files = await test_session.scalars(select(ExperimentFile).where(ExperimentFile.experiment_id == experiment_id))
    assert list(files) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["exists", "permission"])
async def test_version_restore_refusal_privacy(auth_client, test_session, monkeypatch, caplog, kind):
    from spectra_sherpa.app.api.v1.routes import experiments

    caplog.set_level(logging.WARNING)
    created = await auth_client.post("/api/v1/experiments", json={"name": "Privacy restore"})
    assert created.status_code == 201, created.text
    experiment_id = created.json()["id"]
    test_session.add(ExpVersion(experiment_id=experiment_id, version_name="v1", manifest_path="versions/v1.json"))
    await test_session.commit()
    calls = []

    def fail_restore(self, version_name, *, overwrite=False):
        calls.append((version_name, overwrite))
        error_type = FileExistsError if kind == "exists" else PermissionError
        raise error_type(13, "Storage refused", PRIVATE_PATH)

    monkeypatch.setattr(experiments.ContentAddressableStorage, "restore_version", fail_restore)
    response = await auth_client.post(f"/api/v1/experiments/{experiment_id}/versions/v1/restore")
    assert response.status_code == (409 if kind == "exists" else 503)
    assert calls == [("v1", False)]
    assert PRIVATE_PATH not in response.text
    assert PRIVATE_PATH in caplog.text
    if kind == "exists":
        assert "Confirm overwrite" in response.json()["detail"]
