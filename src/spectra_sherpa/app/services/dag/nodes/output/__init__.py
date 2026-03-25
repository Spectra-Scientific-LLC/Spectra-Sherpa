"""
Output nodes for workflow results.

These nodes handle visualization and export of spectral data.

All node classes have been split into individual files for navigability.
"""

# Import all node modules to trigger @register_node decorators
from . import (  # noqa: F401
    contour_plot_node,
    data_table_node,
    export_node,
    plot_node,
    stats_summary_node,
)

# Re-export shared helper for backward compatibility
from ._helpers import get_axis_display_info

# Re-export node classes for backward compatibility
from .contour_plot_node import ContourPlotNode
from .data_table_node import DataTableNode
from .export_node import ExportNode
from .plot_node import PlotNode
from .stats_summary_node import StatsSummaryNode

__all__ = [
    "PlotNode",
    "ExportNode",
    "StatsSummaryNode",
    "ContourPlotNode",
    "DataTableNode",
    "get_axis_display_info",
]
