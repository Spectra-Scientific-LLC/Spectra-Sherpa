"""
DAG Workflow Executor.

Handles execution of workflows represented as directed acyclic graphs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass
from enum import Enum
import asyncio
import hashlib
import json
import warnings

from .node_base import Node, NodeStatus, node_registry
from .meta_helpers import safe_get_coord

# Try to import NDDataset for type checking
try:
    from spectrochempy import NDDataset
    HAS_NDDATASET = True
except ImportError:
    NDDataset = None
    HAS_NDDATASET = False

# SpectralResult removed - using NDDataset-only
HAS_SPECTRAL_RESULT = False
SpectralResult = None

# Import unit validation from app/lib
try:
    from app.lib.spectral.validators import validate_and_normalize_units
    HAS_UNIT_VALIDATION = True
except ImportError:
    validate_and_normalize_units = None
    HAS_UNIT_VALIDATION = False


def _validate_spectral_units(
    datasets: List[Any],
    operation: str,
) -> List[Any]:
    """
    Validate and normalize spectral units across multiple datasets.

    Uses the "warning + auto-convert" policy: if incompatible units are
    detected (e.g., mixing Absorbance and Transmittance), logs a warning
    and auto-converts all datasets to Absorbance.

    Args:
        datasets: List of NDDataset objects to validate
        operation: Name of the operation (for warning messages)

    Returns:
        List of datasets with compatible units (possibly auto-converted)
    """
    if not HAS_UNIT_VALIDATION or not HAS_NDDATASET:
        return datasets

    # Filter to only NDDataset objects
    nddatasets = [d for d in datasets if isinstance(d, NDDataset)]
    if len(nddatasets) < 2:
        return datasets

    # Validate and normalize units
    normalized = validate_and_normalize_units(nddatasets, operation)

    # Replace in original list
    result = []
    norm_idx = 0
    for d in datasets:
        if isinstance(d, NDDataset):
            result.append(normalized[norm_idx])
            norm_idx += 1
        else:
            result.append(d)

    return result


def _validate_port_type(
    data: Any,
    expected_type: str,
    port_name: str,
    source_node_id: str,
    target_node_id: str,
    strict: bool = False,
) -> None:
    """
    Validate that data matches the expected port type.

    Port types:
    - "dataset": Expects NDDataset (SpectroChemPy smart array)
    - "array": Expects list, tuple, or numpy array
    - "model": Expects fitted model object
    - "target": Expects array-like (concentrations, labels)
    - "config": Expects dict

    Args:
        data: The data to validate
        expected_type: The expected port type
        port_name: Name of the port for error messages
        source_node_id: ID of the node providing the data
        target_node_id: ID of the node receiving the data
        strict: If True, raise error on mismatch. If False, warn only.

    Raises:
        TypeError: If strict=True and type doesn't match
    """
    import numpy as np

    type_checks = {
        "dataset": lambda d: HAS_NDDATASET and isinstance(d, NDDataset),
        "array": lambda d: isinstance(d, (list, tuple, np.ndarray)) or (HAS_NDDATASET and isinstance(d, NDDataset)),
        "model": lambda d: hasattr(d, "fit") or hasattr(d, "transform") or hasattr(d, "predict"),
        "target": lambda d: isinstance(d, (list, tuple, np.ndarray)) or (HAS_NDDATASET and isinstance(d, NDDataset)),
        "config": lambda d: isinstance(d, dict),
    }

    # Skip validation for unknown types
    if expected_type not in type_checks:
        return

    # Check type
    is_valid = type_checks[expected_type](data)

    if not is_valid:
        actual_type = type(data).__name__
        msg = (
            f"Port type mismatch: '{port_name}' on node '{target_node_id}' "
            f"expects '{expected_type}' but received '{actual_type}' from node '{source_node_id}'. "
        )

        if expected_type == "dataset" and not HAS_NDDATASET:
            msg += "SpectroChemPy NDDataset not available."
        elif expected_type == "dataset":
            msg += (
                "Upstream node should return NDDataset with coordinates attached, "
                "not raw arrays. This ensures X-axis (wavenumbers) stays coupled with data."
            )

        if strict:
            raise TypeError(msg)
        else:
            warnings.warn(msg, UserWarning, stacklevel=3)

    # Additional coordinate validation for datasets
    # This catches mismatched axes that could cause cryptic errors downstream
    if is_valid and expected_type == "dataset" and HAS_NDDATASET and isinstance(data, NDDataset):
        coord_issues = []

        # Check X-axis (spectral dimension) exists and matches data shape
        x_coord = safe_get_coord(data, 'x')
        if x_coord is not None:
            x_len = len(x_coord.data) if hasattr(x_coord, 'data') else len(x_coord)
            data_spectral_dim = data.shape[-1] if len(data.shape) > 0 else 0
            if x_len != data_spectral_dim:
                coord_issues.append(
                    f"X-axis length ({x_len}) doesn't match spectral dimension ({data_spectral_dim})"
                )
        elif len(data.shape) > 0 and data.shape[-1] > 1:
            # Missing X-axis on multi-point data is a warning
            coord_issues.append(
                "No X-axis coordinates defined (wavenumbers will be unavailable for display)"
            )

        # Check for NaN in data
        if np.any(np.isnan(data.data)):
            coord_issues.append("Data contains NaN values")

        # Warn about coordinate issues (don't block execution)
        for issue in coord_issues:
            warnings.warn(
                f"Data integrity warning on '{port_name}' from node '{source_node_id}': {issue}",
                UserWarning,
                stacklevel=3,
            )



class WorkflowStatus(str, Enum):
    """Workflow execution status."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


