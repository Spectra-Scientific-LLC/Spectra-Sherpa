"""Selection & Design nodes for chemometric calibration.

This package provides:
- Sample partitioning (random, stratified, sequential, Kennard-Stone, DUPLEX, SPXY)
- Variable/wavelength selection (interval, peak-window, VIP, coef, selectivity ratio)
- Advanced selectors: iPLS, CARS, SPA, UVE, stability selection
- Leakage-safe nested CV with selection inside folds
- Selection audit trail and comparative analysis
- Shared utilities (VIP calculation, sample selection algorithms)
"""

# Import node modules to trigger @register_node decorators
from . import (  # noqa: F401
    cars_node,
    compare_selections_node,
    ipls_node,
    nested_cv_node,
    sample_partition_node,
    selection_audit_node,
    spa_node,
    stability_node,
    uve_node,
    variable_select_node,
)
from .cars_node import CARSNode
from .compare_selections_node import CompareSelectionsNode
from .ipls_node import IPLSNode
from .nested_cv_node import NestedCVNode
from .sample_partition_node import SamplePartitionNode
from .selection_audit_node import SelectionAuditNode
from .spa_node import SPANode
from .stability_node import StabilitySelectionNode
from .uve_node import UVENode
from .variable_select_node import VariableSelectNode

__all__ = [
    "SamplePartitionNode",
    "VariableSelectNode",
    "IPLSNode",
    "CARSNode",
    "SPANode",
    "UVENode",
    "StabilitySelectionNode",
    "NestedCVNode",
    "SelectionAuditNode",
    "CompareSelectionsNode",
]
