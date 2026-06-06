"""Data-format capability metadata shared by backend and frontend."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from spectra_sherpa.app.lib.scp_compat import HAS_SCP, require_scp

INSTALL_SCP_COMMAND = "pip install spectra-sherpa[scp]"
THERMO_CONTAINER_EXPORT_MESSAGE = (
    "Thermo OMNIC Paradigm/OMNICxi container files (.srsx, .session, .map, .mapx) "
    "are not directly readable yet. Export spectra as .spa or .spg, or export legacy "
    "OMNIC time series as .srs, then upload those files."
)

BASE_EXTENSIONS: tuple[str, ...] = (
    ".csv",
    ".jdx",
    ".dx",
    ".npy",
    ".npz",
    ".mat",
)

SCP_EXTENSIONS: tuple[str, ...] = (
    ".spc",
    ".spa",
    ".spg",
    ".srs",
    ".wdf",
    ".opus",
    ".txt",
    ".dat",
)

KNOWN_UNSUPPORTED_EXTENSIONS: tuple[str, ...] = (
    ".srsx",
    ".session",
    ".map",
    ".mapx",
)

BASE_FORMATS: tuple[dict[str, Any], ...] = (
    {
        "key": "csv",
        "name": "CSV",
        "extensions": [".csv"],
        "description": "Delimited numeric spectra or feature tables",
        "requiresScp": False,
    },
    {
        "key": "jcamp",
        "name": "JCAMP-DX",
        "extensions": [".jdx", ".dx"],
        "description": "Open spectroscopy interchange format",
        "requiresScp": False,
    },
    {
        "key": "numpy",
        "name": "NumPy",
        "extensions": [".npy", ".npz"],
        "description": "Numeric arrays and explicit X payloads",
        "requiresScp": False,
    },
    {
        "key": "matlab",
        "name": "MAT",
        "extensions": [".mat"],
        "description": "MATLAB numeric arrays",
        "requiresScp": False,
    },
)

SCP_FORMATS: tuple[dict[str, Any], ...] = (
    {
        "key": "omnic",
        "name": "OMNIC / OMNICxi spectra",
        "extensions": [".spa", ".spg", ".srs"],
        "description": "Thermo OMNIC single spectra, groups, and legacy time series",
        "requiresScp": True,
    },
    {
        "key": "spc",
        "name": "SPC",
        "extensions": [".spc"],
        "description": "Galactic SPC files",
        "requiresScp": True,
    },
    {
        "key": "wdf",
        "name": "WDF",
        "extensions": [".wdf"],
        "description": "Renishaw WiRE files",
        "requiresScp": True,
    },
    {
        "key": "opus",
        "name": "OPUS",
        "extensions": [".opus"],
        "description": "Bruker OPUS files",
        "requiresScp": True,
    },
    {
        "key": "text_vendor",
        "name": "Vendor text",
        "extensions": [".txt", ".dat"],
        "description": "Vendor text files handled by SpectroChemPy",
        "requiresScp": True,
    },
)

KNOWN_UNSUPPORTED_FORMATS: tuple[dict[str, Any], ...] = (
    {
        "key": "thermo_paradigm_timeseries",
        "name": "OMNIC Paradigm time series",
        "extensions": [".srsx"],
        "description": "Thermo OMNIC Paradigm time-series container",
        "requiresScp": False,
        "requiresExport": True,
        "unsupportedReason": THERMO_CONTAINER_EXPORT_MESSAGE,
    },
    {
        "key": "thermo_microscopy_session",
        "name": "OMNIC Paradigm microscopy session",
        "extensions": [".session"],
        "description": "Thermo OMNIC Paradigm microscopy session container",
        "requiresScp": False,
        "requiresExport": True,
        "unsupportedReason": THERMO_CONTAINER_EXPORT_MESSAGE,
    },
    {
        "key": "omnicxi_map",
        "name": "OMNICxi map",
        "extensions": [".map", ".mapx"],
        "description": "Thermo OMNICxi Raman map container",
        "requiresScp": False,
        "requiresExport": True,
        "unsupportedReason": THERMO_CONTAINER_EXPORT_MESSAGE,
    },
)


def normalized_extension(filename_or_ext: str | Path) -> str:
    """Return a normalized extension from a filename, path, or raw suffix."""
    value = str(filename_or_ext).strip()
    if not value:
        return ""
    if value.startswith(".") and "/" not in value and "\\" not in value:
        ext = value
    else:
        ext = Path(value).suffix
    return ext.lower()


def requires_scp_for_extension(filename_or_ext: str | Path) -> bool:
    """Return True when the extension is supported only through SpectroChemPy."""
    ext = normalized_extension(filename_or_ext)
    return ext in SCP_EXTENSIONS or ext.lstrip(".").isdigit()


def ensure_reader_available(filename_or_ext: str | Path) -> None:
    """Fail early if a selected file needs the optional SpectroChemPy extra."""
    ext = normalized_extension(filename_or_ext)
    if ext in KNOWN_UNSUPPORTED_EXTENSIONS:
        raise ValueError(THERMO_CONTAINER_EXPORT_MESSAGE)
    if requires_scp_for_extension(filename_or_ext):
        require_scp("Vendor spectral file reading")


def client_data_formats() -> dict[str, Any]:
    """Return client-safe data-format capability metadata."""
    formats: list[dict[str, Any]] = []
    for fmt in (*BASE_FORMATS, *SCP_FORMATS):
        requires_scp = bool(fmt["requiresScp"])
        formats.append(
            {
                **fmt,
                "available": (not requires_scp) or HAS_SCP,
            }
        )
    for fmt in KNOWN_UNSUPPORTED_FORMATS:
        formats.append({**fmt, "available": False})

    accepted = list(BASE_EXTENSIONS)
    if HAS_SCP:
        accepted.extend(SCP_EXTENSIONS)

    return {
        "hasScp": HAS_SCP,
        "installScpCommand": INSTALL_SCP_COMMAND,
        "baseExtensions": list(BASE_EXTENSIONS),
        "scpExtensions": list(SCP_EXTENSIONS),
        "knownUnsupportedExtensions": list(KNOWN_UNSUPPORTED_EXTENSIONS),
        "acceptedExtensions": accepted,
        "formats": formats,
    }
