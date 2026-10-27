"""Collection mutations retain scientific refusals, never storage exception text."""

import logging
from unittest.mock import AsyncMock, Mock

import pytest

from spectra_sherpa.app.api.v1.routes import experiments as routes
from spectra_sherpa.app.models.experiment_file import ExperimentFile
from spectra_sherpa.app.services.dag.nodes.data.loaders import ExperimentDatasetReader
from spectra_sherpa.app.services.model_application import load_project_dataset
from tests.test_collection_definition_api import _definition, _definition_upload, _project_experiment_with_two_sources


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["preview", "save", "remove"])
@pytest.mark.parametrize("kind", ["storage", "wrapped", "scientific"])
async def test_collection_definition_refusal_keeps_context_not_paths(auth_client, monkeypatch, caplog, operation, kind):
    caplog.set_level(logging.WARNING)
    _, experiment_id, files = await _project_experiment_with_two_sources(auth_client)
    private_path = "/private/operator-science/collection.json"
    reason = "Scientific collection sample identities do not match the selected files"
    if kind == "storage":
        error = PermissionError(13, "denied", private_path)
    elif kind == "wrapped":
        try:
            raise PermissionError(13, "denied", private_path)
        except OSError as cause:
            try:
                raise ValueError(str(cause)) from cause
            except ValueError as wrapped:
                error = wrapped
    else:
        error = ValueError(reason)
    if operation == "remove":
        action = Mock(side_effect=error)
        monkeypatch.setattr(routes, "remove_collection_definition", action)
        response = await auth_client.delete(f"/api/v1/experiments/{experiment_id}/collection-definition")
    else:
        action = AsyncMock(side_effect=error)
        monkeypatch.setattr(routes, "load_project_dataset", action)
        path = f"/api/v1/experiments/{experiment_id}/collection-definition"
        payload = _definition_upload(_definition([str(item["file_path"]) for item in files]))
        response = await (
            auth_client.post(path + "/preview", files=payload)
            if operation == "preview"
            else auth_client.put(path, files=payload)
        )
    action.assert_called_once()
    assert response.status_code == (503 if kind == "storage" else 422), response.text
    assert private_path not in response.text
    if kind == "scientific":
        assert reason in response.json()["detail"]
    else:
        assert "check storage access" in response.json()["detail"]
        assert private_path in caplog.text


@pytest.mark.asyncio
async def test_missing_legacy_absolute_source_does_not_expose_path(
    auth_client, test_session, test_user, tmp_path, caplog
):
    caplog.set_level(logging.WARNING)
    created = await auth_client.post("/api/v1/experiments", json={"name": "Missing source"})
    experiment_id = created.json()["id"]
    missing = tmp_path / "private-laboratory" / "missing.csv"
    test_session.add(ExperimentFile(experiment_id=experiment_id, file_path=str(missing), stage="raw", file_type="csv"))
    await test_session.commit()
    with pytest.raises(ValueError, match="Re-import the source") as error:
        await load_project_dataset(test_session, user_id=test_user.id, experiment_id=experiment_id)
    assert str(missing) not in str(error.value)
    assert str(missing) in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["preview", "save"])
async def test_source_deleted_between_collection_and_reader_checks(auth_client, monkeypatch, caplog, operation):
    from pathlib import Path

    caplog.set_level(logging.WARNING)
    _, experiment_id, files = await _project_experiment_with_two_sources(auth_client)
    original = ExperimentDatasetReader._load_file
    removed = []

    def remove_before_read(self, file_path, **kwargs):
        Path(file_path).unlink()
        removed.append(file_path)
        return original(self, file_path, **kwargs)

    monkeypatch.setattr(ExperimentDatasetReader, "_load_file", remove_before_read)
    path = f"/api/v1/experiments/{experiment_id}/collection-definition"
    payload = _definition_upload(_definition([str(item["file_path"]) for item in files]))
    response = await (
        auth_client.post(path + "/preview", files=payload)
        if operation == "preview"
        else auth_client.put(path, files=payload)
    )
    assert response.status_code == 503, response.text
    assert removed
    assert all(path not in response.text for path in removed)
    assert "check storage access" in response.json()["detail"]
    assert removed[0] in caplog.text
