"""
Node implementations for DAG workflows.

This package contains all available node types organized by category.
"""

# Import all node modules to trigger registration
from . import data
from . import modeling
from . import output
from . import preprocessing
from . import blend
from . import classification
from . import cloud
from . import diagnostics
from . import time_series
from . import custom  # Atomic blending & synthetic data nodes

__all__ = [
    "data",
    "modeling",
    "output",
    "preprocessing",
    "blend",
    "classification",
    "cloud",
    "diagnostics",
    "time_series",
    "custom",
]
