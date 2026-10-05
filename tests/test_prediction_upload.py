"""Bounded private inputs remain owned prediction custody, not training data."""

import hashlib
import os
from dataclasses import replace

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from spectra_sherpa.app.services import prediction_upload as service


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "settings", replace(service.settings, data_dir=tmp_path))
    return tmp_path


@pytest.fixture
def client(storage):
    app = FastAPI()

    @app.post("/inputs")
    async def inputs(request: Request):
        uploads = await service.read_prediction_files(request)
        _, receipts = service.persist_prediction_files(1, uploads)
        return receipts

    return TestClient(app)


def test_receipts_preserve_exact_bytes_and_account_custody(client, storage):
    content = b"x,y\n1,2\n"
    response = client.post("/inputs", files=[("files", ("spectrum.csv", content))])
    assert response.status_code == 200
    receipt = response.json()
    assert receipt["inputs"] == [
        {"name": "spectrum.csv", "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
    ]
    paths = list((storage / "prediction-inputs-v1" / "1").glob("batch-*/*"))
    assert len(paths) == 1 and paths[0].read_bytes() == content
    if os.name != "nt":  # Windows uses the containing profile ACL.
        assert paths[0].stat().st_mode & 0o777 == 0o600
    assert not (storage / "experiments").exists()


@pytest.mark.parametrize("name", ["../spectrum.csv", ".hidden", "folder/file.csv", "folder\\file.csv"])
def test_reject_unsafe_names_before_writing(storage, name):
    with pytest.raises(HTTPException):
        service.persist_prediction_files(1, [(name, b"123")])
    assert not list(storage.iterdir())


def test_duplicate_names_and_empty_files_refused(client):
    assert client.post("/inputs", files=[("files", ("a.csv", b"1")), ("files", ("a.csv", b"2"))]).status_code == 422
    assert client.post("/inputs", files=[("files", ("a.csv", b""))]).status_code == 422


def test_stream_limit_not_dependent_on_content_length(client, monkeypatch):
    monkeypatch.setattr(service, "settings", replace(service.settings, prediction_upload_max_request_bytes=64))
    assert client.post("/inputs", content=b"x" * 65).status_code == 413


def test_per_account_quota_and_isolation(storage, monkeypatch):
    monkeypatch.setattr(service, "settings", replace(service.settings, prediction_upload_max_user_bytes=4))
    service.persist_prediction_files(1, [("a.csv", b"1234")])
    with pytest.raises(ValueError, match="account limit"):
        service.persist_prediction_files(1, [("b.csv", b"5")])
    files, _ = service.persist_prediction_files(2, [("a.csv", b"5678")])
    assert files[0].read_bytes() == b"5678"


def test_file_count_is_bounded(client):
    files = [("files", (f"{index}.csv", b"1")) for index in range(17)]
    assert client.post("/inputs", files=files).status_code == 400


def test_receipt_rechecked_before_execution(storage):
    files, receipts = service.persist_prediction_files(1, [("a.csv", b"1234")])
    service.verify_prediction_file(1, files[0], receipts)
    with pytest.raises(ValueError, match="owner"):
        service.verify_prediction_file(2, files[0], receipts)
    files[0].write_bytes(b"5678")
    with pytest.raises(ValueError, match="accepted bytes"):
        service.verify_prediction_file(1, files[0], receipts)


@pytest.mark.asyncio
async def test_paid_prediction_does_not_grant_other_model_mutations(test_session, test_user, monkeypatch):
    from unittest.mock import AsyncMock

    from spectra_sherpa.app.api import deps
    from spectra_sherpa.app.api.v1.routes.models import ModelUpdateRequest, update_model
    from spectra_sherpa.app.contracts import prediction_access

    def blocked(capability):
        raise HTTPException(403, "Demo model mutation disabled")

    admission = AsyncMock()
    monkeypatch.setattr(deps, "check_demo_capability", blocked)
    monkeypatch.setattr(prediction_access, "require_private_prediction", admission)
    with pytest.raises(HTTPException) as error:
        await update_model(
            "unknown",
            ModelUpdateRequest(display_name="changed", is_deploy_ready=True),
            session=test_session,
            current_user=test_user,
        )
    assert error.value.status_code == 403
    admission.assert_not_awaited()
    with pytest.raises(HTTPException) as error:
        await update_model(
            "unknown",
            ModelUpdateRequest(is_deploy_ready=True),
            session=test_session,
            current_user=test_user,
        )
    assert error.value.status_code == 404
    admission.assert_awaited_once_with(test_session, test_user.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["entitlement", "ownership", "revoked_during_upload"])
async def test_upload_route_admits_owner_and_entitlement_before_persisting(test_user, monkeypatch, failure):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from spectra_sherpa.app.api.v1.routes import runs
    from spectra_sherpa.app.contracts import prediction_access

    denied = HTTPException(403, "No active entitlement")
    admission = AsyncMock(side_effect=[denied] if failure == "entitlement" else [None, denied])
    artifact = None if failure == "ownership" else SimpleNamespace(workflow_id=1, name="owned model")
    session = SimpleNamespace(scalar=AsyncMock(return_value=artifact))
    reader = AsyncMock(return_value=[("a.csv", b"1")])
    persist = Mock(side_effect=AssertionError("unadmitted bytes persisted"))
    monkeypatch.setattr(prediction_access, "require_private_prediction", admission)
    monkeypatch.setattr(runs, "resolve_deployment_binding", AsyncMock())
    monkeypatch.setattr(service, "read_prediction_files", reader)
    monkeypatch.setattr(service, "persist_prediction_files", persist)

    with pytest.raises(HTTPException) as error:
        await runs.batch_run_uploaded_files("owned", Mock(), session=session, current_user=test_user)
    assert error.value.status_code == (404 if failure == "ownership" else 403)
    persist.assert_not_called()
    if failure == "revoked_during_upload":
        reader.assert_awaited_once()
        assert admission.await_count == 2
    else:
        reader.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_route_preserves_receipts_and_starts_durable_run(test_user, monkeypatch, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock

    from spectra_sherpa.app.api.v1.routes import runs
    from spectra_sherpa.app.contracts import prediction_access
    from spectra_sherpa.app.schemas.deploy import BatchPredictResponse

    artifact = SimpleNamespace(artifact_uid="owned", name="PLS-DA", workflow_id=7)
    binding = SimpleNamespace(artifact=artifact, workflow=SimpleNamespace(id=7))
    admission = AsyncMock()
    resolve = AsyncMock(return_value=binding)
    uploads = [("sample.csv", b"x,y\n1,2\n")]
    files = [tmp_path / "sample.csv"]
    receipts = {"inputs": [{"name": "sample.csv", "sha256": "f" * 64}]}
    reader = AsyncMock(return_value=uploads)
    persist = Mock(return_value=(files, receipts))
    started = BatchPredictResponse(job_id=3, run_id=4, message="started")
    start = AsyncMock(return_value=started)
    session = SimpleNamespace()
    monkeypatch.setattr(prediction_access, "require_private_prediction", admission)
    monkeypatch.setattr(runs, "_resolve_owned_deployment_binding", resolve)
    monkeypatch.setattr(runs, "_start_file_batch", start)
    monkeypatch.setattr(service, "read_prediction_files", reader)
    monkeypatch.setattr(service, "persist_prediction_files", persist)

    response = await runs.batch_run_uploaded_files("owned", Mock(), session=session, current_user=test_user)

    assert response == started
    assert admission.await_count == 2
    resolve.assert_awaited_once()
    persist.assert_called_once_with(test_user.id, uploads)
    payload = start.await_args.args[0]
    assert payload.artifact_uid == "owned"
    assert payload.folder_path == str(tmp_path)
    start.assert_awaited_once_with(
        payload,
        binding,
        files,
        session,
        test_user,
        input_metadata=receipts,
    )
