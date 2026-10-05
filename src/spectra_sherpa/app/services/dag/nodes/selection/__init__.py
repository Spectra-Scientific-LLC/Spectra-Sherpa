"""Selection & Design nodes for chemometric calibration.

This package provides:
- Sample partitioning (random, stratified, sequential, Kennard-Stone, DUPLEX, SPXY)
- Variable/wavelength selection (interval, peak-window, VIP, coef, selectivity ratio)
- Advanced selectors: iPLS, CARS, SPA, MC-UVE, stability selection
- Leakage-safe nested CV with selection inside folds
- Selection audit trail and comparative analysis
- Shared utilities (VIP calculation, sample selection algorithms)
"""

# Import node modules to trigger @register_node decorators
from . import (  # noqa: F401
    cars_node,
    compare_selections_node,
    ipls_node,
    mcuve_node,
    nested_cv_node,
    selection_audit_node,
    spa_node,
    stability_node,
    variable_select_node,
)
from .cars_node import CARSNode
from .compare_selections_node import CompareSelectionsNode
from .ipls_node import IPLSNode
from .mcuve_node import MCUVENode
from .nested_cv_node import NestedCVNode
from .selection_audit_node import SelectionAuditNode
from .spa_node import SPANode
from .stability_node import StabilitySelectionNode
from .variable_select_node import VariableSelectNode

__all__ = [
    "VariableSelectNode",
    "IPLSNode",
    "CARSNode",
    "SPANode",
    "MCUVENode",
    "StabilitySelectionNode",
    "NestedCVNode",
    "SelectionAuditNode",
    "CompareSelectionsNode",
]
