"""Calibration Transfer nodes for multi-instrument standardization.

This package provides:
- PDS (Piecewise Direct Standardization) — local window regression transfer
- SBC (Slope/Bias Correction) — global linear spectral correction

These nodes enable spectra measured on a secondary instrument to be
transformed into the response space of a primary (master) instrument,
allowing a single calibration model to be applied across instruments.
"""

# Import node modules to trigger @register_node decorators
from . import (  # noqa: F401
    pds_node,
    sbc_node,
)
from .pds_node import PDSNode
from .sbc_node import SBCNode

__all__ = [
    "PDSNode",
    "SBCNode",
]
