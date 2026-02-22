"""Modeling nodes and utilities for chemometric analysis.

This package contains:
- Dimensionality reduction nodes (PCA, NMF, FastICA)
- Regression nodes (PLS, PCR, SVR, LinearRegression)
- Clustering nodes (HCA, KMeans, DBSCAN)
- Decomposition/resolution nodes (MCR, EFA, SIMPLISMA)
- Transform nodes (PLSPredict, PCATransform)
- Core utilities for custom node development

**Public Utilities:**
- `make_safe_coord()` - Convert coordinates to AxisInfo
- `create_spectral_dataset()` - Build datasets with coordinate preservation
- `is_sequential_numeric()` - Detect sequential vs categorical data
"""

# Import all nodes from legacy modeling file for backward compatibility
# This ensures existing imports like "from .modeling import PCANode" still work
from ..modeling_legacy import (
    DBSCANNode,
    EFANode,
    FastICANode,
    HCANode,
    KMeansNode,
    LinearRegressionNode,
    MCRNode,
    NMFNode,
    PCANode,
    PCATransformNode,
    PCRNode,
    PeakFindingNode,
    PLSNode,
    PLSPredictNode,
    SIMPLISMANode,
    SVRNode,
)
from .core_utils import (
    create_spectral_dataset,
    is_sequential_numeric,
    make_safe_coord,
)

__all__ = [
    # Public utilities
    "make_safe_coord",
    "create_spectral_dataset",
    "is_sequential_numeric",
    # All node classes (for backward compatibility)
    "PCANode",
    "NMFNode",
    "FastICANode",
    "PLSNode",
    "PCRNode",
    "SVRNode",
    "LinearRegressionNode",
    "HCANode",
    "KMeansNode",
    "DBSCANNode",
    "MCRNode",
    "EFANode",
    "SIMPLISMANode",
    "PeakFindingNode",
    "PLSPredictNode",
    "PCATransformNode",
]
