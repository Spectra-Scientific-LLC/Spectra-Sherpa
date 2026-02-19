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


try:
    import spectrochempy as scp
    from spectrochempy import Coord, NDDataset

    HAS_SCP = True
except ImportError:
    scp = None  # type: ignore[assignment]
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

    candidate_dirs.append(Path.home() / ".spectrochempy" / "testdata")

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
    "resolve_scp_path",
    "download_testdata",
    "from_nddataset",
    "to_nddataset",
]


# ---------------------------------------------------------------------------
# NDDataset ↔ AnalysisDataset adapters
# ---------------------------------------------------------------------------


def from_nddataset(ds: "NDDataset") -> "AnalysisDataset":  # type: ignore[name-defined]  # noqa: F821
    """Lossless conversion from SCP NDDataset to AnalysisDataset.

    Safe to call regardless of HAS_SCP — if you have an NDDataset in hand
    SCP must already be installed.
    """
    import numpy as np

    from spectra_sherpa.app.lib.analysis_dataset import AnalysisDataset, AxisInfo

    x_axis = None
    try:
        xc = ds.x
        if xc is not None:
            x_axis = AxisInfo(
                values=np.asarray(xc.data),
                units=str(xc.units) if hasattr(xc, "units") and xc.units else None,
                title=str(xc.title) if hasattr(xc, "title") and xc.title else None,
                labels=(list(xc.labels) if hasattr(xc, "labels") and xc.labels is not None else None),
            )
    except (KeyError, AttributeError):
        pass

    y_axis = None
    try:
        yc = ds.y
        if yc is not None:
            y_axis = AxisInfo(
                values=np.asarray(yc.data),
                units=str(yc.units) if hasattr(yc, "units") and yc.units else None,
                title=str(yc.title) if hasattr(yc, "title") and yc.title else None,
                labels=(list(yc.labels) if hasattr(yc, "labels") and yc.labels is not None else None),
            )
    except (KeyError, AttributeError):
        pass

    meta = dict(ds.meta) if hasattr(ds, "meta") and ds.meta else {}
    provenance = meta.pop("processing_history", [])

    return AnalysisDataset(
        X=np.asarray(ds.data),
        x_axis=x_axis,
        y_axis=y_axis,
        meta=meta,
        provenance=provenance,
        backend="scp",
        title=str(ds.title) if hasattr(ds, "title") and ds.title else None,
        units=str(ds.units) if hasattr(ds, "units") and ds.units else None,
    )


def to_nddataset(ads: "AnalysisDataset") -> "NDDataset":  # type: ignore[name-defined]  # noqa: F821
    """Convert AnalysisDataset back to NDDataset.

    Raises:
        ImportError: If SpectroChemPy is not installed.
    """
    require_scp("to_nddataset()")

    ds = scp.NDDataset(ads.X)

    if ads.x_axis and ads.x_axis.values is not None:
        ds.x = Coord(ads.x_axis.values, title=ads.x_axis.title or "")
        if ads.x_axis.units:
            try:
                ds.x.units = ads.x_axis.units
            except Exception:
                pass
        if ads.x_axis.labels is not None:
            try:
                ds.x.labels = ads.x_axis.labels
            except Exception:
                pass
    if ads.y_axis and ads.y_axis.values is not None:
        ds.y = Coord(ads.y_axis.values, title=ads.y_axis.title or "")
        if ads.y_axis.units:
            try:
                ds.y.units = ads.y_axis.units
            except Exception:
                pass
        if ads.y_axis.labels is not None:
            try:
                ds.y.labels = ads.y_axis.labels
            except Exception:
                pass

    ds.meta = dict(ads.meta)
    ds.meta["processing_history"] = list(ads.provenance)

    if ads.title:
        ds.title = ads.title
    if ads.units:
        try:
            ds.units = ads.units
        except Exception:
            ds.meta["value_units_label"] = ads.units

    return ds
