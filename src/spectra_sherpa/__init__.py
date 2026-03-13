"""SpectraSherpa — local-first spectroscopy platform."""

from __future__ import annotations

__version__ = "0.2.0"

from spectra_sherpa.app.lib.adapters.numpy_adapter import from_numpy, to_numpy
from spectra_sherpa.app.lib.axes import (
    AxisInfo,
    FeatureAxis,
    FrequencyAxis,
    MZAxis,
    PotentialAxis,
    SampleAxis,
    SpatialAxis,
    SpectralAxis,
    TimeAxis,
)
from spectra_sherpa.app.lib.sherpa_dataset import (
    DomainContext,
    EvaluationResult,
    Provenance,
    QualityMetrics,
    SherpaDataset,
    TargetContext,
)


def __getattr__(name: str):
    """Lazy submodules — io loads pandas, preprocessing loads scipy."""
    if name == "io":
        from spectra_sherpa.app.lib import io as _io

        return _io
    if name == "preprocessing":
        from spectra_sherpa.app.lib import preprocessing as _prep

        return _prep
    raise AttributeError(f"module 'spectra_sherpa' has no attribute {name!r}")


__all__ = [
    "__version__",
    "AxisInfo",
    "DomainContext",
    "EvaluationResult",
    "FeatureAxis",
    "FrequencyAxis",
    "MZAxis",
    "PotentialAxis",
    "Provenance",
    "QualityMetrics",
    "SampleAxis",
    "SherpaDataset",
    "SpatialAxis",
    "SpectralAxis",
    "TargetContext",
    "TimeAxis",
    "from_numpy",
    "io",
    "preprocessing",
    "to_numpy",
]
