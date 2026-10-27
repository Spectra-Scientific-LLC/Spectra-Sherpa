"""Staged uploads and bundled references retain advice without private paths."""

import logging
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from spectra_sherpa.app.api.v1.routes import builder

PRIVATE_PATH = "/private/operator-data/lavender.zip"


def _failure(kind):
    if kind == "validation":
        return ValueError("Lavender reference archive source bytes do not match their manifest")
    if kind == "wrapped":
        try:
            raise PermissionError(13, "Cannot read", PRIVATE_PATH)
        except OSError as cause:
            try:
                raise ValueError(str(cause)) from cause
            except ValueError as exc:
                return exc
    return (FileNotFoundError if kind == "missing" else PermissionError)(13, "Cannot read", PRIVATE_PATH)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["storage", "wrapped", "validation"])
async def test_staged_inspection_storage_privacy(tmp_path, monkeypatch, caplog, kind):
    from spectra_sherpa import io

    caplog.set_level(logging.WARNING)
    path = tmp_path / "source.mat"
    path.write_bytes(b"staged bytes")
    error = _failure(kind)
    monkeypatch.setattr(io, "ingest", Mock(side_effect=error))
    with pytest.raises(HTTPException) as refused:
        await builder._staged_upload_response("test-stage", path)
    assert refused.value.status_code == (503 if kind == "storage" else 400)
    assert PRIVATE_PATH not in refused.value.detail
    if kind == "validation":
        assert str(error) in refused.value.detail
    else:
        assert "check storage access" in refused.value.detail
        assert PRIVATE_PATH in caplog.text


@pytest.mark.parametrize("kind", ["storage", "missing", "wrapped", "validation"])
def test_lavender_preview_storage_privacy(tmp_path, monkeypatch, caplog, kind):
    from spectra_sherpa.app.services import experiments

    caplog.set_level(logging.WARNING)
    path = tmp_path / "lavender.zip"
    path.write_bytes(b"mounted archive")
    monkeypatch.setattr(experiments, "_builtin_lavender_archive_path", lambda: path)
    error = _failure(kind)
    monkeypatch.setattr(builder.zipfile, "ZipFile", Mock(side_effect=error))
    with pytest.raises(HTTPException) as refused:
        builder._builtin_reference_dataset_as_sherpa(experiments._BUILTIN_LAVENDER_NAME)
    assert refused.value.status_code == (503 if kind == "storage" else 400)
    assert PRIVATE_PATH not in refused.value.detail
    if kind == "validation":
        assert str(error) == refused.value.detail
    else:
        assert "archive installation" in refused.value.detail
        assert PRIVATE_PATH in caplog.text
