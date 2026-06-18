"""
Compatibility exports for the public SpectraSherpa SDK surface.

This module preserves the pre-package ``spectra_sherpa.sdk`` imports used by
plugins and custom nodes while the SDK grows domain namespaces such as
``spectra_sherpa.sdk.data`` and ``spectra_sherpa.sdk.preprocess``.
"""

from __future__ import annotations

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
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.io_contracts import build_dataset_like, coerce_to_sherpa
from spectra_sherpa.app.services.dag.meta_helpers import (
    add_processing_step,
    clear_processing_history,
    copy_processing_history,
    detect_data_quantity,
    detect_spectral_technique,
    detect_x_axis_type,
    exclude_samples,
    filter_by_class,
    get_classes,
    get_include_mask,
    get_included_data,
    get_processing_history,
    get_sample_labels,
    get_spectral_info,
    include_samples,
    safe_get_coord,
    set_class,
    set_sample_labels,
)
from spectra_sherpa.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodeRegistry,
    NodeStatus,
    PortMetadata,
    node_registry,
    register_node,
)
from spectra_sherpa.sdk_nodes import (
    ChemometricsNode,
    ChemometricsParam,
    param_bool,
    param_number,
    param_select,
    param_text,
)

__all__ = [
    # Dataset and axis primitives
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
    # Core node system
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
    # Provenance
    "add_processing_step",
    "copy_processing_history",
    "get_processing_history",
    "clear_processing_history",
    "safe_get_coord",
    # Sample management
    "exclude_samples",
    "include_samples",
    "get_included_data",
    "get_include_mask",
    "set_class",
    "get_classes",
    "filter_by_class",
    "set_sample_labels",
    "get_sample_labels",
    # Spectral detection
    "detect_spectral_technique",
    "detect_data_quantity",
    "detect_x_axis_type",
    "get_spectral_info",
]
