"""
Centralized SpectroChemPy compatibility layer.

ALL application code should import SpectroChemPy through this module::

    from spectra_sherpa.app.lib.scp_compat import scp, NDDataset, Coord, HAS_SCP

This centralises version checks, graceful degradation when SCP is
unavailable, and future API migration paths.  No file outside this
module may ``import spectrochempy`` or ``from spectrochempy import ...``
directly — enforce with the CI check in ``tests/test_scp_import_rule.py``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class _NDDatasetMissing:
    """Sentinel type for NDDataset when SpectroChemPy is not installed.

    Using a class (rather than None) allows ``isinstance(x, NDDataset)``
    to always return False instead of raising ``TypeError``.
    """


class _CoordMissing:
    """Sentinel type for Coord when SpectroChemPy is not installed."""


class _ScpMissing:
    """Proxy for the ``scp`` module when SpectroChemPy is not installed.

    Any attribute access (e.g. ``scp.read(...)``) raises an ``ImportError``
    with the exact pip command needed, instead of the opaque
    ``AttributeError: 'NoneType' object has no attribute '...'`` that
    ``scp = None`` would produce.
    """

    def __getattr__(self, name: str) -> None:  # type: ignore[return]
        raise ImportError(
            f"spectrochempy.{name} requires SpectroChemPy. " "Install with: pip install spectra-sherpa[scp]"
        )


try:
    import spectrochempy as scp
    from spectrochempy import Coord, NDDataset

    HAS_SCP = True
except ImportError:
    scp = _ScpMissing()  # type: ignore[assignment]
    NDDataset = _NDDatasetMissing  # type: ignore[assignment,misc]
    Coord = _CoordMissing  # type: ignore[assignment,misc]
    HAS_SCP = False
    logger.warning("spectrochempy not available — spectral analysis features disabled")


def require_scp(feature: str = "This feature") -> None:
    """Raise a clear error when SCP is required but not installed.

    Call at the top of any code path that needs SpectroChemPy at runtime.
    """
    if not HAS_SCP:
        raise ImportError(f"{feature} requires SpectroChemPy. " f"Install with: pip install spectra-sherpa[scp]")


def _resolve_for_dedupe(path: Path) -> Path:
    """Resolve paths for stable deduplication without requiring existence."""
    try:
        return path.expanduser().resolve(strict=False)
    except Exception:
        return path.expanduser()


def get_scp_datadirs() -> list[Path]:
    """Return ordered SpectroChemPy datadirs to search.

    Priority:
    1. ``SCP_DATADIR`` environment variable (explicit override)
    2. ``scp.preferences.datadir`` (runtime default when SCP is installed)
    3. ``~/.spectrochempy/testdata`` fallback
    """
    candidate_dirs: list[Path] = []

    env_dir = os.getenv("SCP_DATADIR", "").strip()
    if env_dir:
        candidate_dirs.append(Path(env_dir))

    if HAS_SCP:
        try:
            candidate_dirs.append(Path(scp.preferences.datadir))  # type: ignore[union-attr]
        except Exception:
            logger.debug("Could not read scp.preferences.datadir", exc_info=True)

    from spectra_sherpa._paths import _safe_home

    home = _safe_home()
    if home is not None:
        candidate_dirs.append(home / ".spectrochempy" / "testdata")

    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidate_dirs:
        resolved = _resolve_for_dedupe(candidate)
        if resolved in seen:
            continue
        seen.add(resolved)
        deduped.append(candidate.expanduser())

    return deduped


def resolve_scp_path(relative_path: str) -> Path | None:
    """Resolve an SCP-relative path against all known datadirs."""
    rel = Path(relative_path)
    for datadir in get_scp_datadirs():
        candidate = datadir / rel
        if candidate.exists():
            return candidate
    return None


def is_scp_testdata_file(path: Path) -> bool:
    """Return True when *path* looks like a valid SCP example data artifact."""
    suffix = path.suffix.lower()
    if suffix in {
        ".csv",
        ".jdx",
        ".dx",
        ".spc",
        ".spa",
        ".spg",
        ".srs",
        ".wdf",
        ".txt",
        ".mat",
        ".asc",
        ".dat",
        ".opus",
        ".0",
    }:
        return True
    if suffix.lstrip(".").isdigit():
        return True
    return not suffix and path.name.isdigit()


def scp_testdata_looks_complete(datadir: Path) -> bool:
    """Heuristic completeness check for a SpectroChemPy testdata root."""
    if not datadir.exists():
        return False

    required_dirs = ("irdata", "ramandata", "nmrdata")
    if any(not (datadir / name).is_dir() for name in required_dirs):
        return False

    visible_dirs = [item for item in datadir.iterdir() if item.is_dir() and not item.name.startswith(".")]
    if len(visible_dirs) < 5:
        return False

    recursive_files = 0
    for path in datadir.rglob("*"):
        if path.name.startswith(".") or not path.is_file():
            continue
        if is_scp_testdata_file(path):
            recursive_files += 1
            if recursive_files >= 25:
                break
    if recursive_files < 25:
        return False

    required_anchors = (
        datadir / "irdata" / "nh4y-activation.spg",
        datadir / "ramandata" / "wire",
        datadir / "nmrdata" / "bruker" / "tests" / "nmr" / "topspin_1d" / "1",
    )
    return all(path.exists() for path in required_anchors)


def get_preferred_scp_datadir() -> Path | None:
    """Return the best available SCP datadir for listing/import operations."""
    fallback: Path | None = None
    for datadir in get_scp_datadirs():
        if not datadir.exists():
            continue
        fallback = datadir
        if scp_testdata_looks_complete(datadir):
            return datadir
    return fallback


def download_testdata() -> None:
    """Download SpectroChemPy test data to ``scp.preferences.datadir``.

    SCP 0.8.x moved the download helper to
    ``spectrochempy.application.testdata.download_full_testdata_directory``.
    """
    require_scp("SpectroChemPy test data download")
    from pathlib import Path

    datadir = Path(scp.preferences.datadir)  # type: ignore[union-attr]
    datadir.mkdir(parents=True, exist_ok=True)

    try:
        from spectrochempy.application.testdata import (
            download_full_testdata_directory,
        )
    except ImportError as exc:
        raise RuntimeError(
            "SpectroChemPy is installed, but download_full_testdata_directory() "
            "is unavailable. Check your spectrochempy version (>=0.8.1 required)."
        ) from exc

    download_full_testdata_directory(datadir)


__all__ = [
    "scp",
    "NDDataset",
    "Coord",
    "HAS_SCP",
    "require_scp",
    "get_scp_datadirs",
    "get_preferred_scp_datadir",
    "is_scp_testdata_file",
    "resolve_scp_path",
    "scp_testdata_looks_complete",
    "download_testdata",
]


# ---------------------------------------------------------------------------
# NDDataset ↔ SherpaDataset adapters live in adapters/scp_adapter.py
# Legacy re-exports for backward compatibility.
# ---------------------------------------------------------------------------


def from_nddataset(ds: "NDDataset") -> "SherpaDataset":  # type: ignore[name-defined]  # noqa: F821
    """Convert NDDataset to SherpaDataset.  Delegates to adapters.scp_adapter."""
    from spectra_sherpa.app.lib.adapters.scp_adapter import from_nddataset as _from_nddataset

    return _from_nddataset(ds)


def to_nddataset(ds: "SherpaDataset") -> "NDDataset":  # type: ignore[name-defined]  # noqa: F821
    """Convert SherpaDataset to NDDataset.  Delegates to adapters.scp_adapter."""
    from spectra_sherpa.app.lib.adapters.scp_adapter import to_nddataset as _to_nddataset

    return _to_nddataset(ds)
