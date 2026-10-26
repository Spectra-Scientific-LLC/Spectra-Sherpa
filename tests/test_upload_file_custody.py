"""An upload retry must never overwrite or remove a retained source."""

from io import BytesIO

import pytest
from fastapi import UploadFile

from spectra_sherpa.app.services.file_storage import FileValidationError, save_upload_file


@pytest.mark.anyio
async def test_duplicate_upload_preserves_existing_bytes(tmp_path):
    target = tmp_path / "Process_data.nc"
    target.write_bytes(b"original scientific source")
    upload = UploadFile(filename=target.name, file=BytesIO(b"replacement"))
    with pytest.raises(FileValidationError, match="already exists"):
        await save_upload_file(upload, tmp_path, 1)
    assert target.read_bytes() == b"original scientific source"
    assert upload.file.closed


@pytest.mark.anyio
async def test_failed_new_upload_removes_only_its_partial_file(tmp_path):
    upload = UploadFile(filename="new.nc", file=BytesIO(b"x" * (1024 * 1024 + 1)))
    with pytest.raises(FileValidationError, match="size limit"):
        await save_upload_file(upload, tmp_path, 1)
    assert not (tmp_path / "new.nc").exists()
    assert upload.file.closed


@pytest.mark.anyio
async def test_failed_commit_returns_sources_to_staging(auth_client, monkeypatch, test_session, test_user):
    from spectra_sherpa.app.api.v1.routes import builder

    stage = await auth_client.post(
        "/api/v1/builder/upload/stage",
        files={
            "file": ("measurements.csv", b"wavelength,a\n400,1\n500,2\n600,3\n", "text/csv"),
        },
    )
    assert stage.status_code == 200, stage.text
    sid = stage.json()["staging_id"]
    experiment = (await auth_client.post("/api/v1/experiments", json={"name": "Retry upload"})).json()

    async def reject(*args, **kwargs):
        from fastapi import HTTPException

        raise HTTPException(409, "Simulated admission failure")

    with monkeypatch.context() as patch:
        patch.setattr(builder, "add_experiment_file", reject)
        refused = await auth_client.post(
            "/api/v1/builder/upload/commit",
            json={
                "experiment_id": experiment["id"],
                "files": [{"staging_id": sid}],
            },
        )
    assert refused.status_code == 409, refused.text
    # This fixture reuses the same ORM user across requests; real requests reload it.
    await test_session.refresh(test_user)
    retry = await auth_client.post(
        "/api/v1/builder/upload/commit",
        json={
            "experiment_id": experiment["id"],
            "files": [{"staging_id": sid}],
        },
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["imported"] == 1
