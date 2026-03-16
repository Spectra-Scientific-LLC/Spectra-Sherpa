"""
Python code generator for workflows.

Exports workflows as standalone executable Python scripts by delegating
code generation to each node's ``generate_python()`` method.  The exporter
handles only orchestration: topological sort, import collection, and
stitching the final script.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from spectra_sherpa.app.lib.scp_compat import HAS_SCP
from spectra_sherpa.app.services.dag.graph_utils import Edge, build_input_map, topological_sort
from spectra_sherpa.app.services.dag.node_base import node_registry

if TYPE_CHECKING:
    from spectra_sherpa.app.models.workflow import Workflow

logger = logging.getLogger(__name__)


def _safe_identifier(node_id: str) -> str:
    """Convert *node_id* to a valid Python identifier suffix."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", node_id)


@dataclass
class ExportValidationError:
    """Describes a node that cannot be exported."""

    node_id: str
    node_type: str
    reason: str


def _generate_source_placeholder_lines(node_id: str, node, edges: list[Edge], indent: str) -> list[str]:
    """Build placeholder code for non-exportable source nodes."""
    used_ports = {e.from_output or "default" for e in edges if e.from_node == node_id}
    is_multi_port = len(used_ports) > 1

    lines: list[str] = []
    lines.append(f"{indent}# --- Source: {node_id} ({node.metadata.node_type}) ---")
    lines.append(f"{indent}# ╔══════════════════════════════════════════════════════════╗")
    lines.append(f"{indent}# ║  DATA LOADING — Edit below to load your data            ║")
    lines.append(f"{indent}# ║                                                          ║")
    lines.append(f"{indent}# ║  Place your spectral data files in the DATA_DIR folder.  ║")
    lines.append(f"{indent}# ║  Supported formats: .csv, .spc, .dx, .jdx, .mat, .scp   ║")
    lines.append(f"{indent}# ╚══════════════════════════════════════════════════════════╝")

    if is_multi_port:
        lines.append(f"{indent}results['{node_id}'] = {{}}")
        lines.append(f"{indent}# Example: Load spectra from CSV (rows=samples, cols=wavelengths)")
        lines.append(f"{indent}# _raw = np.loadtxt(os.path.join(DATA_DIR, 'spectra.csv'), delimiter=',')")
        lines.append(f"{indent}# results['{node_id}']['default'] = SherpaDataset(_raw)")
        for port in sorted(used_ports - {"default"}):
            if port == "target":
                lines.append(f"{indent}# _target = np.loadtxt(os.path.join(DATA_DIR, 'targets.csv'), delimiter=',')")
                lines.append(f"{indent}# results['{node_id}']['target'] = _target")
            else:
                lines.append(f"{indent}# results['{node_id}']['{port}'] = ...  # provide {port} data")
    else:
        lines.append(f"{indent}# Example: Load spectra from CSV (rows=samples, cols=wavelengths)")
        lines.append(f"{indent}# _raw = np.loadtxt(os.path.join(DATA_DIR, 'spectra.csv'), delimiter=',')")
        lines.append(f"{indent}# results['{node_id}'] = SherpaDataset(_raw)")
        lines.append(f"{indent}#")
        lines.append(f"{indent}# Or load a SpectroChemPy dataset:")
        lines.append(f"{indent}# from spectra_sherpa.app.lib.scp_compat import from_nddataset")
        lines.append(f"{indent}# _ndd = scp.read(os.path.join(DATA_DIR, 'data.scp'))")
        lines.append(f"{indent}# results['{node_id}'] = from_nddataset(_ndd)")
    return lines


