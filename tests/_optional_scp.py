"""Test-only access to the optional runtime; never imported by product code."""

from __future__ import annotations

try:
    import spectrochempy as scp
except ImportError:
    scp = None

HAS_SCP = scp is not None
NDDataset = scp.NDDataset if scp is not None else None
Coord = scp.Coord if scp is not None else None

__all__ = ("Coord", "HAS_SCP", "NDDataset", "scp")
