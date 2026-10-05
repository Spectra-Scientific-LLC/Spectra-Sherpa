"""Application projection of the sole native ingestion capability authority."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from spectra_sherpa.ingestion_errors import FormatUnavailableError
from spectra_sherpa.ingestion_formats import (
    pending_extensions,
    pending_format_capabilities,
    pending_format_for,
)
from spectra_sherpa.io.registry import builtin_registry

BASE_EXTENSIONS: tuple[str, ...] = tuple(
    extension for plugin in builtin_registry.plugins for extension in plugin.extensions
)

# The source node admits the full frozen native registry. Multi-asset formats
# remain explicit because the node contract carries an exact ``asset_id``.
CANONICAL_FILE_LOAD_EXTENSIONS: tuple[str, ...] = tuple(
    sorted(
        {
            extension
            for plugin in builtin_registry.plugins
            for extension in (*plugin.extensions, *getattr(plugin, "extension_examples", ()))
        }
    )
)

BASE_FORMATS: tuple[dict[str, Any], ...] = tuple(
    {
        "key": item["key"],
        "name": item["name"],
        "extensions": item["extensions"],
        "description": item["description"],
        "available": True,
    }
    for item in builtin_registry.capability_report()["formats"]
)


def ensure_reader_available(filename_or_ext: str | Path) -> None:
    """Fail early when a recognized source family lacks a native reader."""
    pending = pending_format_for(filename_or_ext)
    if pending is not None:
        raise FormatUnavailableError(pending.unsupported_reason)


def client_data_formats() -> dict[str, Any]:
    """Return the client-safe projection of the sole ingestion authority."""
    report = builtin_registry.capability_report()
    formats: list[dict[str, Any]] = [dict(item) for item in report["formats"]]
    formats.extend(pending_format_capabilities())
    return {
        "baseExtensions": list(BASE_EXTENSIONS),
        "canonicalFileLoadExtensions": list(CANONICAL_FILE_LOAD_EXTENSIONS),
        "knownUnsupportedExtensions": list(pending_extensions()),
        "acceptedExtensions": list(report["acceptedExtensions"]),
        "acceptedFilenamePatterns": list(report["acceptedFilenamePatterns"]),
        "formats": formats,
    }
