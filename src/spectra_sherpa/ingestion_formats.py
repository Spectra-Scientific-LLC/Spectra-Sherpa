"""Single authority for recognized file families awaiting native readers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

THERMO_CONTAINER_EXPORT_MESSAGE = (
    "Thermo OMNIC Paradigm/OMNICxi container files (.srsx, .session, .map, .mapx) "
    "are not directly readable yet. Export spectra as .spa or .spg, or export legacy "
    "OMNIC time series as .srs, then upload those files."
)


def normalized_extension(filename_or_ext: str | Path) -> str:
    value = str(filename_or_ext).strip()
    if not value:
        return ""
    if value.startswith(".") and "/" not in value and "\\" not in value:
        extension = value
    else:
        extension = Path(value).suffix
    return extension.lower()


def matches_filename(
    filename_or_ext: str | Path,
    *,
    extensions: tuple[str, ...],
    filename_patterns: tuple[str, ...] = (),
) -> bool:
    """Match one filename using the closed ingestion filename vocabulary."""
    extension = normalized_extension(filename_or_ext)
    if extension in extensions:
        return True
    return "numeric-extension" in filename_patterns and extension.lstrip(".").isdigit()


@dataclass(frozen=True)
class PendingFormat:
    key: str
    name: str
    extensions: tuple[str, ...]
    description: str
    unsupported_reason: str
    filename_patterns: tuple[str, ...] = ()
    extension_examples: tuple[str, ...] = ()
    requires_export: bool = False

    def matches(self, filename_or_ext: str | Path) -> bool:
        return matches_filename(
            filename_or_ext,
            extensions=self.extensions,
            filename_patterns=self.filename_patterns,
        )

    def capability(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "key": self.key,
            "name": self.name,
            "extensions": list(self.extensions),
            "description": self.description,
            "available": False,
            "unsupportedReason": self.unsupported_reason,
        }
        if self.filename_patterns:
            payload["filenamePatterns"] = list(self.filename_patterns)
        if self.extension_examples:
            payload["extensionExamples"] = list(self.extension_examples)
        if self.requires_export:
            payload["requiresExport"] = True
        return payload


PENDING_FORMATS: tuple[PendingFormat, ...] = (
    PendingFormat(
        "thermo_paradigm_timeseries",
        "OMNIC Paradigm time series",
        (".srsx",),
        "Thermo OMNIC Paradigm time-series container",
        THERMO_CONTAINER_EXPORT_MESSAGE,
        requires_export=True,
    ),
    PendingFormat(
        "thermo_microscopy_session",
        "OMNIC Paradigm microscopy session",
        (".session",),
        "Thermo OMNIC Paradigm microscopy session container",
        THERMO_CONTAINER_EXPORT_MESSAGE,
        requires_export=True,
    ),
    PendingFormat(
        "omnicxi_map",
        "OMNICxi map",
        (".map", ".mapx"),
        "Thermo OMNICxi Raman map container",
        THERMO_CONTAINER_EXPORT_MESSAGE,
        requires_export=True,
    ),
)


def pending_format_for(filename_or_ext: str | Path) -> PendingFormat | None:
    matches = [item for item in PENDING_FORMATS if item.matches(filename_or_ext)]
    if len(matches) > 1:
        names = ", ".join(item.key for item in matches)
        raise RuntimeError(f"Pending format authority is ambiguous for {filename_or_ext!s}: {names}")
    return matches[0] if matches else None


def pending_format_capabilities() -> tuple[dict[str, Any], ...]:
    return tuple(item.capability() for item in PENDING_FORMATS)


def pending_extensions() -> tuple[str, ...]:
    extensions = {extension for item in PENDING_FORMATS for extension in item.extensions}
    extensions.update(example for item in PENDING_FORMATS for example in item.extension_examples)
    return tuple(sorted(extensions))
