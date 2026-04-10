"""
DAG Workflow Executor.

Handles execution of workflows represented as directed acyclic graphs.
Supports offloading CPU-bound node execution to a ProcessPoolExecutor
so the asyncio event loop stays responsive in multi-user deployments.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from spectra_sherpa.app.core.config import settings
from spectra_sherpa.app.lib.scp_compat import HAS_SCP, NDDataset

from .executor_pool import _run_node_in_worker, get_default_pool, set_default_pool  # noqa: F401
from .executor_types import (  # noqa: F401 — re-exported for backward compat
    ValidationIssue,
    ValidationResult,
    WorkflowEdge,
    WorkflowNode,
    WorkflowStatus,
)
from .executor_validation import (  # noqa: F401 — tests import/monkeypatch these
    HAS_NDDATASET,
    _category_from_type_ref,
    _is_dataset,
    _validate_port_type,
    _validate_spectral_units,
)
from .graph_utils import Edge as _Edge
from .graph_utils import build_dependency_map, topological_sort
from .node_base import Node, NodeResult, NodeStatus, node_registry

logger = logging.getLogger(__name__)


class DAGExecutor:
    """
    Executes workflows represented as directed acyclic graphs.

    Handles topological sorting, dependency resolution, and node execution.
    Supports caching to avoid re-executing unchanged nodes.
    """

    def __init__(self, process_pool=None, model_store: Any = None):
        """Initialize executor.

        Args:
            process_pool: Optional ProcessPoolExecutor for offloading CPU-bound
                nodes. When provided, nodes (except data-source nodes) run in
                worker processes, keeping the event loop responsive.
            model_store: Optional ModelStore for persisting model artifacts.
                When provided, nodes that emit ``_model_artifact`` in their
                result dict will have arrays saved to disk automatically.
                Falls back to the global ``get_model_store()`` singleton if
                not provided.
        """
        self.nodes: Dict[str, Node] = {}
        self.edges: List[WorkflowEdge] = []
        self.results: Dict[str, Any] = {}
        self.diagnostics: Dict[str, Dict[str, Any]] = {}
        self.status: WorkflowStatus = WorkflowStatus.IDLE
        self._process_pool = process_pool if process_pool is not None else get_default_pool()
        self.model_store = model_store
        # Artifacts saved during this execution (for DB record creation by callers)
        self.saved_artifacts: List[Dict[str, Any]] = []
        # Caching: store hash of params when node was last executed
        self._param_hashes: Dict[str, str] = {}
        # Track which nodes are "dirty" (need re-execution)
        self._dirty_nodes: Set[str] = set()

    def __getstate__(self) -> Dict[str, Any]:
        """Exclude unpicklable ProcessPoolExecutor from serialization.

        Used by copy.deepcopy() in the headless prediction API to clone
        executors for concurrent request isolation.
        """
        state = self.__dict__.copy()
        # Exclude the unpicklable process pool (contains thread locks, file descriptors)
        state["_process_pool"] = None
        return state

    def __setstate__(self, state: Dict[str, Any]) -> None:
        """Restore executor state, reconnecting to global process pool.

        The process pool is restored from the global pool set at app startup,
        ensuring all cloned executors share the same worker pool.
        """
        self.__dict__.update(state)
        # Restore reference to global process pool
        self._process_pool = get_default_pool()

    def _resolve_model_store(self) -> Any:
        """Return the active ModelStore: explicit > global singleton > None."""
        if self.model_store is not None:
            return self.model_store
        try:
            from spectra_sherpa.app.services.model_store import get_model_store

            return get_model_store()
        except RuntimeError:
            return None

    def _process_model_artifact(self, node_id: str) -> None:
        """Save model artifact to disk if the node produced one.

        Training nodes include ``_model_artifact`` in their result dict.
        This method generates a UUID, persists the artifact to disk via
        the ModelStore (explicit or global singleton), replaces the payload
        with a ``model_id`` reference, and records the artifact metadata
        in ``self.saved_artifacts`` for DB row creation by the caller.
        """
        result = self.results.get(node_id)
        if not isinstance(result, dict) or "_model_artifact" not in result:
            return

        artifact_uid = str(uuid.uuid4())
        store = self._resolve_model_store()
        if store is not None:
            try:
                artifact = result["_model_artifact"]
                metadata = artifact.get("metadata", {})
                arrays = artifact.get("arrays", {})
                metadata.setdefault("node_id", artifact.get("node_id", node_id))
                integrity_hash = store.save(artifact_uid, metadata, arrays)

                # Only pop after successful save — avoid losing data on failure
                result.pop("_model_artifact")
                result["model_id"] = artifact_uid

                # Record for DB creation by the caller
                self.saved_artifacts.append(
                    {
                        "artifact_uid": artifact_uid,
                        "node_id": metadata.get("node_id", node_id),
                        "model_type": metadata.get("model_type", "unknown"),
                        "n_features": metadata.get("n_features", 0),
                        "n_components": metadata.get("n_components"),
                        "classes_json": json.dumps(metadata["classes"]) if "classes" in metadata else None,
                        "feature_axis_json": (
                            json.dumps(metadata["feature_axis"]) if "feature_axis" in metadata else None
                        ),
                        "metrics_json": json.dumps(metadata["metrics"]) if "metrics" in metadata else None,
                        "preprocessing_summary": (
                            json.dumps(metadata["preprocessing_chain"]) if "preprocessing_chain" in metadata else None
                        ),  # noqa: E501
                        "integrity_hash": integrity_hash,
                        "artifact_dir": str(store._artifact_dir(artifact_uid)),
                    }
                )

                logger.info(
                    "Saved model artifact %s (type=%s) from node %s",
                    artifact_uid,
                    metadata.get("model_type", "unknown"),
                    node_id,
                )
            except Exception:
                logger.exception("Failed to save model artifact for node %s", node_id)
                raise  # Fail-fast: don't let a run appear successful while artifact is lost
        else:
            # Fail closed: a training run that emits an artifact must not
            # appear successful if persistence is unavailable.
            raise RuntimeError(
                f"ModelStore not initialized — cannot persist artifact from node {node_id}. "
                "Ensure init_model_store() is called at startup."
            )

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
            return hashlib.md5(param_str.encode(), usedforsecurity=False).hexdigest()
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
            nid
            for nid in self.nodes
            if nid not in incoming
            or (
                self.nodes[nid].metadata is not None
                and self.nodes[nid].metadata.node_type.startswith("data.")  # type: ignore[union-attr]
            )
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
        return self.validate_full().to_error_strings()

    def validate_full(self) -> ValidationResult:
        """
        Full workflow validation with structured results.

        Checks graph structure, required ports, parameters, and port types.

        Returns:
            ValidationResult with categorized errors and warnings
        """
        issues: List[ValidationIssue] = []

        # 1. Cycle detection (topological sort will fail if cycles exist)
        try:
            self._topological_sort()
        except ValueError as e:
            issues.append(ValidationIssue("error", None, None, str(e)))
            return ValidationResult(issues)  # Can't continue if cyclic

        # 2. Required port connections
        issues.extend(self._validate_port_connections())

        # 3. Non-source nodes must have inputs
        issues.extend(self._validate_node_inputs())

        # 4. Required parameters and value constraints
        issues.extend(self._validate_parameters())

        # 5. Port type compatibility between connected nodes
        issues.extend(self._validate_port_types())

        return ValidationResult(issues)

    def _validate_port_connections(self) -> List[ValidationIssue]:
        """Check that multi-input nodes have all required inputs connected."""
        issues: List[ValidationIssue] = []
        for node_id, node in self.nodes.items():
            if node.uses_named_ports() and node.metadata is not None and node.metadata.input_ports:
                incoming_edges = [e for e in self.edges if e.to_node == node_id]
                connected_ports: Set[str] = set()

                for edge in incoming_edges:
                    port_name = edge.to_input
                    if port_name == "default":
                        port_idx = len(connected_ports)
                        if port_idx < len(node.metadata.input_ports):
                            port_name = node.metadata.input_ports[port_idx].name
                    connected_ports.add(port_name)

                for port in node.metadata.input_ports:
                    if port.required and port.name not in connected_ports:
                        issues.append(
                            ValidationIssue(
                                "error",
                                node_id,
                                port.name,
                                f"Node '{node_id}' ({node.metadata.label}): "
                                f"Required input port '{port.label}' is not connected",
                            )
                        )

                # Check cardinality: non-variadic ports must not receive multiple edges
                port_edge_counts: dict[str, int] = {}
                for edge in incoming_edges:
                    port_name = edge.to_input or "default"
                    port_edge_counts[port_name] = port_edge_counts.get(port_name, 0) + 1

                variadic_names = {p.name for p in node.metadata.input_ports if p.variadic}
                for port_name, count in port_edge_counts.items():
                    if count > 1 and port_name not in variadic_names:
                        issues.append(
                            ValidationIssue(
                                "error",
                                node_id,
                                port_name,
                                f"Node '{node_id}' ({node.metadata.label}): "
                                f"Port '{port_name}' accepts only one connection but has {count}",
                            )
                        )
        return issues

    def _validate_node_inputs(self) -> List[ValidationIssue]:
        """Check that all non-source nodes have at least one input."""
        issues: List[ValidationIssue] = []
        deps = self._get_dependencies()
        for node_id, dep_list in deps.items():
            node = self.nodes[node_id]
            is_source = (
                node.metadata is None
                or not node.metadata.input_types
                or node.metadata.input_types == [""]
                or node.metadata.node_type.startswith("data.")
            )
            if not is_source and len(dep_list) == 0:
                assert node.metadata is not None
                issues.append(
                    ValidationIssue(
                        "error",
                        node_id,
                        None,
                        f"Node '{node_id}' ({node.metadata.label}): Has no input connections",
                    )
                )
        return issues

    def _validate_parameters(self) -> List[ValidationIssue]:
        """Validate required parameters have values and constraints are met."""
        issues: List[ValidationIssue] = []
        for node_id, node in self.nodes.items():
            if not node.metadata:
                continue
            for param_def in node.metadata.parameters:
                value = node.parameters.get(param_def.name)
                has_value = value is not None and value != ""
                has_default = param_def.default is not None

                # Required parameter missing
                if param_def.required and not has_value and not has_default:
                    issues.append(
                        ValidationIssue(
                            "error",
                            node_id,
                            None,
                            f"Node '{node_id}' ({node.metadata.label}): "
                            f"Missing required parameter '{param_def.label}'",
                        )
                    )
                    continue

                if not has_value:
                    continue

                # Number range validation
                if param_def.param_type == "number" and isinstance(value, (int, float)):
                    if param_def.min_value is not None and value < param_def.min_value:
                        issues.append(
                            ValidationIssue(
                                "error",
                                node_id,
                                None,
                                f"Node '{node_id}' ({node.metadata.label}): "
                                f"Parameter '{param_def.label}' value {value} "
                                f"below minimum {param_def.min_value}",
                            )
                        )
                    if param_def.max_value is not None and value > param_def.max_value:
                        issues.append(
                            ValidationIssue(
                                "error",
                                node_id,
                                None,
                                f"Node '{node_id}' ({node.metadata.label}): "
                                f"Parameter '{param_def.label}' value {value} "
                                f"above maximum {param_def.max_value}",
                            )
                        )

                # Select parameter: value must be in options
                if param_def.param_type == "select" and param_def.options:
                    option_values = [o["value"] if isinstance(o, dict) else o for o in param_def.options]
                    if value not in option_values:
                        issues.append(
                            ValidationIssue(
                                "warning",
                                node_id,
                                None,
                                f"Node '{node_id}' ({node.metadata.label}): "
                                f"Parameter '{param_def.label}' value '{value}' "
                                f"not in options",
                            )
                        )
        return issues

    def _validate_port_types(self) -> List[ValidationIssue]:
        """Check port type compatibility between connected nodes."""
        issues: List[ValidationIssue] = []
        try:
            from spectra_sherpa.app.types import type_registry

            if not type_registry.is_loaded:
                return issues
        except Exception:
            return issues

        for edge in self.edges:
            source_node = self.nodes.get(edge.from_node)
            target_node = self.nodes.get(edge.to_node)
            if not source_node or not target_node:
                continue

            # Resolve source output type_ref
            source_type_ref = None
            if source_node.metadata and source_node.metadata.output_ports:
                for port in source_node.metadata.output_ports:
                    if port.name == edge.from_output:
                        source_type_ref = port.type_ref
                        break
                if source_type_ref is None and edge.from_output == "default" and source_node.metadata.output_ports:
                    source_type_ref = source_node.metadata.output_ports[0].type_ref

            # Resolve target input type_ref
            target_type_ref = None
            if target_node.metadata and target_node.metadata.input_ports:
                for port in target_node.metadata.input_ports:
                    if port.name == edge.to_input:
                        target_type_ref = port.type_ref
                        break
                if target_type_ref is None and edge.to_input == "default" and target_node.metadata.input_ports:
                    target_type_ref = target_node.metadata.input_ports[0].type_ref

            # Both ports have type_refs: check compatibility
            if source_type_ref and target_type_ref:
                is_ok, reason = type_registry.is_compatible(source_type_ref, target_type_ref)
                if not is_ok:
                    src_label = source_node.metadata.label if source_node.metadata else edge.from_node
                    tgt_label = target_node.metadata.label if target_node.metadata else edge.to_node
                    issues.append(
                        ValidationIssue(
                            "warning",
                            edge.to_node,
                            edge.to_input,
                            f"Port type mismatch: {src_label} output '{edge.from_output}' -> "
                            f"{tgt_label} input '{edge.to_input}': {reason}",
                        )
                    )
        return issues

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

    def _normalized_edges(self) -> List[_Edge]:
        """Convert executor WorkflowEdge objects to graph_utils Edge tuples."""
        return [_Edge(e.from_node, e.to_node, e.from_output, e.to_input) for e in self.edges]

    def _get_dependencies(self) -> Dict[str, List[str]]:
        """
        Build dependency graph.

        Returns:
            Dict mapping node_id to list of nodes it depends on
        """
        return build_dependency_map(list(self.nodes.keys()), self._normalized_edges())

    def _topological_sort(self) -> List[str]:
        """
        Perform topological sort to determine execution order.

        Returns:
            List of node IDs in execution order

        Raises:
            ValueError: If workflow contains cycles
        """
        return topological_sort(list(self.nodes.keys()), self._normalized_edges())

    def _should_offload(self, node: Node) -> bool:
        """Whether a node should run in the process pool.

        Data-source nodes may open async DB sessions inside execute(),
        so they stay in-process.  Custom algo nodes set
        ``offload_to_pool=False`` because process-pool workers only
        import built-in node modules.
        """
        if self._process_pool is None:
            return False
        if node.metadata and node.metadata.category == "data":
            return False
        if node.metadata and node.metadata.policy and not node.metadata.policy.offload_to_pool:
            return False
        return True

    @staticmethod
    def _sanitize_for_pool(value: Any) -> Any:
        """Guard: reject any stray NDDataset at the pool boundary.

        All nodes must emit SherpaDataset.  Use ``scp_roundtrip()`` or
        ``from_nddataset()`` inside the node's ``execute()`` method.
        """
        if HAS_SCP and isinstance(value, NDDataset):
            raise TypeError(
                "NDDataset reached pool boundary — node must emit SherpaDataset. "
                "Use scp_roundtrip() or from_nddataset() in the node's execute() method."
            )
        return value

    async def _run_one_node(
        self,
        node: Node,
        positional_inputs: List[Any],
        named_inputs: Dict[str, Any],
        timeout: float,
    ) -> NodeResult:
        """Execute a single node, offloading to the process pool when possible.

        Falls back to in-process execution if the pool submission fails
        (e.g. unpicklable input or broken worker).
        """
        if self._should_offload(node):
            loop = asyncio.get_running_loop()
            try:
                # Sanitise inputs: convert NDDataset → SherpaDataset so
                # only numpy arrays cross the process boundary.
                safe_pos = tuple(self._sanitize_for_pool(v) for v in positional_inputs) if not named_inputs else ()
                safe_named = {k: self._sanitize_for_pool(v) for k, v in named_inputs.items()} if named_inputs else {}

                assert node.metadata is not None
                future = loop.run_in_executor(
                    self._process_pool,
                    _run_node_in_worker,
                    node.metadata.node_type,
                    node.node_id,
                    dict(node.parameters),
                    safe_pos,
                    safe_named,
                )
                return await asyncio.wait_for(future, timeout=timeout)
            except Exception as exc:
                # If the failure looks like a pickle/serialization issue,
                # a broken worker, or a shut-down pool, fall back to
                # in-process execution.
                from concurrent.futures.process import BrokenProcessPool

                exc_str = str(exc)
                is_pool_error = isinstance(exc, BrokenProcessPool) or any(
                    kw in exc_str
                    for kw in (
                        "pickle",
                        "Pickling",
                        "serialize",
                        "can't pickle",
                        "after shutdown",
                    )
                )
                if is_pool_error:
                    logger.warning(
                        "Pool offload failed for %s (%s), running in-process: %s",
                        node.node_id,
                        node.metadata.label if node.metadata else "?",
                        exc_str,
                    )
                else:
                    raise

        # In-process path (data nodes, pool unavailable, or fallback).
        # NOTE: We do NOT sanitize (NDDataset→SherpaDataset) here because
        # some nodes pass inputs directly to SpectroChemPy functions that
        # require NDDataset.  JSON-safety is ensured at the API boundary
        # by serialize_result() and _json_safe() in to_dict().
        if named_inputs:
            return await asyncio.wait_for(node.run(**named_inputs), timeout=timeout)
        else:
            return await asyncio.wait_for(node.run(*positional_inputs), timeout=timeout)

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
                port_types[port.name] = _category_from_type_ref(port.type_ref)

        # Find all edges that connect to this node
        incoming_edges = [e for e in self.edges if e.to_node == node_id]

        # Check if node uses named input ports
        if node.uses_named_ports():
            # Build variadic port lookup
            variadic_ports: set[str] = set()
            actual_port_names: set[str] = set()
            if node.metadata and node.metadata.input_ports:
                variadic_ports = {p.name for p in node.metadata.input_ports if p.variadic}
                actual_port_names = {p.name for p in node.metadata.input_ports}

            # Build kwargs dict by port name
            named_inputs: Dict[str, Any] = {}
            _legacy_port_counter = 0  # tracks positional index for legacy "default" inference
            for edge in incoming_edges:
                if edge.from_node not in self.results:
                    raise ValueError(f"Node {edge.from_node} has not been executed yet (required by {node_id})")
                port_name = edge.to_input
                if port_name == "default" and "default" not in actual_port_names:
                    # Legacy edge without explicit port — infer from port order
                    if (
                        node.metadata is not None
                        and node.metadata.input_ports
                        and _legacy_port_counter < len(node.metadata.input_ports)
                    ):
                        port_name = node.metadata.input_ports[_legacy_port_counter].name
                    else:
                        port_name = f"input_{_legacy_port_counter}"
                    _legacy_port_counter += 1

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

                # Variadic ports accumulate into lists; non-variadic overwrite
                if port_name in variadic_ports:
                    named_inputs.setdefault(port_name, []).append(data)
                else:
                    named_inputs[port_name] = data

            # Safety: reject multiple edges feeding a non-variadic port.
            # Note: a raw list value from a single edge is legitimate data
            # (e.g. explained_variance), so we count edges per port rather
            # than checking isinstance(value, list).
            _edge_counts: dict[str, int] = {}
            for edge in incoming_edges:
                _pn = edge.to_input
                if _pn == "default" and "default" not in actual_port_names:
                    if (
                        node.metadata
                        and node.metadata.input_ports
                        and _edge_counts.get("__legacy_idx", 0) < len(node.metadata.input_ports)
                    ):
                        _pn = node.metadata.input_ports[_edge_counts.get("__legacy_idx", 0)].name
                _edge_counts[_pn] = _edge_counts.get(_pn, 0) + 1
            for _pn, _count in _edge_counts.items():
                if _count > 1 and _pn not in variadic_ports:
                    raise ValueError(
                        f"Port '{_pn}' on node '{node_id}' received " f"{_count} edges but is not variadic"
                    )

            # Validate and normalize spectral units only for true spectral dataset ports.
            # Do NOT include target/config/model ports even if they are NDDataset objects
            # (e.g., class-label dataset on y port), or numeric conversion may fail.
            if validate_types and len(named_inputs) > 1:
                spectral_keys = [key for key in named_inputs.keys() if port_types.get(key) == "dataset"]
                if len(spectral_keys) > 1:
                    spectral_values = [named_inputs[key] for key in spectral_keys]
                    normalized = _validate_spectral_units(
                        spectral_values,
                        node.metadata.label if node.metadata else node_id,
                    )
                    for i, key in enumerate(spectral_keys):
                        named_inputs[key] = normalized[i]

            return [], named_inputs
        else:
            # Legacy: return positional inputs sorted by port name
            incoming_edges.sort(key=lambda e: e.to_input)
            positional_inputs = []
            for idx, edge in enumerate(incoming_edges):
                if edge.from_node not in self.results:
                    raise ValueError(f"Node {edge.from_node} has not been executed yet (required by {node_id})")

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

            # Validate and normalize spectral units only when we have 2+ spectral inputs.
            # Legacy nodes use input_types ordering; restrict to NDDataset-typed inputs.
            if validate_types and len(positional_inputs) > 1:
                spectral_indices: List[int] = []
                if node.metadata and node.metadata.input_types:
                    for i, expected in enumerate(node.metadata.input_types):
                        if i >= len(positional_inputs):
                            break
                        if expected == "NDDataset":
                            spectral_indices.append(i)
                else:
                    spectral_indices = list(range(len(positional_inputs)))

                if len(spectral_indices) > 1:
                    spectral_values = [positional_inputs[i] for i in spectral_indices]
                    normalized = _validate_spectral_units(
                        spectral_values, node.metadata.label if node.metadata else node_id
                    )
                    for idx, i in enumerate(spectral_indices):
                        positional_inputs[i] = normalized[idx]

            return positional_inputs, {}

    async def execute(
        self,
        initial_data: Optional[Dict[str, Any]] = None,
        status_callback: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Execute the workflow.

        Args:
            initial_data: Optional dict of node_id -> config for source nodes.
                         This is used to configure DATA nodes with experiment IDs,
                         file paths, etc. It is NOT passed as pre-computed results.
            status_callback: Optional async callback ``(node_id, status, error?) -> None``
                            called for per-node progress events (queued/running/completed/error).
                            Failures in the callback are silently ignored.

        Returns:
            Dict mapping node_id to execution results

        Raises:
            ValueError: If workflow is invalid or execution fails
        """

        async def _emit(nid: str, st: str, err: Optional[str] = None) -> None:
            if status_callback is not None:
                try:
                    await status_callback(nid, st, err)
                except Exception:
                    pass  # Never let broadcast failure affect execution

        try:
            self.status = WorkflowStatus.RUNNING
            self.saved_artifacts = []  # Reset for this execution

            # Validate workflow before execution
            validation_errors = self.validate()
            if validation_errors:
                raise ValueError("Workflow validation failed:\n" + "\n".join(f"  - {e}" for e in validation_errors))

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

            # Mark all nodes as queued
            for node_id in execution_order:
                await _emit(node_id, "queued")

            # Execute nodes in order (with caching)
            for node_id in execution_order:
                node = self.nodes[node_id]

                # Check if we can use cached result
                if self._is_node_cached(node_id):
                    logger.debug(
                        "Using cached result: %s (%s)", node_id, node.metadata.label if node.metadata else node_id
                    )
                    node.status = NodeStatus.COMPLETED
                    await _emit(node_id, "completed")
                    continue

                # Get inputs from upstream nodes (positional or named)
                positional_inputs, named_inputs = self._get_node_inputs(node_id)

                # Execute node (offloaded to process pool when available)
                node_timeout = settings.max_job_duration_sec
                label = node.metadata.label if node.metadata else node_id
                logger.debug("Executing node: %s (%s)", node_id, label)
                node.status = NodeStatus.RUNNING
                await _emit(node_id, "running")
                try:
                    result = await self._run_one_node(node, positional_inputs, named_inputs, node_timeout)
                except asyncio.TimeoutError:
                    err_msg = (
                        f"Node '{label}' exceeded {node_timeout}s timeout. "
                        f"Reduce dataset size or simplify parameters."
                    )
                    node.status = NodeStatus.ERROR
                    node.error_message = err_msg
                    await _emit(node_id, "error", err_msg)
                    raise ValueError(err_msg)
                except Exception as exc:
                    # Pool or in-process execution failure — status on the worker
                    # copy (if any) never propagates back, so mark the main-process
                    # node explicitly so get_status() reflects reality.
                    node.status = NodeStatus.ERROR
                    node.error_message = str(exc)
                    await _emit(node_id, "error", str(exc))
                    raise

                # Unpack NodeResult: store outputs for downstream, diagnostics separately
                if isinstance(result, NodeResult):
                    self.results[node_id] = result.outputs
                    self.diagnostics[node_id] = result.diagnostics
                else:
                    self.results[node_id] = result
                    self.diagnostics[node_id] = {}

                # Persist model artifact if present
                self._process_model_artifact(node_id)

                self._param_hashes[node_id] = self._compute_param_hash(node_id)
                # Pool workers mutate their own copy's status; the main-process
                # node stays in whatever state we set before offloading. Mark
                # completed explicitly so get_status() reports reality.
                node.status = NodeStatus.COMPLETED
                logger.debug("Completed: %s (status: %s)", node_id, node.status.value)
                await _emit(node_id, "completed")

            self.status = WorkflowStatus.COMPLETED
            return self.results

        except ImportError as e:
            self.status = WorkflowStatus.ERROR
            raise ValueError(str(e)) from e
        except Exception as e:
            self.status = WorkflowStatus.ERROR
            if not HAS_SCP and "NoneType" in str(e):
                raise ValueError(
                    f"Workflow execution failed: {e}. "
                    f"SpectroChemPy is not installed — install with: "
                    f"pip install spectra-sherpa[scp]"
                ) from e
            raise ValueError(f"Workflow execution failed: {str(e)}") from e

    async def execute_node(self, node_id: str, initial_data: Optional[Dict[str, Any]] = None) -> Any:
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
                logger.debug(
                    "Using cached result: %s (%s)", dep_node_id, node.metadata.label if node.metadata else dep_node_id
                )
                # Still include in results even if cached, and reflect the
                # cache hit as COMPLETED so get_status() doesn't report
                # stale "pending" for reused upstream dependencies.
                node.status = NodeStatus.COMPLETED
                if dep_node_id not in executed_in_this_run:
                    executed_in_this_run.append(dep_node_id)
                continue

            # Execute the node (offloaded to process pool when available)
            positional_inputs, named_inputs = self._get_node_inputs(dep_node_id)
            node_timeout = settings.max_job_duration_sec
            logger.debug("Executing node: %s (%s)", dep_node_id, node.metadata.label if node.metadata else dep_node_id)
            node.status = NodeStatus.RUNNING
            try:
                result = await self._run_one_node(node, positional_inputs, named_inputs, node_timeout)
            except asyncio.TimeoutError:
                label = node.metadata.label if node.metadata else dep_node_id
                err_msg = (
                    f"Node '{label}' exceeded {node_timeout}s timeout. " f"Reduce dataset size or simplify parameters."
                )
                node.status = NodeStatus.ERROR
                node.error_message = err_msg
                raise ValueError(err_msg)
            except Exception as exc:
                # Pool workers mutate a separate node instance; record the
                # error on the main-process copy so get_status() is truthful.
                node.status = NodeStatus.ERROR
                node.error_message = str(exc)
                raise

            # Unpack NodeResult
            if isinstance(result, NodeResult):
                self.results[dep_node_id] = result.outputs
                self.diagnostics[dep_node_id] = result.diagnostics
            else:
                self.results[dep_node_id] = result
                self.diagnostics[dep_node_id] = {}

            # Persist model artifact if present
            self._process_model_artifact(dep_node_id)

            self._param_hashes[dep_node_id] = self._compute_param_hash(dep_node_id)
            # Main-process status update: pool worker's status never flows back,
            # so set COMPLETED here once the result is in self.results.
            node.status = NodeStatus.COMPLETED
            executed_in_this_run.append(dep_node_id)
            logger.debug("Completed: %s (status: %s)", dep_node_id, node.status.value)

        # Return all results from this execution (target + dependencies)
        return {nid: self.results[nid] for nid in executed_in_this_run}

    def _get_execution_path(self, node_id: str, deps: Dict[str, List[str]]) -> List[str]:
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
        self.saved_artifacts = []

    def get_status(self) -> Dict[str, Any]:
        """
        Get current workflow status.

        Returns:
            Dict with workflow and node statuses
        """
        return {
            "workflow_status": self.status.value,
            "total_nodes": len(self.nodes),
            "completed_nodes": sum(1 for n in self.nodes.values() if n.status == NodeStatus.COMPLETED),
            "node_statuses": {node_id: node.status.value for node_id, node in self.nodes.items()},
        }
