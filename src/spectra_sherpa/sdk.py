"""
SpectraSherpa SDK — convenient public imports for plugins and custom nodes.

The full OSS package is open for third-party use. This module collects the
most common, compatibility-oriented symbols for node authors so plugins do not
need to chase internal file layout changes. Advanced integrations may import
directly from ``spectra_sherpa.app.*`` when they intentionally depend on a
lower-level API; prefer this module for ordinary node and plugin development.

Quick start
-----------
::

    from spectra_sherpa.sdk import (
        Node, NodeMetadata, NodeParameter, PortMetadata,
        SherpaDataset, SpectralAxis, SampleAxis,
        register_node, add_processing_step,
    )

    @register_node
    class MyNode(Node):
        metadata = NodeMetadata(
            node_type="vendor.my_operation",
            category="preprocessing",
            label="My Custom Op",
            description="Does something useful",
            parameters=[
                NodeParameter(
                    name="strength",
                    label="Strength",
                    param_type="number",
                    default=1.0,
                    min_value=0.0,
                    max_value=10.0,
                ),
            ],
        )

        async def execute(self, X):
            result = X.copy()
            # ... your operation ...
            add_processing_step(
                result, "vendor.my_operation",
                {"strength": self.parameters.get("strength", 1.0)},
                node_id=self.node_id,
            )
            return result

Compatibility policy
--------------------
SpectraSherpa is pre-1.0. Symbols exported here are the preferred
compatibility surface for plugins and custom nodes; changes are additive when
possible, and breaking changes are called out in the changelog.
"""

from __future__ import annotations

# ── Dataset and axis primitives ─────────────────────────────────────
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

# ── Provenance / processing history ────────────────────────────────
# ── Sample management ────────────────────────────────────────────────
# ── Spectral detection utilities ───────────────────────────────────
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

# ── Core node system ────────────────────────────────────────────────
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
