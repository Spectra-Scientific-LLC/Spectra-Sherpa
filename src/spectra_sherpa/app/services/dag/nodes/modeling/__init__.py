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
    apply_fitted_pls_node,
    clustering_nodes,
    decomposition_nodes,
    efa_nodes,
    fitted_pls_node,
    fitted_regression_nodes,
    ica_node,
    library_compare_node,
    load_apply_node,
    mcr_nodes,
    parafac_node,
    pca_nodes,
    peak_finding_nodes,
    predict_regression_node,
    regression_nodes,
    simplisma_nodes,
)
from .apply_fitted_pls_node import ApplyFittedPLSV2Node
from .clustering_nodes import DBSCANNode, HCANode, KMeansNode

# Public utilities
from .core_utils import (
    create_spectral_dataset,
    ensure_orientation,
    is_sequential_numeric,
    make_safe_coord,
)
from .decomposition_nodes import NMFNode
from .efa_nodes import EFANode
from .fitted_pls_node import FittedPLSV2Node
from .ica_node import FastICANode
from .library_compare_node import CompareVsLibraryNode
from .load_apply_node import LoadApplyModelNode
from .mcr_nodes import MCRNode
from .parafac_node import PARAFACNode
from .pca_nodes import PCANode, PCATransformNode
from .peak_finding_nodes import PeakFindingNode
from .regression_nodes import LinearRegressionNode, PCRNode, SVRNode
from .simplisma_nodes import SIMPLISMANode

__all__ = [
    # Public utilities
    "make_safe_coord",
    "create_spectral_dataset",
    "ensure_orientation",
    "is_sequential_numeric",
    # All node classes
    "PCANode",
    "PCATransformNode",
    "ApplyFittedPLSV2Node",
    "FittedPLSV2Node",
    "PCRNode",
    "SVRNode",
    "LinearRegressionNode",
    "MCRNode",
    "PARAFACNode",
    "EFANode",
    "HCANode",
    "KMeansNode",
    "DBSCANNode",
    "PeakFindingNode",
    "SIMPLISMANode",
    "NMFNode",
    "FastICANode",
    "LoadApplyModelNode",
    "CompareVsLibraryNode",
]
