"""
SpectraSherpa Lite SDK — stable public API for third-party plugins.

Third-party plugin developers should import ONLY from this module.
Everything under ``spectrasherpa_lite.app.*`` is internal and subject
to change without notice.

Quick start
-----------
::

    from spectrasherpa_lite.sdk import (
        Node, NodeMetadata, NodeParameter, PortMetadata,
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

Version policy
--------------
- Minor bumps (1.x → 1.y): additive only, no removals.
- Major bumps (1.x → 2.0): may remove deprecated symbols (6-month notice).
- Patch bumps (1.x.y → 1.x.z): bug fixes only.
"""

from __future__ import annotations

# ── Core node system ────────────────────────────────────────────────
from spectrasherpa_lite.app.services.dag.node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodeRegistry,
    NodeStatus,
    PortMetadata,
    node_registry,
    register_node,
)

# ── Provenance / processing history ────────────────────────────────
from spectrasherpa_lite.app.services.dag.meta_helpers import (
    add_processing_step,
    copy_processing_history,
    get_processing_history,
    clear_processing_history,
    safe_get_coord,
)

# ── Sample management (PLS_Toolbox-style) ──────────────────────────
from spectrasherpa_lite.app.services.dag.meta_helpers import (
    exclude_samples,
    include_samples,
    get_included_data,
    get_include_mask,
    set_class,
    get_classes,
    filter_by_class,
    set_sample_labels,
    get_sample_labels,
)

# ── Spectral detection utilities ───────────────────────────────────
from spectrasherpa_lite.app.services.dag.meta_helpers import (
    detect_spectral_technique,
    detect_data_quantity,
    detect_x_axis_type,
    get_spectral_info,
)

__all__ = [
    # Core node system
    "Node",
    "NodeMetadata",
    "NodeParameter",
    "NodeRegistry",
    "NodeStatus",
    "PortMetadata",
    "node_registry",
    "register_node",
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
