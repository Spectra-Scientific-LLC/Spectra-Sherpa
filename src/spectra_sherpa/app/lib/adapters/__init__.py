"""
Edge adapters for SherpaDataset.

Native NumPy and scikit-learn conversions live here. The deliberately narrow
optional SpectroChemPy boundary lives under ``spectra_sherpa.interoperability``.
The core SherpaDataset module has zero external dependencies.
"""

from spectra_sherpa.app.lib.adapters.numpy_adapter import from_numpy, to_numpy
from spectra_sherpa.app.lib.adapters.sklearn_adapter import from_sklearn

__all__ = [
    "from_numpy",
    "to_numpy",
    "from_sklearn",
]