def _generate_node_python_lines(
    node_id: str,
    node,
    edges: list[Edge],
    dict_output_nodes: frozenset[str],
    indent: str,
    use_scp: bool,
) -> list[str]:
    """Generate the code block for a single workflow node."""
    input_map = build_input_map(node_id, edges, dict_output_nodes=dict_output_nodes)
    if not input_map:
        used_ports = {e.from_output or "default" for e in edges if e.from_node == node_id}
        is_multi_port = len(used_ports) > 1
        if node.supports_python_export():
            export_inputs = {"_multi_port": str(is_multi_port)}
            return node.generate_python(export_inputs, indent=indent, use_scp=use_scp)
        return _generate_source_placeholder_lines(node_id, node, edges, indent)
    return node.generate_python(input_map, indent=indent, use_scp=use_scp)


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
    lines.append("import os")
    lines.append("import json")
    lines.append("import zipfile")
    lines.append("from datetime import datetime")
    lines.append("")
    lines.append("import numpy as np")
    if use_scp:
        lines.append("import spectrochempy as scp")
        lines.append("from spectrochempy import NDDataset")
    lines.append("from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext")
    lines.append("")

    # Extra imports collected from nodes (deduplicated, skip already-present)
    base_imports = {
        "import numpy as np",
        "import os",
        "import json",
        "import zipfile",
        "from datetime import datetime",
        "from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext",
    }
    if use_scp:
        base_imports |= {"import spectrochempy as scp", "from spectrochempy import NDDataset"}
    for imp in sorted(extra_imports - base_imports):
        # Skip SCP imports when not using SCP
        if not use_scp and "spectrochempy" in imp:
            continue
        lines.append(imp)
    lines.append("")

    # Export helpers
    lines.append("def _json_default(value):")
    lines.append(f"{indent}if isinstance(value, np.generic):")
    lines.append(f"{indent}    return value.item()")
    lines.append(f"{indent}if isinstance(value, np.ndarray):")
    lines.append(f"{indent}    return value.tolist()")
    lines.append(f"{indent}if isinstance(value, (list, tuple, set)):")
    lines.append(f"{indent}    return list(value)")
    lines.append(f"{indent}return repr(value)")
    lines.append("")
    lines.append("def _to_jsonable(value):")
    lines.append(f"{indent}if isinstance(value, (str, int, float, bool)) or value is None:")
    lines.append(f"{indent}    return value")
    lines.append(f"{indent}if isinstance(value, np.generic):")
    lines.append(f"{indent}    return value.item()")
    lines.append(f"{indent}if isinstance(value, np.ndarray):")
    lines.append(f"{indent}    return value.tolist()")
    lines.append(f"{indent}if isinstance(value, dict):")
    lines.append(f"{indent}    return {{str(k): _to_jsonable(v) for k, v in value.items()}}")
    lines.append(f"{indent}if isinstance(value, (list, tuple, set)):")
    lines.append(f"{indent}    return [_to_jsonable(v) for v in value]")
    lines.append(f"{indent}if hasattr(value, 'data'):")
    lines.append(f"{indent}    return {{'type': type(value).__name__, 'shape': list(np.asarray(value.data).shape)}}")
    lines.append(f"{indent}return repr(value)")
    lines.append("")
    lines.append("def _save_json(path, value):")
    lines.append(f"{indent}with open(path, 'w') as f:")
    lines.append(f"{indent}    json.dump(value, f, indent=2, default=_json_default)")
    lines.append("")
    lines.append("def _write_array_artifact(path_stem, value):")
    lines.append(f"{indent}_arr = np.asarray(value)")
    lines.append(f"{indent}if _arr.ndim == 0:")
    lines.append(f"{indent}    _arr = _arr.reshape(1, 1)")
    lines.append(f"{indent}elif _arr.ndim == 1:")
    lines.append(f"{indent}    _arr = _arr.reshape(-1, 1)")
    lines.append(f"{indent}try:")
    lines.append(f"{indent}    if np.issubdtype(_arr.dtype, np.number) or np.issubdtype(_arr.dtype, np.bool_):")
    lines.append(f"{indent}        np.savetxt(f'{{path_stem}}.csv', _arr, delimiter=',')")
    lines.append(f"{indent}    else:")
    lines.append(f"{indent}        np.savetxt(f'{{path_stem}}.csv', _arr.astype(str), delimiter=',', fmt='%s')")
    lines.append(f"{indent}except Exception:")
    lines.append(f"{indent}    _save_json(f'{{path_stem}}.json', _arr.tolist())")
    lines.append("")

    # Data directory constant
    lines.append("# ── Data directory: place your raw spectral files here ──")
    lines.append("DATA_DIR = (")
    lines.append('    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")')
    lines.append('    if "__file__" in dir() else os.path.join(os.getcwd(), "data")')
    lines.append(")")
    lines.append("")
    lines.append("")

    # Main function
    lines.append("def run_workflow():")
    lines.append(f'{indent}"""Execute the workflow and return all intermediate results."""')
    lines.append(f'{indent}print("=" * 60)')
    lines.append(f'{indent}print("Workflow: {workflow.name}")')
    lines.append(f'{indent}print("=" * 60)')
    lines.append("")
    lines.append(f"{indent}# Store intermediate results")
    lines.append(f"{indent}results = {{}}")
    lines.append("")

    # Generate code for each node in execution order.
    # Each node block is wrapped in its own function (``_step_{id}()``) so
    # that local variables are scoped and cannot collide when two nodes of
    # the same type appear in one workflow.  ``results`` is captured by
    # closure — reads and mutations both work correctly.
    for node_id in execution_order:
        node = node_map[node_id]
        safe_nid = _safe_identifier(node_id)
        step_indent = indent + "    "

        lines.append(f"{indent}def _step_{safe_nid}():")
        node_lines = _generate_node_python_lines(node_id, node, edges, dict_output_nodes, step_indent, use_scp)
        lines.extend(node_lines)

        # Validate: every node must store its result in results[node_id]
        node_code = "\n".join(node_lines)
        if f"results['{node_id}']" not in node_code:
            logger.warning(
                "Node %s (%s) generate_python() does not set results['%s']",
                node_id,
                node.metadata.node_type,
                node_id,
            )

        lines.append(f"{indent}_step_{safe_nid}()")
        lines.append("")

    # Return
    lines.append(f"{indent}return results")
    lines.append("")
    lines.append("")

    # Artifact export function
    wf_name_safe = workflow.name.replace(" ", "_").replace("/", "_")
    lines.append("")
    lines.append("def export_artifacts(results, workflow_name='{0}'):".format(wf_name_safe))
    lines.append(f'{indent}"""Save all artifacts to individual files and zip them."""')
    lines.append(f"{indent}import pickle")
    lines.append(f'{indent}timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")')
    lines.append(f'{indent}out_dir = f"{{workflow_name}}_{{timestamp}}"')
    lines.append(f"{indent}os.makedirs(out_dir, exist_ok=True)")
    lines.append(f'{indent}print(f"\\nExporting artifacts to {{out_dir}}/")')
    lines.append("")
    lines.append(f"{indent}for key, value in results.items():")
    lines.append(f"{indent}    if isinstance(value, SherpaDataset):")
    lines.append(f"{indent}        _write_array_artifact(os.path.join(out_dir, f'{{key}}_data'), value.data)")
    lines.append(f"{indent}        _meta = {{'shape': list(np.asarray(value.data).shape)}}")
    lines.append(f"{indent}        if value.feature_axis is not None:")
    lines.append(f"{indent}            _meta['feature_axis'] = np.asarray(value.feature_axis.data).tolist()")
    lines.append(f"{indent}        if value.target is not None:")
    lines.append(f"{indent}            _write_array_artifact(os.path.join(out_dir, f'{{key}}_target'), value.target)")
    lines.append(f"{indent}        _save_json(os.path.join(out_dir, f'{{key}}_meta.json'), _meta)")
    lines.append(f"{indent}    elif isinstance(value, dict):")
    lines.append(f"{indent}        # Save each sub-artifact")
    lines.append(f"{indent}        _summary = {{}}")
    lines.append(f"{indent}        for sub_key, sub_val in value.items():")
    lines.append(f"{indent}            _fname = f'{{key}}_{{sub_key}}'")
    lines.append(f"{indent}            if isinstance(sub_val, SherpaDataset):")
    lines.append(f"{indent}                _write_array_artifact(os.path.join(out_dir, _fname), sub_val.data)")
    lines.append(f"{indent}            elif isinstance(sub_val, np.ndarray):")
    lines.append(f"{indent}                _write_array_artifact(os.path.join(out_dir, _fname), sub_val)")
    lines.append(f"{indent}            elif hasattr(sub_val, 'predict'):  # model object")
    lines.append(f"{indent}                with open(os.path.join(out_dir, f'{{_fname}}.pkl'), 'wb') as f:")
    lines.append(f"{indent}                    pickle.dump(sub_val, f)")
    lines.append(f"{indent}            else:")
    lines.append(f"{indent}                _summary[sub_key] = _to_jsonable(sub_val)")
    lines.append(f"{indent}        if _summary:")
    lines.append(f"{indent}            _save_json(os.path.join(out_dir, f'{{key}}_summary.json'), _summary)")
    lines.append(f"{indent}    elif isinstance(value, np.ndarray):")
    lines.append(f"{indent}        _write_array_artifact(os.path.join(out_dir, key), value)")
    lines.append(f"{indent}    else:")
    lines.append(f"{indent}        _save_json(os.path.join(out_dir, f'{{key}}.json'), _to_jsonable(value))")
    lines.append("")
    lines.append(f"{indent}# Save matplotlib figures if any")
    lines.append(f"{indent}try:")
    lines.append(f"{indent}    import matplotlib.pyplot as _plt")
    lines.append(f"{indent}    for i, fig in enumerate(_plt.get_fignums()):")
    lines.append(f"{indent}        _plt.figure(fig).savefig(")
    lines.append(f"{indent}            os.path.join(out_dir, f'figure_{{i+1}}.png'),")
    lines.append(f"{indent}            dpi=150, bbox_inches='tight',")
    lines.append(f"{indent}        )")
    lines.append(f"{indent}except Exception:")
    lines.append(f"{indent}    pass")
    lines.append("")
    lines.append(f"{indent}# Zip everything")
    lines.append(f"{indent}zip_name = f'{{out_dir}}.zip'")
    lines.append(f"{indent}with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zf:")
    lines.append(f"{indent}    for root, dirs, files in os.walk(out_dir):")
    lines.append(f"{indent}        for file in files:")
    lines.append(f"{indent}            fpath = os.path.join(root, file)")
    lines.append(f"{indent}            zf.write(fpath, os.path.relpath(fpath, os.path.dirname(out_dir)))")
    lines.append(f'{indent}print(f"  Artifacts zipped to {{zip_name}}")')
    lines.append(f"{indent}return zip_name")
    lines.append("")
    lines.append("")

    # Main block
    lines.append('if __name__ == "__main__":')
    lines.append(f"{indent}results = run_workflow()")
    lines.append("")
    lines.append(f'{indent}print("\\nWorkflow completed successfully!")')
    lines.append(f"{indent}for key, value in results.items():")
    lines.append(f"{indent}    vtype = type(value).__name__")
    lines.append(f"{indent}    if isinstance(value, SherpaDataset):")
    lines.append(f'{indent}        print(f"  {{key}}: SherpaDataset {{np.asarray(value.data).shape}}")')
    lines.append(f"{indent}    elif isinstance(value, dict):")
    lines.append(f'{indent}        print(f"  {{key}}: dict with keys {{list(value.keys())}}")')
    lines.append(f"{indent}    else:")
    lines.append(f'{indent}        print(f"  {{key}}: {{vtype}}")')
    lines.append("")
    lines.append(f"{indent}# Export all artifacts to a timestamped zip file")
    lines.append(f"{indent}export_artifacts(results)")
    lines.append("")

    return "\n".join(lines)
