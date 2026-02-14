"""
Base classes for DAG workflow nodes.

Each node represents a single operation in a spectral analysis workflow.
Nodes can be connected to form directed acyclic graphs (DAGs).
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


@dataclass
class NodeResult:
    """
    Structured result from node execution.

    Wraps node outputs with optional diagnostic measurements.
    Diagnostics are ephemeral — recomputed on every run, not saved
    with the workflow definition.
    """
    outputs: Dict[str, Any] = field(default_factory=dict)
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def wrap(raw: Any) -> "NodeResult":
        """Wrap a legacy execute() return value into NodeResult.

        - Already a NodeResult → return as-is
        - dict with string keys → treat as named outputs
        - anything else → wrap as ``{"default": raw}``
        """
        if isinstance(raw, NodeResult):
            return raw
        if isinstance(raw, dict):
            return NodeResult(outputs=raw)
        return NodeResult(outputs={"default": raw})


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

    Each port declares a ``type_ref`` — a URI from the type registry
    (e.g. ``spectrasherpa://types/SpectralDataset/1.0``).  The registry
    resolves URIs and checks subtype / version compatibility at connection
    time.
    """
    name: str  # Port identifier (e.g., "X_train", "y_class", "model")
    type_ref: str  # "spectrasherpa://types/SpectralDataset/1.0"
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
    # Diagnostic keys this node emits during execution
    diagnostics: List[str] = field(default_factory=list)
    # Per-node SCP gate: True = requires SpectroChemPy at runtime
    requires_scp: bool = False


def _format_value(value: Any) -> str:
    """Format a Python value as a code literal for codegen."""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, float):
        # Use scientific notation for very large/small values
        if value != 0 and (abs(value) >= 1e6 or abs(value) < 1e-3):
            return f"{value:.0e}" if value == int(value) else f"{value:e}"
        return repr(value)
    return repr(value)


