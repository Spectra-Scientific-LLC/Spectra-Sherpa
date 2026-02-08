"""
Base classes for DAG workflow nodes.

Each node represents a single operation in a spectral analysis workflow.
Nodes can be connected to form directed acyclic graphs (DAGs).
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type
from dataclasses import dataclass, field
from enum import Enum


class NodeStatus(str, Enum):
    """Node execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class NodeParameter:
    """Definition of a node parameter."""
    name: str
    label: str
    param_type: str  # "number", "boolean", "select", "text"
    default: Any = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    step: Optional[float] = None
    options: Optional[List[Dict[str, Any]]] = None
    description: Optional[str] = None
    required: bool = True
    category: Optional[str] = "basic"  # "basic" or "advanced" - complexity level for UI


@dataclass
class PortMetadata:
    """
    Definition of an input or output port for nodes.

    Port types enable smart connection validation and visual distinction:
    - dataset: NDDataset (spectral data, multi-dimensional arrays)
    - target: array (y values, class labels, concentrations)
    - model: Trained model objects (PCAModel, PLSModel, etc.)
    - config: Configuration dicts, metadata
    - array: Numeric arrays (metrics, loadings, scores, etc.)
    - number: Scalar numeric values
    - visualization: Plotly/visualization payloads
    """
    name: str  # Port identifier (e.g., "X_train", "y_class", "model")
    port_type: str  # "dataset", "target", "model", "config", "array", "number", "visualization"
    required: bool = True
    label: str = ""  # Display label (e.g., "Training Spectra")
    description: Optional[str] = None

    def __post_init__(self):
        """Set label to name if not provided."""
        if not self.label:
            self.label = self.name


# Backwards compatibility alias
InputPort = PortMetadata


@dataclass
class NodeMetadata:
    """Metadata about a node type."""
    node_type: str
    category: str  # "preprocessing", "modeling", "diagnostics", "export"
    label: str
    description: str
    parameters: List[NodeParameter] = field(default_factory=list)
    input_types: List[str] = field(default_factory=lambda: ["NDDataset"])
    output_type: str = "NDDataset"
    # Named input ports for multi-input nodes. If None, uses legacy positional inputs.
    # When defined, executor passes inputs as kwargs: execute(X=data1, y=data2)
    input_ports: Optional[List[PortMetadata]] = None
    # Named output ports for multi-output nodes (e.g., train/test split)
    # If None, single output on "default" port
    output_ports: Optional[List[PortMetadata]] = None


