"""
SpectraSherpa SDK public surface.

The top-level package keeps the established node-authoring compatibility
imports while exposing two-tier domain namespaces such as ``data`` and
``preprocess``.
"""

from __future__ import annotations

import importlib
from typing import Any

# Domain namespaces are loaded lazily (PEP 562) rather than eagerly at
# package-import time. A handful of these submodules (e.g. ``validate``) are
# legitimate, lightweight dependencies of individual DAG nodes -- registering
# the node catalog imports every node module, including any that reference
# ``spectra_sherpa.sdk.<submodule>`` for their execution-contract identity.
# Eagerly importing the whole facade here dragged unrelated, heavier
# namespaces (``canonical_capsule``, ``canonical_project``, ``report``, ...) into that
# same registry-load path. Lazy attribute access keeps
# ``import spectra_sherpa.sdk.validate`` cheap without changing the public
# API: every name below is still reachable as ``spectra_sherpa.sdk.<name>``,
# just resolved on first use instead of at import time.
_SCIENTIFIC_SUBMODULES = frozenset(
    {
        "data",
        "deployment",
        "explore",
        "preprocess",
        "plot",
        "plot_spec",
        "regression",
        "project",
        "report",
        "runtime",
        "selection",
        "validate",
        "workflow",
    }
)

# Evidence and portability modules remain supported explicit imports, but are
# deliberately absent from the default ``dir(spectra_sherpa.sdk)`` discovery
# surface. Scientists see data and analysis first; reviewers can still import
# these exact modules without a compatibility alias or eager initialization.
_EVIDENCE_SUBMODULES = frozenset(
    {
        "campaign_review",
        "canonical_application",
        "canonical_campaign_evidence",
        "canonical_capsule",
        "canonical_execution_evidence",
        "canonical_fitted_artifact",
        "canonical_full_refit_evidence",
        "canonical_project",
        "canonical_public_fixture",
        "canonical_reproduction",
        "canonical_summary",
        "execution_contract",
        "local_model_record",
        "optimization_hypothesis_evidence",
    }
)

_LAZY_SUBMODULES = _SCIENTIFIC_SUBMODULES | _EVIDENCE_SUBMODULES

# Keep the historic facade import-compatible without loading it on every
# ``import spectra_sherpa.sdk.<leaf>``.  The compatibility implementation
# reaches the live DAG helpers and node base; importing it eagerly made a
# leaf-only, data-contract operation initialize the full built-in node catalog
# (and optional scientific runtimes).  These names are a deliberate public
# compatibility map.  ``test_sdk_imports`` verifies that it remains exactly
# aligned with ``sdk._compat.__all__`` once that module is requested.
_COMPAT_EXPORTS = (
    "SherpaDataset",
    "AxisInfo",
    "FeatureAxis",
    "SpectralAxis",
    "TimeAxis",
    "MZAxis",
    "PotentialAxis",
    "FrequencyAxis",
    "SpatialAxis",
    "SampleAxis",
    "coerce_to_sherpa",
    "build_dataset_like",
    "Node",
    "NodeMetadata",
    "NodeParameter",
    "NodeRegistry",
    "NodeStatus",
    "PortMetadata",
    "node_registry",
    "register_node",
    "ChemometricsNode",
    "ChemometricsParam",
    "param_number",
    "param_bool",
    "param_text",
    "param_select",
    "add_processing_step",
    "copy_processing_history",
    "get_processing_history",
    "clear_processing_history",
    "exclude_samples",
    "include_samples",
    "get_included_data",
    "get_include_mask",
    "set_class",
    "get_classes",
    "filter_by_class",
    "set_sample_labels",
    "get_sample_labels",
    "detect_spectral_technique",
    "detect_data_quantity",
    "detect_x_axis_type",
    "get_spectral_info",
)

__all__ = [*_COMPAT_EXPORTS, *sorted(_LAZY_SUBMODULES)]


def __getattr__(name: str) -> Any:
    if name == "_compat":
        module = importlib.import_module("._compat", __name__)
        globals()[name] = module
        return module
    if name in _COMPAT_EXPORTS:
        module = importlib.import_module("._compat", __name__)
        value = getattr(module, name)
        globals()[name] = value
        return value
    if name in _LAZY_SUBMODULES:
        module = importlib.import_module(f".{name}", __name__)
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    ordinary_globals = set(globals()) - _EVIDENCE_SUBMODULES
    return sorted(ordinary_globals | _SCIENTIFIC_SUBMODULES | set(_COMPAT_EXPORTS))