class Node(ABC):
    """
    Base class for all workflow nodes.

    Each node implements a single operation on spectral data.
    Nodes can be connected to form a workflow graph.
    """

    # Class-level metadata (must be overridden in subclasses)
    metadata: NodeMetadata = None

    # --- Python export support (override in subclasses) ---
    # SpectroChemPy method name for simple preprocessing nodes.
    # When set, the default generate_python() emits: data.{scp_method}(**params)
    scp_method: Optional[str] = None
    # Rename node parameters -> SCP keyword arguments
    # e.g. {"lam": "lamb", "p": "asymmetry"} means node param "lam" becomes scp kwarg "lamb"
    scp_param_map: Dict[str, str] = {}
    # Extra hardcoded kwargs always passed to the SCP method
    # e.g. {"deriv": 1} for first-derivative nodes
    scp_extra_kwargs: Dict[str, Any] = {}
    # Additional import lines needed by generated code
    python_extra_imports: List[str] = []

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

    # ------------------------------------------------------------------
    # Python export / code generation
    # ------------------------------------------------------------------

    def _resolve_params(self) -> Dict[str, Any]:
        """
        Merge metadata defaults with instance parameters.

        Returns a dict of all parameter values with defaults filled in.
        This is the single source of truth for parameter values used by
        both execute() and generate_python().
        """
        resolved: Dict[str, Any] = {}
        if self.metadata:
            for p in self.metadata.parameters:
                resolved[p.name] = self.parameters.get(p.name, p.default)
        return resolved

    def supports_python_export(self) -> bool:
        """Return True if this node can generate Python export code."""
        if self.scp_method is not None:
            return True
        # Check if the subclass overrides generate_python
        return type(self).generate_python is not Node.generate_python

    def generate_python(
        self, inputs: Dict[str, str], indent: str = "    ",
        use_scp: bool = True,
    ) -> List[str]:
        """
        Generate Python code lines for this node.

        The default implementation handles the common SCP-method pattern::

            data = {input_expr}.copy()
            data.{scp_method}(**kwargs)
            results['{node_id}'] = data

        Nodes that use numpy or have complex logic should override this.

        Args:
            inputs: Mapping of input name -> Python expression
                (e.g. ``{"input": "results['node_1']"}``)
            indent: Whitespace prefix for each line
            use_scp: If True, emit SpectroChemPy code; if False, emit
                numpy/scipy code for standalone scripts.

        Returns:
            List of Python code lines (already indented)
        """
        if self.scp_method is None:
            return [
                f"{indent}# TODO: {self.metadata.node_type} does not support Python export yet",
                f"{indent}raise NotImplementedError("
                f"'{self.metadata.node_type} export not implemented')",
            ]

        # SCP-only nodes can't generate no-SCP code
        if not use_scp and self.metadata and self.metadata.requires_scp:
            return [
                f"{indent}# --- {self.metadata.label} ({self.node_id}) ---",
                f"{indent}# This node requires SpectroChemPy (pip install spectra-sherpa[scp])",
                f"{indent}raise ImportError("
                f"'{self.metadata.label} requires spectrochempy')",
            ]

        lines: List[str] = []
        lines.append(f"{indent}# --- {self.metadata.label} ({self.node_id}) ---")

        # Determine input expression
        input_expr = next(iter(inputs.values())) if inputs else "input_data"
        lines.append(f"{indent}data = {input_expr}.copy()")

        # Build SCP method kwargs
        params = self._resolve_params()
        kwargs_parts: List[str] = []
        for param_name, value in params.items():
            scp_name = self.scp_param_map.get(param_name, param_name)
            kwargs_parts.append(f"{scp_name}={_format_value(value)}")
        for extra_name, extra_val in self.scp_extra_kwargs.items():
            kwargs_parts.append(f"{extra_name}={_format_value(extra_val)}")

        kwargs_str = ", ".join(kwargs_parts)
        lines.append(f"{indent}data.{self.scp_method}({kwargs_str})")
        lines.append(f"{indent}results['{self.node_id}'] = data")

        return lines

    async def run(self, *inputs: Any, **kwargs: Any) -> NodeResult:
        """
        Run the node with error handling.

        Args:
            *inputs: Input data (positional, for single-input nodes)
            **kwargs: Input data by port name (for multi-input nodes)

        Returns:
            NodeResult wrapping outputs and diagnostics
        """
        try:
            self.status = NodeStatus.RUNNING
            # Per-node SCP gate (replaces former blanket _SCP_CATEGORIES check)
            if self.metadata and self.metadata.requires_scp:
                from app.lib.scp_compat import HAS_SCP
                if not HAS_SCP:
                    raise ImportError(
                        f"{self.metadata.label} requires SpectroChemPy. "
                        f"Install with: pip install spectra-sherpa[scp]"
                    )
            self.validate_parameters()
            if kwargs:
                # Single "default" port → pass as first positional arg
                # (most execute() signatures use execute(self, input_data))
                if list(kwargs.keys()) == ["default"]:
                    raw = await self.execute(kwargs["default"])
                else:
                    raw = await self.execute(**kwargs)
            else:
                raw = await self.execute(*inputs)
            self.result = NodeResult.wrap(raw)
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
        self._builtin_types: set[str] = set()
        self._frozen: bool = False

    def freeze_builtins(self) -> None:
        """Mark all currently registered nodes as built-in.

        Call this once after all built-in nodes have been imported.
        After freezing, plugins cannot overwrite built-in node types.
        """
        self._builtin_types = set(self._nodes.keys())
        self._frozen = True
        logger.info(
            "Node registry frozen: %d built-in types", len(self._builtin_types)
        )

    def register(self, node_class: Type[Node]) -> None:
        """
        Register a node type.

        After ``freeze_builtins()`` is called, attempting to overwrite a
        built-in node type raises ``ValueError``.  Plugin-to-plugin
        overwrites emit a warning but are allowed.

        Args:
            node_class: Node class to register

        Raises:
            ValueError: If trying to overwrite a built-in node type
        """
        metadata = node_class.get_metadata()
        node_type = metadata.node_type

        if node_type in self._nodes:
            if self._frozen and node_type in self._builtin_types:
                raise ValueError(
                    f"Cannot overwrite built-in node type {node_type!r}. "
                    f"Plugins must use a unique namespaced type "
                    f"(e.g. 'vendor.my_operation')."
                )
            logger.warning(
                "Node type %r re-registered (overwriting %s with %s)",
                node_type,
                self._nodes[node_type].__name__,
                node_class.__name__,
            )

        self._nodes[node_type] = node_class

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

    def get_node_class(self, node_type: str) -> Type[Node]:
        """Get the registered Node class for a node type."""
        if node_type not in self._nodes:
            raise KeyError(f"Unknown node type: {node_type}")
        return self._nodes[node_type]

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
