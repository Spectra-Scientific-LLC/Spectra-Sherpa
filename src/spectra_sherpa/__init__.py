"""SpectraSherpa — local-first spectroscopy platform."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import TYPE_CHECKING

# Source of truth is ``[tool.poetry] version`` in pyproject.toml; read it via
# importlib.metadata so the runtime banner cannot drift from the installed
# package's actual version. The hard-coded fallback is only for editable
# checkouts where metadata is missing (e.g. running directly from ``src/``
# without ``pip install -e``).
try:
    __version__ = _pkg_version("spectra-sherpa")
except PackageNotFoundError:  # pragma: no cover — uninstalled checkout
    __version__ = "0.0.0+unknown"

if TYPE_CHECKING:
    from spectra_sherpa.app.lib.adapters.numpy_adapter import from_numpy, to_numpy
    from spectra_sherpa.app.lib.axes import (
        AxisClassLevel,
        AxisClassSet,
        AxisInfo,
        AxisLabelSet,
        AxisScaleSet,
        AxisTitleSet,
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
        DatasetDescriptiveContext,
        DatasetLayoutContext,
        DatasetSourceHistory,
        DatasetSourceIdentity,
        DomainContext,
        EvaluationResult,
        Provenance,
        QualityMetrics,
        SherpaDataset,
        TargetContext,
    )


_LAZY_EXPORTS = {
    "from_numpy": ("spectra_sherpa.app.lib.adapters.numpy_adapter", "from_numpy"),
    "to_numpy": ("spectra_sherpa.app.lib.adapters.numpy_adapter", "to_numpy"),
    "AxisClassLevel": ("spectra_sherpa.app.lib.axes", "AxisClassLevel"),
    "AxisClassSet": ("spectra_sherpa.app.lib.axes", "AxisClassSet"),
    "AxisInfo": ("spectra_sherpa.app.lib.axes", "AxisInfo"),
    "AxisLabelSet": ("spectra_sherpa.app.lib.axes", "AxisLabelSet"),
    "AxisScaleSet": ("spectra_sherpa.app.lib.axes", "AxisScaleSet"),
    "AxisTitleSet": ("spectra_sherpa.app.lib.axes", "AxisTitleSet"),
    "FeatureAxis": ("spectra_sherpa.app.lib.axes", "FeatureAxis"),
    "FrequencyAxis": ("spectra_sherpa.app.lib.axes", "FrequencyAxis"),
    "MZAxis": ("spectra_sherpa.app.lib.axes", "MZAxis"),
    "PotentialAxis": ("spectra_sherpa.app.lib.axes", "PotentialAxis"),
    "SampleAxis": ("spectra_sherpa.app.lib.axes", "SampleAxis"),
    "SpatialAxis": ("spectra_sherpa.app.lib.axes", "SpatialAxis"),
    "SpectralAxis": ("spectra_sherpa.app.lib.axes", "SpectralAxis"),
    "TimeAxis": ("spectra_sherpa.app.lib.axes", "TimeAxis"),
    "DatasetDescriptiveContext": (
        "spectra_sherpa.app.lib.sherpa_dataset",
        "DatasetDescriptiveContext",
    ),
    "DatasetLayoutContext": ("spectra_sherpa.app.lib.sherpa_dataset", "DatasetLayoutContext"),
    "DatasetSourceHistory": ("spectra_sherpa.app.lib.sherpa_dataset", "DatasetSourceHistory"),
    "DatasetSourceIdentity": ("spectra_sherpa.app.lib.sherpa_dataset", "DatasetSourceIdentity"),
    "DomainContext": ("spectra_sherpa.app.lib.sherpa_dataset", "DomainContext"),
    "EvaluationResult": ("spectra_sherpa.app.lib.sherpa_dataset", "EvaluationResult"),
    "Provenance": ("spectra_sherpa.app.lib.sherpa_dataset", "Provenance"),
    "QualityMetrics": ("spectra_sherpa.app.lib.sherpa_dataset", "QualityMetrics"),
    "SherpaDataset": ("spectra_sherpa.app.lib.sherpa_dataset", "SherpaDataset"),
    "TargetContext": ("spectra_sherpa.app.lib.sherpa_dataset", "TargetContext"),
}


def __getattr__(name: str):
    """Resolve the supported lazy native-ingestion module and public data types."""
    export = _LAZY_EXPORTS.get(name)
    if export is not None:
        from importlib import import_module

        module_name, attribute_name = export
        value = getattr(import_module(module_name), attribute_name)
        globals()[name] = value
        return value
    if name == "io":
        from importlib import import_module

        _io = import_module("spectra_sherpa.io")
        globals()[name] = _io
        return _io
    raise AttributeError(f"module 'spectra_sherpa' has no attribute {name!r}")


__all__ = [
    "__version__",
    "AxisClassLevel",
    "AxisClassSet",
    "AxisInfo",
    "AxisLabelSet",
    "AxisScaleSet",
    "AxisTitleSet",
    "DatasetDescriptiveContext",
    "DatasetLayoutContext",
    "DatasetSourceHistory",
    "DatasetSourceIdentity",
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
    "to_numpy",
]
