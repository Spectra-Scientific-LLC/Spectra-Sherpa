"""
Preprocessing nodes for spectral data.

These nodes implement various preprocessing techniques like baseline correction,
smoothing, normalization, and derivatives.

All nodes:
- Accept SherpaDataset (or legacy NDDataset via coercion) as input
- Return SherpaDataset as output
- Record processing history via provenance

All node classes have been split into individual files for navigability.
"""

# Import all node modules to trigger @register_node decorators
from . import (  # noqa: F401
    baseline_nodes,
    cleaning_nodes,
    correction_nodes,
    normalize_scale_nodes,
    osc_node,
    smooth_deriv_nodes,
)

# Re-export node classes for backward compatibility
from .baseline_nodes import BaselinePenalizedLSNode, BaselineRubberbandNode
from .cleaning_nodes import ClipFloorNode, ClipRangeNode, CosmicRayRemovalNode, WavenumberAlignNode
from .correction_nodes import EMSCNode
from .normalize_scale_nodes import NormalizeNode, ScaleNode
from .osc_node import OSCNode
from .smooth_deriv_nodes import DerivativeNode, SmoothNode

__all__ = [
    "BaselinePenalizedLSNode",
    "BaselineRubberbandNode",
    "ClipFloorNode",
    "ClipRangeNode",
    "CosmicRayRemovalNode",
    "DerivativeNode",
    "EMSCNode",
    "NormalizeNode",
    "OSCNode",
    "ScaleNode",
    "SmoothNode",
    "WavenumberAlignNode",
]
