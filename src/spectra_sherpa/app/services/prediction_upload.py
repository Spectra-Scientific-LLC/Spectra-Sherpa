"""Bounded inference-only uploads; never register them as training datasets."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

from fastapi import HTTPException, Request
from starlette.datastructures import UploadFile

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.services.run_output_retention import _storage_lock


def _validate_uploads(uploads: list[tuple[str, bytes]]) -> None:
    if not 1 <= len(uploads) <= settings.prediction_upload_max_files:
        raise HTTPException(422, "Select a bounded, nonempty batch of prediction files")
    names: set[str] = set()
    for name, data in uploads:
        if (
            not name
            or len(name) > 200
            or name.startswith(".")
            or any(character in name for character in ("/", "\\", "\x00"))
            or name in names
        ):
            raise HTTPException(422, "Prediction filenames must be unique plain filenames")
        if not data:
            raise HTTPException(422, "Empty prediction files are not accepted")
        names.add(name)
    if sum(len(data) for _, data in uploads) > settings.prediction_upload_max_request_bytes:
        raise HTTPException(413, "Prediction batch exceeds the configured request limit")


async def read_prediction_files(request: Request) -> list[tuple[str, bytes]]:
    """Called only after authentication, entitlement and model admission."""
    body = bytearray()
    try:
        async with asyncio.timeout(settings.prediction_upload_timeout_seconds):
            async for chunk in request.stream():
                if len(body) + len(chunk) > settings.prediction_upload_max_request_bytes:
                    raise HTTPException(413, "Prediction batch exceeds the configured request limit")
                body.extend(chunk)
    except TimeoutError as exc:
        raise HTTPException(408, "Prediction upload timed out; retry with a smaller batch") from exc

    async def receive():
        return {"type": "http.request", "body": bytes(body), "more_body": False}

    bounded = Request(request.scope, receive)
    result: list[tuple[str, bytes]] = []
    async with bounded.form(max_files=settings.prediction_upload_max_files, max_fields=0) as form:
        for key, upload in form.multi_items():
            if key != "files" or not isinstance(upload, UploadFile):
                raise HTTPException(422, "Only prediction files are accepted")
            name = upload.filename or ""
            data = await upload.read()
            result.append((name, data))
    _validate_uploads(result)
    return result


def persist_prediction_files(user_id: int, uploads: list[tuple[str, bytes]]) -> tuple[list[Path], dict]:
    if user_id <= 0:
        raise ValueError("Prediction input owner is invalid")
    _validate_uploads(uploads)
    root = settings.data_dir / "prediction-inputs-v1"
    directory = root / str(user_id)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or directory.is_symlink():
        raise ValueError("Prediction input storage must not use symlinks")
    with _storage_lock(directory):
        used = entries = 0
        for batch in directory.iterdir():
            entries += 1
            if entries > 1024:
                raise ValueError("Prediction input batch limit reached")
            if batch.is_symlink():
                raise ValueError("Prediction input storage must not use symlinks")
            if batch.is_dir():
                for path in batch.iterdir():
                    if path.is_symlink():
                        raise ValueError("Prediction input storage must not use symlinks")
                    used += path.stat().st_size
        incoming = sum(len(data) for _, data in uploads)
        if used + incoming > settings.prediction_upload_max_user_bytes:
            raise ValueError("Prediction input storage exceeds the configured account limit")
        if shutil.disk_usage(directory).free < incoming + 128 * 1024 * 1024:
            raise ValueError("Insufficient disk space for prediction input")
        target = Path(tempfile.mkdtemp(prefix="batch-", dir=directory))
        try:
            files, receipts = [], []
            for name, data in uploads:
                path = target / name
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                files.append(path)
                receipts.append({"name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
            return files, {"private_prediction_input": True, "inputs": receipts}
        except BaseException:
            shutil.rmtree(target)
            raise


def verify_prediction_file(user_id: int, path: Path, metadata: dict) -> None:
    """Recheck owned custody and exact accepted bytes before native ingestion."""
    root = settings.data_dir / "prediction-inputs-v1" / str(user_id)
    if path.parent.parent != root or not path.parent.name.startswith("batch-"):
        raise ValueError("Prediction input is outside its owner's custody")
    if any(item.is_symlink() for item in (root.parent, root, path.parent, path)):
        raise ValueError("Prediction input storage must not use symlinks")
    receipts = metadata.get("inputs", [])
    matches = [item for item in receipts if isinstance(item, dict) and item.get("name") == path.name]
    if len(matches) != 1:
        raise ValueError("Prediction input has no unique acceptance receipt")
    receipt = matches[0]
    size = path.stat().st_size
    if size != receipt.get("size") or size > settings.prediction_upload_max_request_bytes:
        raise ValueError("Prediction input no longer matches its accepted size")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != receipt.get("sha256"):
        raise ValueError("Prediction input no longer matches its accepted bytes")
