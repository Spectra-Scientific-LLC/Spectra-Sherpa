"""
Node implementations for DAG workflows.

This package contains all available node types organized by category.
"""

import os

# Import all node modules to trigger registration
if os.environ.get("SPECTRA_DAG_SKIP_BUILTIN_REGISTRATION") != "1":
    from . import (
        blend,
        classification,
        classification_evaluator_node,
        custom,  # Atomic blending & synthetic data nodes
        data,
        deploy_nodes,
        diagnostics,
        labeled_regression_evaluator_node,
        modeling,
        output,
        preprocessing,
        regression_evaluator_node,
        selection,
        time_series,
        transfer,
    )

__all__ = [
    "data",
    "modeling",
    "labeled_regression_evaluator_node",
    "output",
    "preprocessing",
    "blend",
    "classification",
    "classification_evaluator_node",
    "diagnostics",
    "time_series",
    "custom",
    "deploy_nodes",
    "regression_evaluator_node",
    "selection",
    "transfer",
]
