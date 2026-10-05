"""
Classification nodes for chemometrics analysis.

This package contains:
- PLS-DA: Partial Least Squares Discriminant Analysis
- KNN: K-Nearest Neighbors classification
- SIMCA: Soft Independent Modeling of Class Analogy

All node classes have been split into individual files for navigability.
"""

# Import all node modules to trigger @register_node decorators
from . import (  # noqa: F401
    application_nodes,
    knn_nodes,
    plsda_nodes,
    simca_nodes,
)
from .application_nodes import ApplyKNNNode, ApplyPLSDANode, ApplySIMCANode
from .knn_nodes import KNNNode

# Re-export node classes for backward compatibility
from .plsda_nodes import PLSDANode
from .simca_nodes import SIMCANode

__all__ = [
    "PLSDANode",
    "KNNNode",
    "SIMCANode",
    "ApplyKNNNode",
    "ApplyPLSDANode",
    "ApplySIMCANode",
]
