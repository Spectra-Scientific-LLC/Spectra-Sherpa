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
    knn_nodes,
    plsda_nodes,
    predict_node,
    simca_nodes,
)
from .knn_nodes import KNNNode

# Re-export node classes for backward compatibility
from .plsda_nodes import PLSDANode
from .predict_node import ClassifierPredictNode
from .simca_nodes import SIMCANode

__all__ = [
    "PLSDANode",
    "KNNNode",
    "SIMCANode",
    "ClassifierPredictNode",
]
