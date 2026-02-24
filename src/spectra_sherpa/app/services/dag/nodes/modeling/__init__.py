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

# Import all node modules to trigger @register_node decorators
from . import (  # noqa: F401
    clustering_nodes,
    decomposition_nodes,
    efa_nodes,
    load_apply_node,
    mcr_nodes,
    pca_nodes,
    peak_finding_nodes,
    pls_nodes,
    regression_nodes,
    simplisma_nodes,
)
from .clustering_nodes import DBSCANNode, HCANode, KMeansNode

# Public utilities
from .core_utils import (
    create_spectral_dataset,
    is_sequential_numeric,
    make_safe_coord,
)
from .decomposition_nodes import FastICANode, NMFNode
from .efa_nodes import EFANode
from .load_apply_node import LoadApplyModelNode
from .mcr_nodes import MCRNode

# Re-export node classes for backward compatibility
from .pca_nodes import PCANode, PCATransformNode
from .peak_finding_nodes import PeakFindingNode
from .pls_nodes import PLSNode, PLSPredictNode
from .regression_nodes import LinearRegressionNode, PCRNode, SVRNode
from .simplisma_nodes import SIMPLISMANode

__all__ = [
    # Public utilities
    "make_safe_coord",
    "create_spectral_dataset",
    "is_sequential_numeric",
    # All node classes
    "PCANode",
    "PCATransformNode",
    "PLSNode",
    "PLSPredictNode",
    "PCRNode",
    "SVRNode",
    "LinearRegressionNode",
    "MCRNode",
    "EFANode",
    "HCANode",
    "KMeansNode",
    "DBSCANNode",
    "PeakFindingNode",
    "SIMPLISMANode",
    "NMFNode",
    "FastICANode",
    "LoadApplyModelNode",
]
