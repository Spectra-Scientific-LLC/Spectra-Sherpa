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
import os
import uuid
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from spectra_sherpa.app.lib.data_roles import is_spectrum_only_node, require_data_role
from spectra_sherpa.core.execution_runtime import ExecutionRuntime

from .executor_pool import (
    IsolatedWorkerPool,
    WorkerExecutionContext,
    _run_node_in_worker,
    get_default_pool,
)  # noqa: F401
from .executor_pool import set_default_pool as set_default_pool
from .executor_types import (  # noqa: F401 — re-exported for backward compat
    ValidationIssue,
    ValidationResult,
    WorkflowEdge,
    WorkflowNode,
    WorkflowStatus,
)
from .executor_validation import (  # noqa: F401 — tests import/monkeypatch these
    _category_from_type_ref,
    _is_dataset,
    _validate_port_type,
)
from .graph_utils import Edge as _Edge
from .graph_utils import build_dependency_map, topological_sort
from .node_base import Node, NodeResult, NodeStatus, node_registry, resolved_runtime_worker_capabilities
from .transport import reject_spectrochempy_transport

logger = logging.getLogger(__name__)


class DAGExecutor:
    """
    Executes workflows represented as directed acyclic graphs.

    Handles topological sorting, dependency resolution, and node execution.
    Supports caching to avoid re-executing unchanged nodes.
    """

    def __init__(self, process_pool=None, runtime: ExecutionRuntime | None = None):
        """Initialize executor.

        Args:
            process_pool: Optional ProcessPoolExecutor for offloading CPU-bound
                nodes. When provided, nodes (except data-source nodes) run in
                worker processes, keeping the event loop responsive.
            runtime: Immutable timeout and artifact capabilities constructed
                by the SDK, workbench, or managed caller. An omitted runtime
                has no storage authority and uses the public local timeout.
        """
        self.nodes: Dict[str, Node] = {}
        self.edges: List[WorkflowEdge] = []
        self.results: Dict[str, Any] = {}
        self.diagnostics: Dict[str, Dict[str, Any]] = {}
        self.status: WorkflowStatus = WorkflowStatus.IDLE
        self._process_pool = process_pool if process_pool is not None else get_default_pool()
        self.runtime = runtime if runtime is not None else ExecutionRuntime()
        # Artifacts saved during this execution (for DB record creation by callers)
        self.saved_artifacts: List[Dict[str, Any]] = []
        # Caching: store hash of params when node was last executed
        self._param_hashes: Dict[str, str] = {}
        # Track which nodes are "dirty" (need re-execution)
        self._dirty_nodes: Set[str] = set()
        # A sheet opened from a campaign candidate keeps the campaign's folds:
        # its terminal evaluator is scored out of fold, never on fitted rows.
        self.fold_validation_plan: Any = None

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

    def _process_model_artifact(self, node_id: str) -> None:
        """Save model artifact to disk if the node produced one.

        Training nodes include ``_model_artifact`` in their result dict.
        This method generates a UUID, persists the artifact through the
        explicitly supplied write capability, replaces the payload
        with a ``model_id`` reference, and records the artifact metadata
        in ``self.saved_artifacts`` for DB row creation by the caller.
        """
        result = self.results.get(node_id)
        if not isinstance(result, dict) or "_model_artifact" not in result:
            return

        artifact_uid = str(uuid.uuid4())
        store = self.runtime.require_model_artifact_writer()
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
                    "feature_axis_json": (json.dumps(metadata["feature_axis"]) if "feature_axis" in metadata else None),
                    "metrics_json": json.dumps(metadata["metrics"]) if "metrics" in metadata else None,
                    "preprocessing_summary": (
                        json.dumps(metadata["preprocessing_chain"]) if "preprocessing_chain" in metadata else None
                    ),  # noqa: E501
                    "training_data_hash": metadata.get("training_data_hash"),
                    "training_scientific_digest": metadata.get("training_scientific_digest"),
                    "artifact_origin": metadata.get("artifact_origin"),
                    "canonical_lineage_digest": (metadata.get("canonical_training_lineage") or {}).get(
                        "lineage_digest"
                    ),
                    "validation_evidence_digest": (metadata.get("canonical_training_lineage") or {}).get(
                        "validation_execution_digest"
                    ),
                    "integrity_hash": integrity_hash,
                    "artifact_dir": store.artifact_directory(artifact_uid),
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
            definition = {
                "parameters": node.parameters,
                "inputs": sorted(
                    (edge.from_node, edge.from_output, edge.to_input) for edge in self.edges if edge.to_node == node_id
                ),
            }
            param_str = json.dumps(definition, sort_keys=True, default=str)
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

    def _transitive_descendants(self, node_id: str) -> Set[str]:
        """Return every node id reachable downstream of ``node_id``.

        Used after a node failure to mark all dependents as ``ERROR`` so
        ``get_status()`` reflects what actually happened (rather than
        leaving them in ``PENDING``, which reads as "didn't run yet" in
        the UI and misleads users about a failed workflow).
        """
        descendants: Set[str] = set()
        stack: list[str] = [node_id]
        while stack:
            current = stack.pop()
            for edge in self.edges:
                if edge.from_node == current and edge.to_node not in descendants:
                    descendants.add(edge.to_node)
                    stack.append(edge.to_node)
        return descendants

    def _mark_descendants_failed(self, failed_node_id: str) -> None:
        """Mark every transitive downstream of ``failed_node_id`` as ERROR.

        Skips nodes that already have a terminal status so a node that
        errored on its own (and brought down its descendants) doesn't
        get its message overwritten.
        """
        descendants = self._transitive_descendants(failed_node_id)
        reason = f"Skipped: upstream node '{failed_node_id}' failed"
        for dep_id in descendants:
            dep_node = self.nodes.get(dep_id)
            if dep_node is None:
                continue
            if dep_node.status in (NodeStatus.COMPLETED, NodeStatus.ERROR):
                continue
            dep_node.status = NodeStatus.ERROR
            dep_node.error_message = reason

    def inject_result(self, node_id: str, result: Any) -> None:
        """
        Inject a pre-computed result for a node (used by prediction API).

        The node is treated as cached and will not be re-executed.

        Args:
            node_id: Node ID to inject result for
            result: Pre-computed canonical result
        """
        node = self.nodes.get(node_id)
        if node is None:
            raise KeyError(f"Cannot inject a result for unknown node {node_id!r}")
        if node.metadata is not None and node.metadata.node_type == "deploy.input":
            raise ValueError(
                "deploy.input payloads must use inject_deployment_input() so the named external dataset is admitted"
            )
        reject_spectrochempy_transport(result, boundary=f"executor injection for node {node_id!r}")
        self.results[node_id] = result
        self._param_hashes[node_id] = "__injected__"

    def inject_deployment_input(self, node_id: str, payload: Any, *, stream_name: str) -> None:
        """Admit and inject one named external dataset into ``deploy.input``.

        HTTP authentication belongs to the caller-facing route. This method is
        the scientific data boundary: it binds the requested stream to the
        node's declared stream and applies the same matrix contract used by
        exported Python.
        """

        node = self.nodes.get(node_id)
        if node is None:
            raise KeyError(f"Unknown deployment input node {node_id!r}")
        if node.metadata is None or node.metadata.node_type != "deploy.input":
            raise ValueError(f"Node {node_id!r} is not a deploy.input node")
        declared_stream = node.parameters.get("stream_name", "sample")
        if stream_name != declared_stream:
            raise ValueError(f"Deployment input {node_id!r} declares stream {declared_stream!r}, not {stream_name!r}")

        from spectra_sherpa.sdk.deployment import (
            DEPLOYMENT_INPUT_SCHEMA,
            admit_deployment_input,
            deployment_target_output,
        )

        dataset = admit_deployment_input(
            payload,
            stream_name=stream_name,
            schema_version=node.parameters.get("schema_version", DEPLOYMENT_INPUT_SCHEMA),
        )
        admitted: dict[str, Any] = {"default": dataset}
        target_required = any(edge.from_node == node_id and edge.from_output == "target" for edge in self.edges)
        target = deployment_target_output(dataset, required=target_required)
        if target is not None:
            admitted["target"] = target
        self.results[node_id] = admitted
        # Reuse the executor's sole precomputed-result cache marker. The
        # deployment-specific admission has already happened above; cache
        # identity only needs to prevent ordinary source execution.
        self._param_hashes[node_id] = "__injected__"

    def find_entry_nodes(self) -> List[str]:
        """
        Find graph roots, never downstream data-processing nodes.

        Returns:
            List of node IDs that are entry points
        """
        incoming = {e.to_node for e in self.edges}
        return [nid for nid in self.nodes if nid not in incoming]

    def find_prediction_entry_nodes(self) -> List[str]:
        """Resolve the single dataset boundary without replacing reference branches."""
        roots = self.find_entry_nodes()
        types = {nid: node.metadata.node_type for nid in roots if (node := self.nodes[nid]).metadata is not None}
        explicit = [nid for nid, node_type in types.items() if node_type == "deploy.input"]
        candidates = explicit or [
            nid for nid, node_type in types.items() if node_type in {"data.file_load", "data.collection_load"}
        ]
        if len(candidates) != 1:
            raise ValueError("Prediction requires exactly one input; add a single deploy.input node")
        return candidates

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

    def validate_full(self, *, include_port_type_validation: bool = True) -> ValidationResult:
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

        # 5. Port type compatibility between connected nodes.  API/workbench
        # admission uses workflow_preflight as its one semantic authority and
        # opts out here; direct SDK use retains the historical check until the
        # canonical runtime path is fully adopted.
        if include_port_type_validation:
            issues.extend(self._validate_port_types())

        # 6. Static data-role compatibility where a source role can be inferred
        issues.extend(self._validate_static_data_roles())

        # 7. The ordinary canvas executes every ancestor once on the complete
        # matrix. A holdout split or nested-CV node may consume only raw sources and
        # operations whose canonical contracts prove they are stateless
        # transforms.  The rule is deliberately based on lifecycle contracts
        # rather than catalog categories: fitted variable selectors leak just
        # as surely as fitted preprocessing.  Target access alone is not a
        # proxy for fitting—a stateless target-attachment operation is safe.
        issues.extend(self._validate_nested_cv_ancestor_fold_safety())
        from .population_authority import analyze_populations

        population_issues, _ = analyze_populations(self.nodes, self.edges)
        issues.extend(population_issues)

        return ValidationResult(issues)

    def _validate_nested_cv_ancestor_fold_safety(self) -> List[ValidationIssue]:
        """Reject full-matrix fitting before holdout or nested-CV boundaries."""

        issues: List[ValidationIssue] = []
        incoming: dict[str, list[str]] = {node_id: [] for node_id in self.nodes}
        for edge in self.edges:
            incoming.setdefault(edge.to_node, []).append(edge.from_node)

        for nested_id, nested_node in self.nodes.items():
            if nested_node.metadata is None or nested_node.metadata.node_type not in {
                "selection.nested_cv",
                "data.train_test_split",
            }:
                continue
            is_holdout = nested_node.metadata.node_type == "data.train_test_split"
            boundary = "Train/test split" if is_holdout else "Nested CV"
            evaluation = "the holdout split" if is_holdout else "cross-validation"
            remedy = (
                "Split raw data first, fit on the training branch, and apply that frozen state to the test branch."
                if is_holdout
                else "Run fitted operations through the canonical fold lifecycle."
            )
            ancestors: set[str] = set()
            stack = list(incoming.get(nested_id, ()))
            while stack:
                ancestor_id = stack.pop()
                if ancestor_id in ancestors:
                    continue
                ancestors.add(ancestor_id)
                stack.extend(incoming.get(ancestor_id, ()))

            for ancestor_id in sorted(ancestors):
                ancestor = self.nodes[ancestor_id]
                metadata = ancestor.metadata
                if metadata is None:
                    issues.append(
                        ValidationIssue(
                            "error",
                            nested_id,
                            "X",
                            f"{boundary} cannot consume upstream operation '{ancestor_id}' because its "
                            "metadata is unavailable. The canvas would execute that operation on all "
                            f"rows before {evaluation}.",
                        )
                    )
                    continue
                contract = metadata.resolved_execution_contract()

                if contract is None:
                    reason = "has no canonical execution contract"
                else:
                    payload = contract.payload
                    lifecycle = payload.get("lifecycle_kind")
                    unsafe: list[str] = []
                    if lifecycle not in {"data_source", "stateless_transform"}:
                        unsafe.append(f"lifecycle_kind={lifecycle}")
                    if not unsafe:
                        continue
                    reason = "declares " + ", ".join(unsafe)
                issues.append(
                    ValidationIssue(
                        "error",
                        nested_id,
                        "X",
                        f"{boundary} cannot consume upstream operation '{ancestor_id}' "
                        f"({metadata.label}) because it {reason}. The canvas would execute that "
                        f"operation on all rows before {evaluation}. Use only a raw data source "
                        f"or a contract-declared stateless transform here. {remedy}",
                    )
                )
        return issues

    def _validate_port_connections(self) -> List[ValidationIssue]:
        """Check that multi-input nodes have all required inputs connected."""
        issues: List[ValidationIssue] = []
        for node_id, node in self.nodes.items():
            if node.uses_named_ports() and node.metadata is not None and node.metadata.input_ports:
                incoming_edges = [e for e in self.edges if e.to_node == node_id]
                connected_ports: Set[str] = set()
                declared_ports = {port.name for port in node.metadata.input_ports}

                for edge in incoming_edges:
                    port_name = edge.to_input
                    if port_name == "default" and "default" not in declared_ports:
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
                            f"Node '{node_id}' ({node.metadata.label}): Missing required parameter '{param_def.label}'",
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
                if is_ok:
                    from .model_edge_contracts import model_edge_error

                    reason = model_edge_error(
                        source_node.metadata, edge.from_output, target_node.metadata, edge.to_input
                    )
                    if reason is not None:
                        issues.append(ValidationIssue("error", edge.to_node, edge.to_input, reason))
                        continue
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

    def _validate_static_data_roles(self) -> List[ValidationIssue]:
        """Catch clear X_features → spectrum-only mistakes before execution."""
        issues: List[ValidationIssue] = []
        inferred_roles: dict[tuple[str, str], str | None] = {}

        def infer_role(node_id: str, output_name: str = "default", seen: set[str] | None = None) -> str | None:
            key = (node_id, output_name)
            if key in inferred_roles:
                return inferred_roles[key]
            if seen is None:
                seen = set()
            if node_id in seen:
                return None
            seen.add(node_id)

            node = self.nodes.get(node_id)
            if node is None or node.metadata is None:
                inferred_roles[key] = None
                return None

            role = self._infer_node_output_role(node, output_name)
            if role is None:
                incoming = [edge for edge in self.edges if edge.to_node == node_id]
                for edge in incoming:
                    role = infer_role(edge.from_node, edge.from_output, seen)
                    if role is not None:
                        break

            inferred_roles[key] = role
            return role

        for edge in self.edges:
            target_node = self.nodes.get(edge.to_node)
            if target_node is None or target_node.metadata is None:
                continue

            role = infer_role(edge.from_node, edge.from_output)
            if role is None:
                continue

            accepted = None
            for port in target_node.metadata.input_ports or []:
                if port.name == edge.to_input:
                    accepted = port.accepted_data_roles
                    break

            allowed_roles = accepted or (
                ["X_spectra"] if is_spectrum_only_node(target_node.metadata.node_type, target_node.parameters) else None
            )
            if allowed_roles and role not in allowed_roles:
                label = target_node.metadata.label or target_node.metadata.node_type
                issues.append(
                    ValidationIssue(
                        "error",
                        edge.to_node,
                        edge.to_input,
                        f"{label} requires {', '.join(allowed_roles)} input; received {role}. "
                        "Feature-table data has no ordered spectral axis for this operation.",
                    )
                )
        return issues

    def _infer_node_output_role(self, node: Node, output_name: str) -> str | None:
        """Infer a node's output data role from parameters and known role-changing ports."""
        if output_name in {"scores", "X_scores", "T", "visualization", "cluster_assignment", "predictions"}:
            return "X_features"

        explicit_role = node.parameters.get("data_role")
        if isinstance(explicit_role, str) and explicit_role in {"X_spectra", "X_features", "X_hsi"}:
            return explicit_role

        node_type = node.metadata.node_type if node.metadata is not None else ""
        if node_type == "data.filter_samples" and node.parameters.get("field") == "source_inclusion":
            return "X_spectra"
        if node_type == "data.nist_library":
            return "X_spectra"

        return None

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

    def _worker_context(self, node: Node) -> WorkerExecutionContext:
        """Create trusted worker authority; never derive it from workflow data."""
        capabilities = resolved_runtime_worker_capabilities(node)
        return WorkerExecutionContext(
            execution_id=str(uuid.uuid4()),
            runtime=self.runtime.for_worker(capabilities),
            capabilities=capabilities,
            origin_pid=os.getpid(),
        )

    @staticmethod
    def _sanitize_for_pool(value: Any) -> Any:
        """Reject any optional-runtime object recursively at the pool boundary."""

        reject_spectrochempy_transport(value, boundary="process-pool submission")
        return value

    async def _run_fold_validated_evaluator(self, node: Node, timeout: float) -> NodeResult | None:
        """Score a sheet's terminal evaluator with its recorded campaign folds.

        Returns ``None`` when the node is not a fold-validated evaluator (for
        example, the scientist wired explicit reference values).
        """
        from .sheet_fold_validation import (
            fold_validation_chain,
            prepare_sheet_fold_validation,
            run_sheet_fold_validation,
            run_sheet_fold_validation_async,
            sheet_fold_validation_result,
        )

        node_types = {nid: item.metadata.node_type for nid, item in self.nodes.items() if item.metadata}
        chain = fold_validation_chain(node_types, self.edges, node.node_id, holdout=self.fold_validation_plan.holdout)
        if chain is None:
            return None
        boundary_id, chain_ids = chain
        boundary = self.results.get(boundary_id)
        boundary_port = "X_train" if node_types[boundary_id] == "data.train_test_split" else "default"
        dataset = boundary.get(boundary_port) if isinstance(boundary, dict) else boundary
        members = set(chain_ids)
        chain_nodes = [WorkflowNode(nid, node_types[nid], dict(self.nodes[nid].parameters)) for nid in chain_ids]
        chain_edges = [edge for edge in self.edges if edge.from_node in members and edge.to_node in members]
        plan = self.fold_validation_plan
        graph_wire, capability_wire, split = prepare_sheet_fold_validation(plan, chain_nodes, chain_edges, dataset)
        if isinstance(self._process_pool, IsolatedWorkerPool):
            execution = await self._process_pool.run(
                run_sheet_fold_validation, graph_wire, capability_wire, split, timeout=timeout
            )
        elif self._process_pool is not None:
            future = asyncio.get_running_loop().run_in_executor(
                self._process_pool, run_sheet_fold_validation, graph_wire, capability_wire, split
            )
            execution = await asyncio.wait_for(future, timeout=timeout)
        else:
            execution = await asyncio.wait_for(
                run_sheet_fold_validation_async(graph_wire, capability_wire, split), timeout=timeout
            )
        return sheet_fold_validation_result(plan, execution, split=split)

    async def _run_one_node(
        self,
        node: Node,
        positional_inputs: List[Any],
        named_inputs: Dict[str, Any],
        timeout: float,
    ) -> NodeResult:
        """Execute a node; worker failures never retry in the API process."""
        from .execution_scope import upstream_node_ids
        from .population_authority import analyze_populations, qualify_evaluation_result

        selected = upstream_node_ids(self.nodes, self.edges, node.node_id)
        population_issues, receipts = analyze_populations(
            {key: value for key, value in self.nodes.items() if key in selected},
            [edge for edge in self.edges if edge.to_node in selected],
        )
        if population_issues:
            raise ValueError("\n".join(issue.message for issue in population_issues))
        receipt = receipts.get(node.node_id)
        if self.fold_validation_plan is not None:
            holdout = self.fold_validation_plan.holdout
            if holdout is not None and node.node_id == holdout["split_node_id"]:
                from .retained_holdout import materialize_retained_holdout

                if node.metadata.node_type != "data.train_test_split":
                    raise ValueError("Retained holdout is bound to a train/test split node")
                source = named_inputs.get("X") if named_inputs else positional_inputs[0]
                retained_source = self.results.get(holdout["source_node_id"])
                if isinstance(retained_source, dict):
                    retained_source = retained_source.get("default")
                outputs = materialize_retained_holdout(
                    source, holdout, parameters=node.parameters, raw_source=retained_source
                )
                return NodeResult(
                    outputs=outputs,
                    diagnostics={
                        "membership": "retained_from_source_run",
                        "source_run_id": holdout["source_run_id"],
                        "training_rows": len(holdout["train_indices"]),
                        "held_out_rows": len(holdout["test_indices"]),
                    },
                )
            fold_result = await self._run_fold_validated_evaluator(node, timeout)
            if fold_result is not None:
                return fold_result
        capabilities = frozenset(resolved_runtime_worker_capabilities(node))
        if "read_model_artifact" in capabilities:
            self.runtime.require_model_artifact_reader()
            self.runtime.require_model_artifact_replay()
        if "read_canonical_fitted_artifact" in capabilities:
            self.runtime.require_canonical_artifact_reader()
        if self._should_offload(node):
            safe_pos = tuple(self._sanitize_for_pool(v) for v in positional_inputs) if not named_inputs else ()
            safe_named = {k: self._sanitize_for_pool(v) for k, v in named_inputs.items()} if named_inputs else {}
            assert node.metadata is not None
            args = (
                node.metadata.node_type,
                node.node_id,
                dict(node.parameters),
                safe_pos,
                safe_named,
                self._worker_context(node),
            )
            if isinstance(self._process_pool, IsolatedWorkerPool):
                result = await self._process_pool.run(_run_node_in_worker, *args, timeout=timeout)
            else:
                # Compatibility for SDK callers supplying their own executor.
                # They own its cancellation policy; never retry locally.
                future = asyncio.get_running_loop().run_in_executor(self._process_pool, _run_node_in_worker, *args)
                result = await asyncio.wait_for(future, timeout=timeout)
            return qualify_evaluation_result(result, receipt)

        # In-process nodes use the same Node.run transport guard as workers.
        node.bind_execution_runtime(self.runtime)
        if named_inputs:
            return qualify_evaluation_result(await asyncio.wait_for(node.run(**named_inputs), timeout=timeout), receipt)
        else:
            return qualify_evaluation_result(
                await asyncio.wait_for(node.run(*positional_inputs), timeout=timeout), receipt
            )

    def _validate_runtime_data_roles(
        self,
        node: Node,
        positional_inputs: List[Any],
        named_inputs: Dict[str, Any],
    ) -> None:
        """Reject feature tables at spectrum-only nodes before execution."""
        if node.metadata is None:
            return

        port_roles = {
            port.name: port.accepted_data_roles
            for port in (node.metadata.input_ports or [])
            if port.accepted_data_roles
        }
        spectrum_only_roles = ["X_spectra"] if is_spectrum_only_node(node.metadata.node_type, node.parameters) else None

        def _iter_values(value: Any):
            if isinstance(value, (list, tuple)):
                for item in value:
                    yield from _iter_values(item)
            else:
                yield value

        def _validate(value: Any, accepted: list[str] | None, port_name: str | None) -> None:
            roles = accepted or spectrum_only_roles
            if not roles:
                return
            label = node.metadata.label or node.metadata.node_type
            context = f"{label} input '{port_name}'" if port_name else label
            for item in _iter_values(value):
                require_data_role(item, roles, context=context)

        for port_name, value in named_inputs.items():
            _validate(value, port_roles.get(port_name), port_name)

        if positional_inputs:
            ports = node.metadata.input_ports or []
            for idx, value in enumerate(positional_inputs):
                port_name = ports[idx].name if idx < len(ports) else None
                _validate(value, port_roles.get(port_name or ""), port_name)

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
                    raise ValueError(f"Port '{_pn}' on node '{node_id}' received {_count} edges but is not variadic")

            return [], named_inputs
        else:
            # Legacy: return positional inputs sorted by port name
            incoming_edges.sort(key=lambda e: e.to_input)
            positional_inputs = []
            for edge in incoming_edges:
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

                positional_inputs.append(data)

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
                self._validate_runtime_data_roles(node, positional_inputs, named_inputs)

                # Execute node (offloaded to process pool when available)
                node_timeout = self.runtime.node_timeout_seconds
                label = node.metadata.label if node.metadata else node_id
                logger.debug("Executing node: %s (%s)", node_id, label)
                node.status = NodeStatus.RUNNING
                await _emit(node_id, "running")
                try:
                    result = await self._run_one_node(node, positional_inputs, named_inputs, node_timeout)
                except asyncio.TimeoutError:
                    err_msg = (
                        f"Node '{label}' exceeded {node_timeout}s timeout. Reduce dataset size or simplify parameters."
                    )
                    node.status = NodeStatus.ERROR
                    node.error_message = err_msg
                    await _emit(node_id, "error", err_msg)
                    # Cascade ERROR to downstream so get_status() doesn't
                    # leave them in PENDING — see _mark_descendants_failed.
                    self._mark_descendants_failed(node_id)
                    raise ValueError(err_msg)
                except Exception as exc:
                    # Pool or in-process execution failure — status on the worker
                    # copy (if any) never propagates back, so mark the main-process
                    # node explicitly so get_status() reflects reality.
                    node.status = NodeStatus.ERROR
                    node.error_message = str(exc)
                    await _emit(node_id, "error", str(exc))
                    self._mark_descendants_failed(node_id)
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
            raise ValueError(f"Workflow execution failed: {str(e)}") from e

    async def execute_node(
        self,
        node_id: str,
        initial_data: Optional[Dict[str, Any]] = None,
        status_callback: Optional[Callable[[str, str, Optional[str]], Any]] = None,
    ) -> Any:
        """
        Execute a single node (and its dependencies if needed).

        Args:
            node_id: ID of node to execute
            initial_data: Optional dict of node_id -> config for source nodes.
                         This is used to configure DATA nodes with experiment IDs,
                         file paths, etc.
            status_callback: Optional ``async (node_id, status, error_msg) -> None``
                         hook for real-time progress updates. Mirrors the
                         signature accepted by ``execute()`` so the route can
                         forward WS broadcasts identically for single-node
                         trial runs. Failures inside the callback are
                         swallowed so a broken broadcast never aborts
                         execution.

        Returns:
            Result of node execution

        Raises:
            ValueError: If node not found or execution fails
        """
        if node_id not in self.nodes:
            raise ValueError(f"Node {node_id} not found in workflow")

        async def _emit(nid: str, st: str, err: str | None = None) -> None:
            if status_callback is None:
                return
            try:
                await status_callback(nid, st, err)
            except Exception:
                pass  # never let broadcast failure affect execution

        from .execution_scope import upstream_node_ids
        from .population_authority import analyze_populations

        selected = upstream_node_ids(self.nodes, self.edges, node_id)
        population_issues, _ = analyze_populations(
            {key: node for key, node in self.nodes.items() if key in selected},
            [edge for edge in self.edges if edge.to_node in selected],
        )
        if population_issues:
            raise ValueError("\n".join(issue.message for issue in population_issues))

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
                await _emit(dep_node_id, "completed")
                if dep_node_id not in executed_in_this_run:
                    executed_in_this_run.append(dep_node_id)
                continue

            # Execute the node (offloaded to process pool when available)
            positional_inputs, named_inputs = self._get_node_inputs(dep_node_id)
            node_timeout = self.runtime.node_timeout_seconds
            logger.debug("Executing node: %s (%s)", dep_node_id, node.metadata.label if node.metadata else dep_node_id)
            node.status = NodeStatus.RUNNING
            await _emit(dep_node_id, "running")
            try:
                result = await self._run_one_node(node, positional_inputs, named_inputs, node_timeout)
            except asyncio.TimeoutError:
                label = node.metadata.label if node.metadata else dep_node_id
                err_msg = (
                    f"Node '{label}' exceeded {node_timeout}s timeout. Reduce dataset size or simplify parameters."
                )
                node.status = NodeStatus.ERROR
                node.error_message = err_msg
                await _emit(dep_node_id, "error", err_msg)
                self._mark_descendants_failed(dep_node_id)
                raise ValueError(err_msg)
            except Exception as exc:
                # Pool workers mutate a separate node instance; record the
                # error on the main-process copy so get_status() is truthful.
                node.status = NodeStatus.ERROR
                node.error_message = str(exc)
                await _emit(dep_node_id, "error", str(exc))
                self._mark_descendants_failed(dep_node_id)
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
            await _emit(dep_node_id, "completed")

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
