"""
Preprocessing nodes for spectral data.

These nodes implement various preprocessing techniques like baseline correction,
smoothing, normalization, and derivatives.

All nodes:
- Accept the canonical SherpaDataset as input
- Return SherpaDataset as output
- Record processing history via provenance

All node classes have been split into individual files for navigability.
"""

# Import all node modules to trigger @register_node decorators
from . import (  # noqa: F401
    apply_fitted_preprocessing_nodes,
    apply_fitted_scale_node,
    baseline_nodes,
    clip_floor_node,
    clip_range_node,
    cosmic_ray_node,
    derivative_node,
    emsc_node,
    msc_node,
    normalize_node,
    osc_node,
    penalized_baseline_node,
    scale_node,
    smooth_node,
    wavenumber_align_node,
)

__all__: list[str] = []