class Node(ABC):
    """
    Base class for all workflow nodes.

    Each node implements a single operation on spectral data.
    Nodes can be connected to form a workflow graph.
    """

    # Class-level metadata (must be overridden in subclasses)
    metadata: NodeMetadata = None

    def __init__(self, node_id: str, parameters: Optional[Dict[str, Any]] = None):
        """
        Initialize a node.

        Args:
            node_id: Unique identifier for this node instance
            parameters: Dictionary of parameter values
        """
        self.node_id = node_id
        self.parameters = parameters or {}
        self.status = NodeStatus.PENDING
        self.error_message: Optional[str] = None
        self.result: Optional[Any] = None

    @abstractmethod
    async def execute(self, *inputs: Any, **kwargs: Any) -> Any:
        """
        Execute the node's operation.

        For single-input nodes: receives positional args
        For multi-input nodes with named ports: receives kwargs by port name

        Args:
            *inputs: Input data from connected nodes (legacy positional)
            **kwargs: Input data by port name (for nodes with input_ports defined)

        Returns:
            Output data (typically an NDDataset)

        Raises:
            ValueError: If inputs are invalid
            RuntimeError: If execution fails
        """
        pass

    def uses_named_ports(self) -> bool:
        """Check if this node uses named input ports."""
        return self.metadata is not None and self.metadata.input_ports is not None

    def validate_parameters(self) -> None:
        """
        Validate node parameters against metadata.

        Raises:
            ValueError: If parameters are invalid
        """
        if not self.metadata:
            return

        for param_def in self.metadata.parameters:
            if param_def.required and param_def.name not in self.parameters:
                raise ValueError(f"Missing required parameter: {param_def.name}")

            value = self.parameters.get(param_def.name)
            if value is None:
                continue

            # Type validation
            if param_def.param_type == "number":
                if not isinstance(value, (int, float)):
                    raise ValueError(
                        f"Parameter {param_def.name} must be a number, got {type(value)}"
                    )
                if param_def.min_value is not None and value < param_def.min_value:
                    raise ValueError(
                        f"Parameter {param_def.name} must be >= {param_def.min_value}"
                    )
                if param_def.max_value is not None and value > param_def.max_value:
                    raise ValueError(
                        f"Parameter {param_def.name} must be <= {param_def.max_value}"
                    )

            elif param_def.param_type == "boolean":
                if not isinstance(value, bool):
                    raise ValueError(
                        f"Parameter {param_def.name} must be a boolean, got {type(value)}"
                    )

    async def run(self, *inputs: Any, **kwargs: Any) -> Any:
        """
        Run the node with error handling.

        Args:
            *inputs: Input data (positional, for single-input nodes)
            **kwargs: Input data by port name (for multi-input nodes)

        Returns:
            Output data
        """
        try:
            self.status = NodeStatus.RUNNING
            self.validate_parameters()
            self.result = await (self.execute(**kwargs) if kwargs else self.execute(*inputs))
            self.status = NodeStatus.COMPLETED
            return self.result
        except Exception as e:
            self.status = NodeStatus.ERROR
            self.error_message = str(e)
            raise

    @classmethod
    def get_metadata(cls) -> NodeMetadata:
        """Get node metadata."""
        if not cls.metadata:
            raise NotImplementedError("Node metadata not defined")
        return cls.metadata

    def to_dict(self) -> Dict[str, Any]:
        """Serialize node to dictionary."""
        return {
            "node_id": self.node_id,
            "node_type": self.metadata.node_type if self.metadata else None,
            "parameters": self.parameters,
            "status": self.status.value,
            "error_message": self.error_message,
        }


class NodeRegistry:
    """Registry for available node types."""

    def __init__(self):
        self._nodes: Dict[str, Type[Node]] = {}

    def register(self, node_class: Type[Node]) -> None:
        """
        Register a node type.

        Args:
            node_class: Node class to register
        """
        metadata = node_class.get_metadata()
        self._nodes[metadata.node_type] = node_class

    def create_node(
        self, node_type: str, node_id: str, parameters: Optional[Dict[str, Any]] = None
    ) -> Node:
        """
        Create a node instance.

        Args:
            node_type: Type of node to create (e.g., "baseline.als")
            node_id: Unique ID for the instance
            parameters: Node parameters

        Returns:
            Node instance

        Raises:
            KeyError: If node type is not registered
        """
        if node_type not in self._nodes:
            raise KeyError(f"Unknown node type: {node_type}")

        node_class = self._nodes[node_type]
        return node_class(node_id, parameters)

    def get_metadata(self, node_type: str) -> NodeMetadata:
        """Get metadata for a node type."""
        if node_type not in self._nodes:
            raise KeyError(f"Unknown node type: {node_type}")
        return self._nodes[node_type].get_metadata()

    def list_nodes(self) -> List[NodeMetadata]:
        """List all registered node types."""
        return [cls.get_metadata() for cls in self._nodes.values()]

    def list_by_category(self, category: str) -> List[NodeMetadata]:
        """List nodes in a specific category."""
        return [
            metadata for metadata in self.list_nodes()
            if metadata.category == category
        ]


# Global registry instance
node_registry = NodeRegistry()


def register_node(node_class: Type[Node]) -> Type[Node]:
    """
    Decorator to register a node type.

    Usage:
        @register_node
        class MyNode(Node):
            ...
    """
    node_registry.register(node_class)
    return node_class
