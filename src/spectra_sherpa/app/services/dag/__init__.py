"""
DAG workflow engine for spectral analysis.

This module provides a node-based workflow system for building
reproducible spectral analysis pipelines.
"""

from .node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodeRegistry,
    NodeStatus,
    node_registry,
    register_node,
)
from .executor import DAGExecutor, WorkflowNode, WorkflowEdge, WorkflowStatus

# Import ALL node modules to trigger registration
# Order matters: data and blend depend on other modules
from .nodes import (
    blend,
    classification,
    cloud,
    data,
    diagnostics,
    modeling,
    output,
    preprocessing,
    time_series,
)

# Lock the registry — plugins loaded later cannot overwrite built-in types
node_registry.freeze_builtins()

__all__ = [
    "Node",
    "NodeMetadata",
    "NodeParameter",
    "NodeRegistry",
    "NodeStatus",
    "node_registry",
    "register_node",
    "DAGExecutor",
    "WorkflowNode",
    "WorkflowEdge",
    "WorkflowStatus",
]
