"""
Python code generator for workflows.

Exports workflows as standalone executable Python scripts by delegating
code generation to each node's ``generate_python()`` method.  The exporter
handles only orchestration: topological sort, import collection, and
stitching the final script.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from spectra_sherpa.app.lib.scp_compat import HAS_SCP
from spectra_sherpa.app.services.dag.graph_utils import Edge, build_input_map, topological_sort
from spectra_sherpa.app.services.dag.node_base import node_registry

if TYPE_CHECKING:
    from spectra_sherpa.app.models.workflow import Workflow

logger = logging.getLogger(__name__)


@dataclass
class ExportValidationError:
    """Describes a node that cannot be exported."""

    node_id: str
    node_type: str
    reason: str


def validate_export(workflow: Workflow) -> list[ExportValidationError]:
    """
    Pre-check whether every non-source node in the workflow supports Python export.

    Source nodes (those with no incoming edges) are always rendered as
    placeholder comments, so they do not need a ``generate_python()``
    implementation to pass validation.

    Returns:
        List of validation errors (empty means all nodes are exportable).
    """
    # Identify source nodes (no incoming edges)
    nodes_with_incoming = {e.to_node_id for e in workflow.edges}

    errors: list[ExportValidationError] = []
    for wf_node in workflow.nodes:
        # Source nodes get placeholder comments — skip validation
        if wf_node.node_id not in nodes_with_incoming:
            continue

        try:
            node = node_registry.create_node(wf_node.node_type, wf_node.node_id, wf_node.parameters)
        except KeyError:
            errors.append(
                ExportValidationError(
                    node_id=wf_node.node_id,
                    node_type=wf_node.node_type,
                    reason=f"Unknown node type: {wf_node.node_type}",
                )
            )
            continue

        if not node.supports_python_export():
            errors.append(
                ExportValidationError(
                    node_id=wf_node.node_id,
                    node_type=wf_node.node_type,
                    reason="Node does not support Python export yet",
                )
            )
            continue

        # Check that wired output ports exist in the node's exported output
        exported_ports = node.exported_output_ports()
        if exported_ports is not None:
            wired_ports = {e.from_output or "default" for e in workflow.edges if e.from_node_id == wf_node.node_id}
            missing = wired_ports - exported_ports - {"default"}
            if missing:
                errors.append(
                    ExportValidationError(
                        node_id=wf_node.node_id,
                        node_type=wf_node.node_type,
                        reason=(
                            f"Downstream edges reference output port(s) "
                            f"{sorted(missing)} but export only provides "
                            f"{sorted(exported_ports)}"
                        ),
                    )
                )
    return errors


def generate_python_code(workflow: Workflow) -> str:
    """
    Generate executable Python code from a workflow.

    Instantiates each node via the registry and calls its
    ``generate_python()`` method.  Source nodes (no incoming edges) get a
    placeholder comment prompting the user to supply data.

    Args:
        workflow: Workflow model with nodes and edges

    Returns:
        Python code as a string

    Raises:
        ValueError: If any node does not support Python export.
    """
    # --- validate --------------------------------------------------------
    errors = validate_export(workflow)
    if errors:
        details = "; ".join(f"{e.node_id} ({e.node_type}): {e.reason}" for e in errors)
        raise ValueError(f"Workflow contains nodes that cannot be exported: {details}")

    # --- normalise edges -------------------------------------------------
    edges = [
        Edge(
            from_node=e.from_node_id,
            to_node=e.to_node_id,
            from_output=e.from_output or "default",
            to_input=e.to_input or "default",
        )
        for e in workflow.edges
    ]
    node_ids = [n.node_id for n in workflow.nodes]

    # --- topological sort ------------------------------------------------
    execution_order = topological_sort(node_ids, edges)

    # --- instantiate nodes via registry ----------------------------------
    node_map = {}
    for wf_node in workflow.nodes:
        node_map[wf_node.node_id] = node_registry.create_node(wf_node.node_type, wf_node.node_id, wf_node.parameters)

    # --- backend mode (SCP vs numpy) --------------------------------------
    use_scp = HAS_SCP

    # --- collect extra imports -------------------------------------------
    extra_imports: set[str] = set()
    for node in node_map.values():
        for imp in node.python_extra_imports:
            extra_imports.add(imp)

    # --- identify dict-emitting nodes ------------------------------------
    # Non-source nodes whose generate_python() always emits a dict result.
    # Source nodes are excluded because their output format is controlled
    # by the _multi_port flag (handled separately in the source-node block).
    nodes_with_incoming = {e.to_node for e in edges}
    dict_output_nodes = frozenset(
        nid for nid, node in node_map.items() if nid in nodes_with_incoming and node.exported_output_ports() is not None
    )

    # --- build code lines ------------------------------------------------
    indent = "    "
    lines: list[str] = []

    # Header
    lines.append('"""')
    lines.append(f"Generated workflow: {workflow.name}")
    if workflow.description:
        lines.append("")
        lines.append(workflow.description)
    if hasattr(workflow, "integrity_hash") and workflow.integrity_hash:
        lines.append("")
        lines.append(f"Integrity Hash: {workflow.integrity_hash}")
    lines.append('"""')
    lines.append("")

    # Imports
    lines.append("import numpy as np")
    if use_scp:
        lines.append("import spectrochempy as scp")
        lines.append("from spectrochempy import NDDataset")
    lines.append("")

    # Extra imports collected from nodes (deduplicated, skip already-present)
    base_imports = {"import numpy as np"}
    if use_scp:
        base_imports |= {"import spectrochempy as scp", "from spectrochempy import NDDataset"}
    for imp in sorted(extra_imports - base_imports):
        # Skip SCP imports when not using SCP
        if not use_scp and "spectrochempy" in imp:
            continue
        lines.append(imp)

    if not use_scp:
        # Lightweight data container so downstream .data / .x access works
        lines.append("")
        lines.append("")
        lines.append("class _Result:")
        lines.append('    """Lightweight data container for pipeline results."""')
        lines.append("    def __init__(self, data, x=None, target=None, target_names=None):")
        lines.append("        self.data = np.atleast_2d(np.asarray(data, dtype=np.float64))")
        lines.append("        self.x = x")
        lines.append("        self.shape = self.data.shape")
        lines.append("        self.ndim = self.data.ndim")
        lines.append("        self.target = np.asarray(target, dtype=np.float64) if target is not None else None")
        lines.append("        self.target_names = target_names")
        lines.append("    def copy(self):")
        lines.append("        return _Result(")
        lines.append("            self.data.copy(), x=self.x,")
        lines.append("            target=self.target.copy() if self.target is not None else None,")
        lines.append("            target_names=self.target_names,")
        lines.append("        )")
    lines.append("")

    # Main function
    lines.append("")
    lines.append("def run_workflow():")
    lines.append(f'{indent}"""Execute the workflow."""')
    lines.append(f'{indent}print("=" * 60)')
    lines.append(f'{indent}print("Workflow: {workflow.name}")')
    lines.append(f'{indent}print("=" * 60)')
    lines.append("")
    lines.append(f"{indent}# Store intermediate results")
    lines.append(f"{indent}results = {{}}")
    lines.append("")

    # Generate code for each node in execution order
    for node_id in execution_order:
        node = node_map[node_id]
        input_map = build_input_map(node_id, edges, dict_output_nodes=dict_output_nodes)

        if not input_map:
            # Source node — no upstream edges.
            # Check if downstream edges use multiple output ports from this
            # node.  When they do, the result must be a dict so that
            # port-qualified references like results['node']['target'] work.
            used_ports = {e.from_output or "default" for e in edges if e.from_node == node_id}
            is_multi_port = len(used_ports) > 1

            # Exportable source nodes (e.g. sklearn/eigenvector/SCP loaders)
            # generate their own loading code with SherpaDataset construction.
            if node.supports_python_export():
                export_inputs = {"_multi_port": str(is_multi_port)}
                node_lines = node.generate_python(export_inputs, indent=indent, use_scp=use_scp)
                lines.extend(node_lines)
                lines.append("")
                continue

            # Non-exportable source: emit placeholder for user to fill in.
            lines.append(f"{indent}# --- Source: {node_id} ({node.metadata.node_type}) ---")
            lines.append(f"{indent}# >>> EDIT: provide your data below <<<")

            if is_multi_port:
                lines.append(f"{indent}results['{node_id}'] = {{}}")
                if use_scp:
                    lines.append(f"{indent}# results['{node_id}']['default'] = scp.read('your_spectra.scp')")
                else:
                    lines.append(f"{indent}# results['{node_id}']['default'] = _Result(np.zeros((10, 100)))")
                for port in sorted(used_ports - {"default"}):
                    lines.append(f"{indent}# results['{node_id}']['{port}'] = ...  # provide {port} data")
            else:
                if use_scp:
                    lines.append(f"{indent}# results['{node_id}'] = scp.read('your_file.scp')")
                    lines.append(f"{indent}# results['{node_id}'] = scp.load_iris()")
                else:
                    lines.append(f"{indent}# from sklearn.datasets import load_iris")
                    lines.append(f"{indent}# _bunch = load_iris()")
                    lines.append(f"{indent}# results['{node_id}'] = _Result(_bunch.data)")
            lines.append("")
            continue

        # Delegate to node's generate_python()
        node_lines = node.generate_python(input_map, indent=indent, use_scp=use_scp)
        lines.extend(node_lines)
        lines.append("")

    # Return
    lines.append(f"{indent}return results")
    lines.append("")
    lines.append("")

    # Main block
    lines.append('if __name__ == "__main__":')
    lines.append(f"{indent}results = run_workflow()")
    lines.append("")
    lines.append(f'{indent}print("\\nWorkflow completed successfully!")')
    lines.append(f"{indent}for key, value in results.items():")
    lines.append(f'{indent}    print(f"  {{key}}: {{type(value).__name__}}")')
    lines.append("")

    return "\n".join(lines)
