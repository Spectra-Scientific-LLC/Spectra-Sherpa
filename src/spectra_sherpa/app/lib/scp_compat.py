"""
Centralized SpectroChemPy compatibility layer.

ALL application code should import SpectroChemPy through this module::

    from app.lib.scp_compat import scp, NDDataset, Coord, HAS_SCP

This centralises version checks, graceful degradation when SCP is
unavailable, and future API migration paths.  No file outside this
module may ``import spectrochempy`` or ``from spectrochempy import ...``
directly — enforce with the CI check in ``tests/test_scp_import_rule.py``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import spectrochempy as scp
    from spectrochempy import NDDataset, Coord

    HAS_SCP = True
except ImportError:
    scp = None  # type: ignore[assignment]
    NDDataset = None  # type: ignore[assignment,misc]
    Coord = None  # type: ignore[assignment,misc]
    HAS_SCP = False
    logger.warning("spectrochempy not available — spectral analysis features disabled")


__all__ = ["scp", "NDDataset", "Coord", "HAS_SCP"]
