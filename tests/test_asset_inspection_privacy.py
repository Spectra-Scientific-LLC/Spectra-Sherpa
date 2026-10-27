"""Scientific asset inspection refuses safely without losing scientific advice."""

import logging
from unittest.mock import Mock

import pytest

from spectra_sherpa.app.lib.reference_materialization import ReferenceMaterializationError
from spectra_sherpa.app.lib.registered_reference_storage import RegisteredReferenceStorageError
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.ingestion_errors import UnreadableSpectrumError

PRIVATE_PATH = "/private/operator-data/source.mat"


async def _source(auth_client, test_session):
    created = await auth_client.post("/api/v1/experiments", json={"name": "Asset inspection"})
    assert created.status_code == 201, created.text
    experiment_id = created.json()["id"]
    record = ExperimentFile(experiment_id=experiment_id, file_path="raw/source.mat", stage="raw", file_type="mat")
    test_session.add(record)
    await test_session.commit()
    return experiment_id, record.id


def _failure(stage, kind):
    if kind == "storage":
        return PermissionError(13, "Cannot read", PRIVATE_PATH)
    if kind == "wrapped":
        try:
            raise PermissionError(13, "Cannot read", PRIVATE_PATH)
        except OSError as cause:
            try:
                raise ValueError(str(cause)) from cause
            except ValueError as exc:
                return exc
    return {
        "sidecar": RegisteredReferenceStorageError("registered reference sidecar differs from the active registry"),
        "projection": ReferenceMaterializationError(
            "registered reference scientific content differs from its authority"
        ),
        "native": UnreadableSpectrumError(format_id="matlab", detail="source contains no numeric spectral matrix"),
    }[stage]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["sidecar", "projection", "native"])
@pytest.mark.parametrize("kind", ["storage", "wrapped", "validation"])
async def test_asset_inspection_error_boundary(auth_client, test_session, monkeypatch, caplog, stage, kind):
    from spectra_sherpa import io
    from spectra_sherpa.app.lib import reference_materialization, registered_reference_storage

    caplog.set_level(logging.WARNING)
    experiment_id, file_id = await _source(auth_client, test_session)
    error = _failure(stage, kind)
    sidecar = Mock(return_value={"projection_id": "qualified-reference"} if stage == "projection" else None)
    projection = Mock()
    native = Mock()
    selected = {"sidecar": sidecar, "projection": projection, "native": native}[stage]
    selected.side_effect = error
    monkeypatch.setattr(registered_reference_storage, "read_registered_reference_sidecar", sidecar)
    monkeypatch.setattr(reference_materialization, "materialize_reference_member", projection)
    monkeypatch.setattr(io, "ingest", native)

    response = await auth_client.get(f"/api/v1/experiments/{experiment_id}/files/{file_id}/scientific-assets")
    expected = 503 if kind == "storage" else (400 if stage == "native" else 409)
    assert response.status_code == expected, response.text
    selected.assert_called_once()
    assert PRIVATE_PATH not in response.text
    if kind == "validation":
        assert str(error) in response.json()["detail"]
    else:
        assert "check storage access" in response.json()["detail"]
        assert PRIVATE_PATH in caplog.text
    if stage != "native":
        native.assert_not_called()  # Never bypass failed reference authority with generic ingestion.
    if stage == "sidecar":
        projection.assert_not_called()


@pytest.mark.asyncio
async def test_real_invalid_sidecar_refuses_without_native_fallback(auth_client, test_session, monkeypatch):
    from spectra_sherpa import io
    from spectra_sherpa.app.lib.registered_reference_storage import registered_reference_sidecar_path
    from spectra_sherpa.app.services.experiments import experiment_dir

    experiment_id, file_id = await _source(auth_client, test_session)
    source = experiment_dir(experiment_id) / "raw/source.mat"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"not a native source")
    sidecar = registered_reference_sidecar_path(source)
    sidecar.write_bytes(b"{invalid json")
    native = Mock()
    monkeypatch.setattr(io, "ingest", native)
    response = await auth_client.get(f"/api/v1/experiments/{experiment_id}/files/{file_id}/scientific-assets")
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "registered reference sidecar is unreadable"
    assert str(source.parent) not in response.text
    assert sidecar.read_bytes() == b"{invalid json"
    native.assert_not_called()


@pytest.mark.asyncio
async def test_real_missing_source_refuses_with_storage_remedy(auth_client, test_session, caplog):
    from spectra_sherpa.app.services.experiments import experiment_dir

    caplog.set_level(logging.WARNING)
    experiment_id, file_id = await _source(auth_client, test_session)
    source = experiment_dir(experiment_id) / "raw/source.mat"
    assert not source.exists()
    response = await auth_client.get(f"/api/v1/experiments/{experiment_id}/files/{file_id}/scientific-assets")
    assert response.status_code == 400, response.text
    assert "check storage access" in response.json()["detail"]
    assert str(source) not in response.text
    assert str(source) in caplog.text


@pytest.mark.asyncio
async def test_unknown_file_refuses_before_storage_inspection(auth_client, test_session, monkeypatch):
    from spectra_sherpa.app.lib import registered_reference_storage

    experiment_id, file_id = await _source(auth_client, test_session)
    sidecar = Mock()
    monkeypatch.setattr(registered_reference_storage, "read_registered_reference_sidecar", sidecar)
    response = await auth_client.get(f"/api/v1/experiments/{experiment_id}/files/{file_id + 1000}/scientific-assets")
    assert response.status_code == 404
    sidecar.assert_not_called()
