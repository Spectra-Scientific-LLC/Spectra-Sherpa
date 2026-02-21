"""
Edge adapters for SherpaDataset.

All external format conversions (numpy, sklearn, SpectroChemPy)
live here. The core SherpaDataset module has zero external dependencies.
"""

from spectra_sherpa.app.lib.adapters.numpy_adapter import from_numpy, to_numpy
from spectra_sherpa.app.lib.adapters.sklearn_adapter import from_sklearn

__all__ = [
    "from_numpy",
    "to_numpy",
    "from_sklearn",
]

# SCP adapters are imported lazily to avoid hard dependency:
#   from spectra_sherpa.app.lib.adapters.scp_adapter import from_nddataset, to_nddataset
