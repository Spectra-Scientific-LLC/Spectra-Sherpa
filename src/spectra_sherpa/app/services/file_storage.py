from __future__ import annotations

from pathlib import Path
from typing import Iterable

from fastapi import UploadFile
from werkzeug.utils import secure_filename

from spectra_sherpa.app.core.config import settings


class FileValidationError(ValueError):
    pass


def sanitize_filename(filename: str) -> str:
    if not filename:
        raise FileValidationError("Filename is required")
    if "\x00" in filename:
        raise FileValidationError("Invalid filename")
    if ".." in filename or "/" in filename or "\\" in filename:
        raise FileValidationError("Invalid filename")

    sanitized = secure_filename(filename)
    if not sanitized:
        raise FileValidationError("Invalid filename")
    return sanitized


def validate_extension(filename: str, allowed_extensions: Iterable[str] | None = None) -> str:
    extension = Path(filename).suffix.lower()
    allowed = {ext.lower() for ext in (allowed_extensions or settings.allowed_extensions)}
    if extension not in allowed:
        raise FileValidationError("Unsupported file type")
    return extension


def resolve_target_path(destination_dir: Path, filename: str) -> Path:
    destination_dir = destination_dir.resolve()
    target_path = (destination_dir / filename).resolve()
    if not target_path.is_relative_to(destination_dir):
        raise FileValidationError("Invalid destination path")
    return target_path


def max_size_bytes(max_file_size_mb: int) -> int:
    if max_file_size_mb <= 0:
        raise FileValidationError("Invalid max file size")
    return max_file_size_mb * 1024 * 1024


async def save_upload_file(
    upload: UploadFile,
    destination_dir: Path,
    max_file_size_mb: int,
    allowed_extensions: Iterable[str] | None = None,
) -> Path:
    filename = sanitize_filename(upload.filename or "")
    validate_extension(filename, allowed_extensions)

    destination_dir.mkdir(parents=True, exist_ok=True)
    target_path = resolve_target_path(destination_dir, filename)

    size_limit = max_size_bytes(max_file_size_mb)
    bytes_written = 0
    chunk_size = 1024 * 1024

    try:
        with target_path.open("wb") as buffer:
            while True:
                chunk = await upload.read(chunk_size)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > size_limit:
                    raise FileValidationError("File exceeds size limit")
                buffer.write(chunk)
    except FileValidationError:
        if target_path.exists():
            target_path.unlink()
        raise
    finally:
        await upload.close()

    return target_path