@dataclass
class WorkflowEdge:
    """Represents a connection between two nodes in a workflow."""

    from_node: str  # source node ID
    to_node: str  # target node ID
    from_output: str = "default"  # output port name
    to_input: str = "default"  # input port name


@dataclass
class WorkflowNode:
    """Represents a node instance in a workflow."""

    node_id: str
    node_type: str
    parameters: Dict[str, Any]
    position: Optional[Dict[str, float]] = None  # x, y coordinates for UI


class DAGExecutor:
    """
    Executes workflows represented as directed acyclic graphs.

    Handles topological sorting, dependency resolution, and node execution.
    Supports caching to avoid re-executing unchanged nodes.
    """

    def __init__(self):
        """Initialize executor."""
        self.nodes: Dict[str, Node] = {}
        self.edges: List[WorkflowEdge] = []
        self.results: Dict[str, Any] = {}
        self.status: WorkflowStatus = WorkflowStatus.IDLE
        # Caching: store hash of params when node was last executed
        self._param_hashes: Dict[str, str] = {}
        # Track which nodes are "dirty" (need re-execution)
        self._dirty_nodes: Set[str] = set()

    def _compute_param_hash(self, node_id: str) -> str:
        """
        Compute a deterministic hash of node parameters.

        Args:
            node_id: Node ID to hash parameters for

        Returns:
            MD5 hash string of parameters
        """
        node = self.nodes.get(node_id)
        if not node:
            return ""
        try:
            # Sort keys for deterministic output
            param_str = json.dumps(node.parameters, sort_keys=True, default=str)
            return hashlib.md5(param_str.encode()).hexdigest()
        except Exception:
            # If params can't be serialized, always consider dirty
            return ""

    def _is_node_cached(self, node_id: str) -> bool:
        """
        Check if a node's cached result is still valid.

        A cached result is valid if:
        1. The node has been executed before (result exists)
        2. Parameters haven't changed since last execution
        3. All upstream dependencies are also cached

        Args:
            node_id: Node ID to check

        Returns:
            True if cached result is valid
        """
        # No cached result
        if node_id not in self.results:
            return False

        # Accept injected results (prediction API)
        if self._param_hashes.get(node_id) == "__injected__":
            return True

        # Parameters changed since last execution
        current_hash = self._compute_param_hash(node_id)
        if node_id not in self._param_hashes or self._param_hashes[node_id] != current_hash:
            return False

        # Check if any upstream dependency is dirty
        incoming_edges = [e for e in self.edges if e.to_node == node_id]
        for edge in incoming_edges:
            if not self._is_node_cached(edge.from_node):
                return False

        return True

    def invalidate_node(self, node_id: str) -> None:
        """
        Invalidate a node's cache (and all its downstream dependents).

        Args:
            node_id: Node ID to invalidate
        """
        if node_id in self.results:
            del self.results[node_id]
        if node_id in self._param_hashes:
            del self._param_hashes[node_id]

        # Invalidate all downstream nodes
        for edge in self.edges:
            if edge.from_node == node_id:
                self.invalidate_node(edge.to_node)

    def inject_result(self, node_id: str, result: Any) -> None:
        """
        Inject a pre-computed result for a node (used by prediction API).

        The node is treated as cached and will not be re-executed.

        Args:
            node_id: Node ID to inject result for
            result: Pre-computed result (typically an NDDataset)
        """
        self.results[node_id] = result
        self._param_hashes[node_id] = "__injected__"

    def find_entry_nodes(self) -> List[str]:
        """
        Find entry nodes (no incoming edges or data.* type).

        Returns:
            List of node IDs that are entry points
        """
        incoming = {e.to_node for e in self.edges}
        return [
            nid for nid in self.nodes
            if nid not in incoming
            or self.nodes[nid].metadata.node_type.startswith("data.")
        ]

    def find_exit_nodes(self) -> List[str]:
        """
        Find terminal/exit nodes (no outgoing edges).

        Returns:
            List of node IDs that are exit points
        """
        outgoing = {e.from_node for e in self.edges}
        return [nid for nid in self.nodes if nid not in outgoing]

    def validate(self) -> List[str]:
        """
        Validate the workflow before execution.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors: List[str] = []

        # Check for cycles (topological sort will fail if cycles exist)
        try:
            self._topological_sort()
        except ValueError as e:
            errors.append(str(e))
            return errors  # Can't continue validation if graph is cyclic

        # Check that multi-input nodes have all required inputs connected
        for node_id, node in self.nodes.items():
            if node.uses_named_ports() and node.metadata.input_ports:
                incoming_edges = [e for e in self.edges if e.to_node == node_id]
                connected_ports = set()

                for edge in incoming_edges:
                    port_name = edge.to_input
                    if port_name == "default":
                        # Legacy edge - assign to first available port
                        port_idx = len(connected_ports)
                        if port_idx < len(node.metadata.input_ports):
                            port_name = node.metadata.input_ports[port_idx].name
                    connected_ports.add(port_name)

                # Check required ports
                for port in node.metadata.input_ports:
                    if port.required and port.name not in connected_ports:
                        errors.append(
                            f"Node '{node_id}' ({node.metadata.label}): "
                            f"Required input port '{port.label}' is not connected"
                        )

        # Check that all non-source nodes have at least one input
        deps = self._get_dependencies()
        for node_id, dep_list in deps.items():
            node = self.nodes[node_id]
            # Skip source nodes (no input_types or first input_type is empty)
            is_source = (
                not node.metadata.input_types or
                node.metadata.input_types == [""] or
                node.metadata.node_type.startswith("data.")
            )
            if not is_source and len(dep_list) == 0:
                errors.append(
                    f"Node '{node_id}' ({node.metadata.label}): "
                    f"Has no input connections"
                )

        return errors

    def add_node(self, workflow_node: WorkflowNode) -> None:
        """
        Add a node to the workflow.

        Args:
            workflow_node: WorkflowNode configuration
        """
        node = node_registry.create_node(
            node_type=workflow_node.node_type,
            node_id=workflow_node.node_id,
            parameters=workflow_node.parameters,
        )
        self.nodes[workflow_node.node_id] = node

    def add_edge(self, edge: WorkflowEdge) -> None:
        """
        Add an edge (connection) between two nodes.

        Args:
            edge: WorkflowEdge connecting two nodes
        """
        if edge.from_node not in self.nodes:
            raise ValueError(f"Source node {edge.from_node} not found")
        if edge.to_node not in self.nodes:
            raise ValueError(f"Target node {edge.to_node} not found")

        self.edges.append(edge)

    def _get_dependencies(self) -> Dict[str, List[str]]:
        """
        Build dependency graph.

        Returns:
            Dict mapping node_id to list of nodes it depends on
        """
        deps: Dict[str, List[str]] = {node_id: [] for node_id in self.nodes}

        for edge in self.edges:
            deps[edge.to_node].append(edge.from_node)

        return deps

    def _topological_sort(self) -> List[str]:
        """
        Perform topological sort to determine execution order.

        Returns:
            List of node IDs in execution order

        Raises:
            ValueError: If workflow contains cycles
        """
        deps = self._get_dependencies()

        # Count incoming edges for each node
        in_degree = {node_id: len(dep_list) for node_id, dep_list in deps.items()}

        # Queue of nodes with no dependencies
        queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            # Pop node with no dependencies
            node_id = queue.pop(0)
            result.append(node_id)

            # Find all nodes that depend on this one
            for edge in self.edges:
                if edge.from_node == node_id:
                    target = edge.to_node
                    in_degree[target] -= 1
                    if in_degree[target] == 0:
                        queue.append(target)

        # Check for cycles
        if len(result) != len(self.nodes):
            raise ValueError("Workflow contains cycles - not a valid DAG")

        return result

    def _get_node_inputs(self, node_id: str, validate_types: bool = True) -> Tuple[List[Any], Dict[str, Any]]:
        """
        Get input data for a node from upstream node results.

        For nodes with named input_ports: returns ([], {port_name: data})
        For legacy nodes: returns ([data1, data2, ...], {})

        Args:
            node_id: ID of node to get inputs for
            validate_types: If True, validate port types and warn on mismatches

        Returns:
            Tuple of (positional_inputs, named_inputs)
        """
        node = self.nodes[node_id]

        # Build port type lookup for validation
        port_types: Dict[str, str] = {}
        if node.metadata and node.metadata.input_ports:
            for port in node.metadata.input_ports:
                port_types[port.name] = port.port_type

        # Find all edges that connect to this node
        incoming_edges = [e for e in self.edges if e.to_node == node_id]

        # Check if node uses named input ports
        if node.uses_named_ports():
            # Build kwargs dict by port name
            named_inputs: Dict[str, Any] = {}
            for edge in incoming_edges:
                if edge.from_node not in self.results:
                    raise ValueError(
                        f"Node {edge.from_node} has not been executed yet (required by {node_id})"
                    )
                port_name = edge.to_input
                if port_name == "default":
                    # If edge uses legacy "default" port, try to infer from port order
                    # This provides backward compatibility for existing workflows
                    port_idx = len(named_inputs)
                    if node.metadata.input_ports and port_idx < len(node.metadata.input_ports):
                        port_name = node.metadata.input_ports[port_idx].name
                    else:
                        port_name = f"input_{port_idx}"

                # Extract specific output from multi-output nodes
                result = self.results[edge.from_node]
                data = None
                if isinstance(result, dict):
                    if edge.from_output and edge.from_output != "default":
                        # Multi-output node: extract specific output port
                        if edge.from_output not in result:
                            raise ValueError(
                                f"Output port '{edge.from_output}' not found in results from node {edge.from_node}. "
                                f"Available outputs: {list(result.keys())}"
                            )
                        data = result[edge.from_output]
                    elif "default" in result:
                        # Multi-output node with explicit default port
                        data = result["default"]
                    else:
                        # Dict output without explicit ports
                        data = result
                else:
                    # Single-output node
                    data = result

                # Validate port type if enabled
                if validate_types and port_name in port_types:
                    _validate_port_type(
                        data=data,
                        expected_type=port_types[port_name],
                        port_name=port_name,
                        source_node_id=edge.from_node,
                        target_node_id=node_id,
                        strict=False,  # Warn only, don't block execution
                    )

                named_inputs[port_name] = data

            # Validate and normalize spectral units for multi-input nodes
            if validate_types and len(named_inputs) > 1:
                all_values = list(named_inputs.values())
                normalized = _validate_spectral_units(all_values, node.metadata.label if node.metadata else node_id)
                # Update named_inputs with normalized values
                for i, key in enumerate(named_inputs.keys()):
                    named_inputs[key] = normalized[i]

            return [], named_inputs
        else:
            # Legacy: return positional inputs sorted by port name
            incoming_edges.sort(key=lambda e: e.to_input)
            positional_inputs = []
            for idx, edge in enumerate(incoming_edges):
                if edge.from_node not in self.results:
                    raise ValueError(
                        f"Node {edge.from_node} has not been executed yet (required by {node_id})"
                    )

                # Extract specific output from multi-output nodes
                result = self.results[edge.from_node]
                data = None
                if isinstance(result, dict):
                    if edge.from_output and edge.from_output != "default":
                        # Multi-output node: extract specific output port
                        if edge.from_output not in result:
                            raise ValueError(
                                f"Output port '{edge.from_output}' not found in results from node {edge.from_node}. "
                                f"Available outputs: {list(result.keys())}"
                            )
                        data = result[edge.from_output]
                    elif "default" in result:
                        # Multi-output node with explicit default port
                        data = result["default"]
                    else:
                        # Dict output without explicit ports
                        data = result
                else:
                    # Single-output node
                    data = result

                # Validate port type for legacy single-input nodes (assume first input_type)
                if validate_types and node.metadata and node.metadata.input_types:
                    if idx < len(node.metadata.input_types):
                        expected = node.metadata.input_types[idx]
                        if expected == "NDDataset":
                            _validate_port_type(
                                data=data,
                                expected_type="dataset",
                                port_name=f"input_{idx}",
                                source_node_id=edge.from_node,
                                target_node_id=node_id,
                                strict=False,
                            )

                positional_inputs.append(data)

            # Validate and normalize spectral units for multi-input nodes
            if validate_types and len(positional_inputs) > 1:
                positional_inputs = _validate_spectral_units(
                    positional_inputs,
                    node.metadata.label if node.metadata else node_id
                )

            return positional_inputs, {}

    async def execute(
        self, initial_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute the workflow.

        Args:
            initial_data: Optional dict of node_id -> config for source nodes.
                         This is used to configure DATA nodes with experiment IDs,
                         file paths, etc. It is NOT passed as pre-computed results.

        Returns:
            Dict mapping node_id to execution results

        Raises:
            ValueError: If workflow is invalid or execution fails
        """
        try:
            self.status = WorkflowStatus.RUNNING

            # Validate workflow before execution
            validation_errors = self.validate()
            if validation_errors:
                raise ValueError(
                    "Workflow validation failed:\n" + "\n".join(f"  - {e}" for e in validation_errors)
                )

            # Inject initial_data as parameters into DATA nodes
            if initial_data:
                for node_id, config in initial_data.items():
                    if node_id in self.nodes:
                        node = self.nodes[node_id]
                        # Merge initial config into node parameters
                        if isinstance(config, dict):
                            node.parameters.update(config)

            # Get execution order
            execution_order = self._topological_sort()

            # Execute nodes in order (with caching)
            for node_id in execution_order:
                node = self.nodes[node_id]

                # Check if we can use cached result
                if self._is_node_cached(node_id):
                    print(f"Using cached result: {node_id} ({node.metadata.label})")
                    continue

                # Get inputs from upstream nodes (positional or named)
                positional_inputs, named_inputs = self._get_node_inputs(node_id)

                # Execute node with appropriate calling convention
                print(f"Executing node: {node_id} ({node.metadata.label})")
                if named_inputs:
                    result = await node.run(**named_inputs)
                else:
                    result = await node.run(*positional_inputs)

                # Store result and param hash for caching
                self.results[node_id] = result
                self._param_hashes[node_id] = self._compute_param_hash(node_id)
                print(f"  ✓ Completed: {node_id} (status: {node.status.value})")

            self.status = WorkflowStatus.COMPLETED
            return self.results

        except Exception as e:
            self.status = WorkflowStatus.ERROR
            raise ValueError(f"Workflow execution failed: {str(e)}") from e

    async def execute_node(
        self, node_id: str, initial_data: Optional[Dict[str, Any]] = None
    ) -> Any:
        """
        Execute a single node (and its dependencies if needed).

        Args:
            node_id: ID of node to execute
            initial_data: Optional dict of node_id -> config for source nodes.
                         This is used to configure DATA nodes with experiment IDs,
                         file paths, etc.

        Returns:
            Result of node execution

        Raises:
            ValueError: If node not found or execution fails
        """
        if node_id not in self.nodes:
            raise ValueError(f"Node {node_id} not found in workflow")

        # Inject initial_data as parameters into DATA nodes
        if initial_data:
            for data_node_id, config in initial_data.items():
                if data_node_id in self.nodes:
                    node = self.nodes[data_node_id]
                    # Merge initial config into node parameters
                    if isinstance(config, dict):
                        node.parameters.update(config)

        # Get dependencies for this node
        deps = self._get_dependencies()
        nodes_to_execute = self._get_execution_path(node_id, deps)

        # Execute dependencies in order (with caching)
        executed_in_this_run = []
        for dep_node_id in nodes_to_execute:
            node = self.nodes[dep_node_id]

            # Check if we can use cached result
            if self._is_node_cached(dep_node_id):
                print(f"Using cached result: {dep_node_id} ({node.metadata.label})")
                # Still include in results even if cached
                if dep_node_id not in executed_in_this_run:
                    executed_in_this_run.append(dep_node_id)
                continue

            # Execute the node
            positional_inputs, named_inputs = self._get_node_inputs(dep_node_id)
            print(f"Executing node: {dep_node_id} ({node.metadata.label})")
            if named_inputs:
                result = await node.run(**named_inputs)
            else:
                result = await node.run(*positional_inputs)

            # Store result and param hash
            self.results[dep_node_id] = result
            self._param_hashes[dep_node_id] = self._compute_param_hash(dep_node_id)
            executed_in_this_run.append(dep_node_id)
            print(f"  ✓ Completed: {dep_node_id} (status: {node.status.value})")

        # Return all results from this execution (target + dependencies)
        return {nid: self.results[nid] for nid in executed_in_this_run}

    def _get_execution_path(
        self, node_id: str, deps: Dict[str, List[str]]
    ) -> List[str]:
        """
        Get list of nodes that need to be executed for a given node.

        Args:
            node_id: Target node ID
            deps: Dependency graph

        Returns:
            List of node IDs in execution order
        """
        visited: Set[str] = set()
        path: List[str] = []

        def dfs(current: str):
            if current in visited:
                return
            visited.add(current)

            # Visit dependencies first
            for dep in deps.get(current, []):
                dfs(dep)

            path.append(current)

        dfs(node_id)
        return path

    def clear(self) -> None:
        """Clear all nodes, edges, results, and cache."""
        self.nodes = {}
        self.edges = []
        self.results = {}
        self.status = WorkflowStatus.IDLE
        self._param_hashes = {}
        self._dirty_nodes = set()

    def get_status(self) -> Dict[str, Any]:
        """
        Get current workflow status.

        Returns:
            Dict with workflow and node statuses
        """
        return {
            "workflow_status": self.status.value,
            "total_nodes": len(self.nodes),
            "completed_nodes": sum(
                1 for n in self.nodes.values() if n.status == NodeStatus.COMPLETED
            ),
            "node_statuses": {
                node_id: node.status.value for node_id, node in self.nodes.items()
            },
        }
