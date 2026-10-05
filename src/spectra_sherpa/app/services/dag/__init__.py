"""
DAG workflow engine for spectral analysis.

This module provides a node-based workflow system for building
reproducible spectral analysis pipelines.
"""

import os

from .node_base import (
    Node,
    NodeMetadata,
    NodeParameter,
    NodeRegistry,
    NodeStatus,
    node_registry,
    register_node,
)
from .presentation_contract import NodePresentationContract, ScientificPresentation

if os.environ.get("SPECTRA_DAG_SKIP_BUILTIN_REGISTRATION") != "1":
    # Import ALL node modules to trigger @register_node side effects.
    # Order matters: data and blend depend on other modules.
    from .nodes import (  # noqa: F401
        blend,
        classification,
        data,
        diagnostics,
        modeling,
        output,
        preprocessing,
        time_series,
    )

    # Lock the exact installed operation vocabulary for this process.
    node_registry.freeze_builtins()


def __getattr__(name: str):
    """Load the execution engine only when a caller needs it.

    Node authors and contract helpers use the registry and node base directly.
    Loading the executor merely to reach those definitions imports optional
    scientific adapters.  Keeping that import at the executor boundary makes
    a fresh approved-package child use the same node classes without loading
    unrelated built-in runtime families.
    """

    if name in {"DAGExecutor", "WorkflowEdge", "WorkflowNode", "WorkflowStatus"}:
        from .executor import DAGExecutor, WorkflowEdge, WorkflowNode, WorkflowStatus

        exports = {
            "DAGExecutor": DAGExecutor,
            "WorkflowEdge": WorkflowEdge,
            "WorkflowNode": WorkflowNode,
            "WorkflowStatus": WorkflowStatus,
        }
        globals().update(exports)
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Node",
    "NodeMetadata",
    "NodeParameter",
    "NodeRegistry",
    "NodeStatus",
    "node_registry",
    "register_node",
    "NodePresentationContract",
    "ScientificPresentation",
    "DAGExecutor",
    "WorkflowNode",
    "WorkflowEdge",
    "WorkflowStatus",
]
