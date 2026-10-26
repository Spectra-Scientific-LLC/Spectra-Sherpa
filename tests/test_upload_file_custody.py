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
