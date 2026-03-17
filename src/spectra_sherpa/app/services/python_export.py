"""
Python code generator for workflows.

Exports workflows as standalone executable Python scripts by delegating
code generation to each node's ``generate_python()`` method.  The exporter
handles only orchestration: topological sort, import collection, and
stitching the final script.

The generated code is styled for readability:
- Each workflow step is a named top-level function
- ``run_workflow()`` reads as a linear recipe
- Utility code lives in ``export_utils`` (not inlined)
- ``SherpaDataset`` is the visible first-class data object
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
    from spectra_sherpa.app.services.workflow_export_context import SourceExportSpec, WorkflowExportContext

logger = logging.getLogger(__name__)


def _safe_identifier(node_id: str) -> str:
    """Convert *node_id* to a valid Python identifier suffix."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", node_id)


# ── Variable naming ──────────────────────────────────────────────

_TYPE_TO_VARNAME: dict[str, str] = {
    "data.source": "data",
    "data.transform": "transformed",
    "preprocess.normalize": "normalized",
    "preprocess.smooth": "smoothed",
    "preprocess.scale": "scaled",
    "preprocess.derivative": "derivative",
    "preprocess.clip_range": "clipped",
    "baseline.penalized_ls": "baseline_corrected",
    "baseline.rubberband": "baseline_corrected",
    "model.pca": "pca_result",
    "model.pls": "pls_result",
    "model.mcr_als": "mcr_result",
    "model.simplisma": "simplisma_result",
    "model.efa": "efa_result",
    "model.hca": "hca_result",
    "model.pls_predict": "pls_prediction",
    "classification.plsda": "plsda_result",
    "classification.knn": "knn_result",
    "classification.simca": "simca_result",
    "classification.predict": "prediction",
    "selection.sample_partition": "partition",
    "selection.variable_select": "selected_vars",
    "selection.nested_cv": "nested_cv_result",
    "transfer.pds": "pds_result",
    "transfer.sbc": "sbc_result",
    "output.plot": "figure",
    "output.export": "exported",
    "stats.summary": "statistics",
    "diagnostics.outliers": "outliers",
    "diagnostics.cross_validation": "cv_result",
    "analysis.peak_finding": "peaks",
    "deploy.input": "deploy_input",
    "deploy.output": "deploy_output",
}


def _derive_function_name(node_id: str, node_type: str, label: str) -> str:
    """Derive a clean function name from node metadata.

    Uses the node label (user-provided) when available, falling back
    to the node type.  Deduplication is handled by the caller.
    """
    # Use label if meaningful, otherwise fall back to type
    raw = label or node_type.replace(".", "_")
    # Convert to snake_case
    name = re.sub(r"[^a-zA-Z0-9]+", "_", raw).strip("_").lower()
    # Collapse repeated underscores
    name = re.sub(r"_+", "_", name)
    # Ensure it doesn't start with a digit
    if name and name[0].isdigit():
        name = f"step_{name}"
    return name or f"step_{_safe_identifier(node_id)}"


def _derive_variable_name(node_id: str, node_type: str) -> str:
    """Derive a readable variable name for a node's output."""
    return _TYPE_TO_VARNAME.get(node_type, _safe_identifier(node_id))


def _deduplicate_names(names: list[tuple[str, str]]) -> dict[str, str]:
    """Given (node_id, desired_name) pairs, return {node_id: unique_name}.

    Appends _2, _3, etc. for collisions.
    """
    counts: dict[str, int] = {}
    result: dict[str, str] = {}
    for node_id, name in names:
        counts[name] = counts.get(name, 0) + 1
    # Second pass: assign with suffix if needed
    used: dict[str, int] = {}
    for node_id, name in names:
        if counts[name] > 1:
            used[name] = used.get(name, 0) + 1
            result[node_id] = f"{name}_{used[name]}"
        else:
            result[node_id] = name
    return result


@dataclass
class ExportValidationError:
    """Describes a node that cannot be exported."""

    node_id: str
    node_type: str
    reason: str


# ── Source node code generation ───────────────────────────────────


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


def _inject_prepared_override_lines(
    lines: list[str],
    node_id: str,
    spec: "SourceExportSpec | None",
    indent: str,
) -> list[str]:
    if spec is None or spec.overrides.is_empty():
        return lines

    insert_at = next((idx for idx, line in enumerate(lines) if f"results['{node_id}']" in line), len(lines))
    return lines[:insert_at] + _generate_prepared_override_lines("_ds", spec, indent) + lines[insert_at:]


def _generate_prepared_override_lines(dataset_expr: str, spec: "SourceExportSpec", indent: str) -> list[str]:
    safe_id = _safe_identifier(spec.node_id)
    lines: list[str] = []
    lines.append(f"{indent}# Replay Data/Explore overrides for {spec.node_id}")

    if spec.overrides.x_title is not None or spec.overrides.x_units is not None:
        lines.append(f"{indent}if getattr({dataset_expr}, 'feature_axis', None) is not None:")
        lines.append(f"{indent}    _feature_axis_{safe_id} = {dataset_expr}.feature_axis.copy()")
        if spec.overrides.x_title is not None:
            lines.append(f"{indent}    _feature_axis_{safe_id}.title = {spec.overrides.x_title!r}")
            lines.append(f"{indent}    {dataset_expr}.meta['x_title'] = {spec.overrides.x_title!r}")
        if spec.overrides.x_units is not None:
            lines.append(
                f"{indent}    _feature_axis_{safe_id}.units = "
                f"{repr(spec.overrides.x_units) if spec.overrides.x_units else 'None'}"
            )
            lines.append(f"{indent}    {dataset_expr}.meta['x_units'] = {spec.overrides.x_units!r}")
        lines.append(f"{indent}    {dataset_expr}.feature_axis = _feature_axis_{safe_id}")

    if spec.overrides.y_title is not None or spec.overrides.x_units is not None:
        lines.append(f"{indent}_domain_{safe_id} = {dataset_expr}.domain.model_copy(deep=True)")
        if spec.overrides.x_units is not None:
            lines.append(
                f"{indent}_domain_{safe_id}.expected_units = "
                f"{repr(spec.overrides.x_units) if spec.overrides.x_units else 'None'}"
            )
        if spec.overrides.y_title is not None:
            lines.append(f"{indent}_domain_{safe_id}.data_quantity = {spec.overrides.y_title!r}")
            lines.append(f"{indent}{dataset_expr}.meta['data_quantity'] = {spec.overrides.y_title!r}")
        lines.append(f"{indent}{dataset_expr}.domain = _domain_{safe_id}")

    if spec.overrides.is_time_series is not None:
        lines.append(f"{indent}{dataset_expr}.is_time_series = {spec.overrides.is_time_series!r}")
        lines.append(f"{indent}{dataset_expr}.meta['is_time_series'] = {spec.overrides.is_time_series!r}")

    return lines


def _generate_bundled_source_lines(
    node_id: str,
    node,
    spec: "SourceExportSpec",
    indent: str,
    is_multi_port: bool,
    use_scp: bool,
) -> list[str]:
    safe_id = _safe_identifier(node_id)
    lines: list[str] = []
    lines.append(f"{indent}# --- Data Source ({node_id}) — bundled files ---")

    if spec.loader_mode == "single_file":
        bundle_file = spec.bundle_files[0]
        lines.append(f"{indent}_bundle_path_{safe_id} = os.path.join(DATA_DIR, {bundle_file.bundle_relative_path!r})")
        lines.append(f"{indent}if _bundle_path_{safe_id}.lower().endswith('.csv'):")
        lines.append(f"{indent}    from spectra_sherpa.app.lib.io import load_csv_as_sherpa")
        lines.append(f"{indent}    _ds = load_csv_as_sherpa(_bundle_path_{safe_id})")
        lines.append(f"{indent}else:")
        lines.append(f"{indent}    if not {use_scp!r}:")
        lines.append(f"{indent}        raise ImportError('SpectroChemPy is required for non-CSV bundled data export')")
        lines.append(f"{indent}    from spectra_sherpa.app.lib.scp_compat import from_nddataset")
        lines.append(f"{indent}    _ndd = scp.read(_bundle_path_{safe_id})")
        lines.append(f"{indent}    _ds = from_nddataset(_ndd)")
        lines.extend(_generate_prepared_override_lines("_ds", spec, indent))
        lines.append(f'{indent}print(f"  Data Source ({node_id}): {{_ds.shape}} from bundled file")')
        if is_multi_port:
            lines.append(f"{indent}results['{node_id}'] = {{'default': _ds, 'target': _ds.target}}")
        else:
            lines.append(f"{indent}results['{node_id}'] = _ds")
        return lines

    lines.append(f"{indent}from spectra_sherpa.app.lib.scp_compat import from_nddataset")
    lines.append(f"{indent}from spectra_sherpa.app.services.dag.nodes.data.loaders import MyDatasetNode")
    lines.append(f"{indent}_loader_{safe_id} = MyDatasetNode({node_id!r}, {{'dataset_id': 0}})")
    lines.append(f"{indent}_loaded_{safe_id} = []")
    for bundle_file in spec.bundle_files:
        lines.append(
            f"{indent}_loaded_{safe_id}.append("
            f"_loader_{safe_id}._load_file("
            f"os.path.join(DATA_DIR, {bundle_file.bundle_relative_path!r}), "
            f"file_name={bundle_file.bundle_relative_path!r}"
            f"))"
        )
    lines.append(f"{indent}_groups_{safe_id} = _loader_{safe_id}._group_by_x_axis(_loaded_{safe_id})")
    lines.append(
        f"{indent}_groups_{safe_id}.sort("
        f"key=lambda _group: _loader_{safe_id}._x_length(_group[0].dataset), reverse=True"
        f")"
    )
    lines.append(f"{indent}_spectra_group_{safe_id} = _groups_{safe_id}[0]")
    lines.append(
        f"{indent}_embedded_target_{safe_id} = "
        f"_loader_{safe_id}._combine_embedded_targets(_spectra_group_{safe_id})"
    )
    lines.append(f"{indent}_spectra_items_{safe_id} = [item.dataset for item in _spectra_group_{safe_id}]")
    lines.append(f"{indent}_spectra_names_{safe_id} = [item.file_name for item in _spectra_group_{safe_id}]")
    lines.append(f"{indent}_spectra_{safe_id} = (")
    lines.append(
        f"{indent}    _loader_{safe_id}._concatenate(_spectra_items_{safe_id}, _spectra_names_{safe_id}) "
        f"if len(_spectra_items_{safe_id}) > 1 else _spectra_items_{safe_id}[0]"
    )
    lines.append(f"{indent})")
    lines.append(f"{indent}_ds = from_nddataset(_spectra_{safe_id})")
    lines.append(f"{indent}if _embedded_target_{safe_id} is not None:")
    lines.append(
        f"{indent}    _embedded_target_data_{safe_id}, "
        f"_embedded_target_names_{safe_id} = _embedded_target_{safe_id}"
    )
    lines.append(f"{indent}    _ds.target = _embedded_target_data_{safe_id}")
    lines.append(f"{indent}    _ds.target_context = TargetContext(")
    lines.append(f"{indent}        target_type='continuous',")
    lines.append(f"{indent}        target_names=_embedded_target_names_{safe_id},")
    lines.append(f"{indent}    )")
    lines.extend(_generate_prepared_override_lines("_ds", spec, indent))
    lines.append(f'{indent}print(f"  Data Source ({node_id}): {{_ds.shape}} from bundled folder")')
    if is_multi_port:
        lines.append(f"{indent}results['{node_id}'] = {{'default': _ds, 'target': _ds.target}}")
    else:
        lines.append(f"{indent}results['{node_id}'] = _ds")
    return lines


# ── Per-node code generation ─────────────────────────────────────


def _generate_node_python_lines(
    node_id: str,
    node,
    edges: list[Edge],
    dict_output_nodes: frozenset[str],
    indent: str,
    use_scp: bool,
    export_context: "WorkflowExportContext | None" = None,
) -> list[str]:
    """Generate the code block for a single workflow node."""
    input_map = build_input_map(node_id, edges, dict_output_nodes=dict_output_nodes)
    if not input_map:
        used_ports = {e.from_output or "default" for e in edges if e.from_node == node_id}
        is_multi_port = len(used_ports) > 1
        spec = export_context.source_spec_for(node_id) if export_context is not None else None
        if spec is not None and spec.loader_mode != "builtin":
            return _generate_bundled_source_lines(node_id, node, spec, indent, is_multi_port, use_scp)
        if node.supports_python_export():
            export_inputs = {"_multi_port": str(is_multi_port)}
            return _inject_prepared_override_lines(
                node.generate_python(export_inputs, indent=indent, use_scp=use_scp),
                node_id,
                spec,
                indent,
            )
        return _generate_source_placeholder_lines(node_id, node, edges, indent)
    return node.generate_python(input_map, indent=indent, use_scp=use_scp)


# ── Export validation ─────────────────────────────────────────────


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


# ── Main code generator ──────────────────────────────────────────


def generate_python_code(
    workflow: Workflow,
    export_context: "WorkflowExportContext | None" = None,
) -> str:
    """
    Generate executable Python code from a workflow.

    Produces clean, sklearn-styled code with:
    - Named top-level functions for each workflow step
    - A linear ``run_workflow()`` that reads like a recipe
    - ``SherpaDataset`` as the visible first-class data object
    - Utilities imported from ``export_utils`` (not inlined)

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
    node_type_map = {}
    node_label_map = {}
    for wf_node in workflow.nodes:
        node_map[wf_node.node_id] = node_registry.create_node(wf_node.node_type, wf_node.node_id, wf_node.parameters)
        node_type_map[wf_node.node_id] = wf_node.node_type
        try:
            meta = node_registry.get_metadata(wf_node.node_type)
            node_label_map[wf_node.node_id] = meta.label
        except (KeyError, AttributeError):
            node_label_map[wf_node.node_id] = wf_node.node_type

    # --- backend mode (SCP vs numpy) --------------------------------------
    use_scp = HAS_SCP

    # --- collect extra imports -------------------------------------------
    extra_imports: set[str] = set()
    for node in node_map.values():
        for imp in node.python_extra_imports:
            extra_imports.add(imp)

    # --- identify dict-emitting nodes ------------------------------------
    nodes_with_incoming = {e.to_node for e in edges}
    dict_output_nodes = frozenset(
        nid for nid, node in node_map.items() if nid in nodes_with_incoming and node.exported_output_ports() is not None
    )

    # --- derive clean function names -------------------------------------
    raw_func_names = [
        (nid, _derive_function_name(nid, node_type_map[nid], node_label_map.get(nid, "")))
        for nid in execution_order
    ]
    func_names = _deduplicate_names(raw_func_names)

    # --- build code lines ------------------------------------------------
    indent = "    "
    lines: list[str] = []

    # ── Header ──
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

    # ── Imports ──
    lines.append("import os")
    lines.append("")
    lines.append("import numpy as np")
    if use_scp:
        lines.append("import spectrochempy as scp")
        lines.append("from spectrochempy import NDDataset")
    lines.append("from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext")
    lines.append("from spectra_sherpa.app.services.export_utils import export_artifacts")
    lines.append("")

    # Extra imports from nodes (deduplicated, skip already-present)
    base_imports = {
        "import numpy as np",
        "import os",
        "from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext",
        "from spectra_sherpa.app.services.export_utils import export_artifacts",
    }
    if use_scp:
        base_imports |= {"import spectrochempy as scp", "from spectrochempy import NDDataset"}
    for imp in sorted(extra_imports - base_imports):
        if not use_scp and "spectrochempy" in imp:
            continue
        lines.append(imp)
    if extra_imports - base_imports:
        lines.append("")

    # ── Data directory ──
    data_env_var = export_context.data_env_var if export_context is not None else "SHERPA_DATA_DIR"
    lines.append("# Data directory — defaults to ./data, override with SHERPA_DATA_DIR")
    lines.append("DATA_DIR = os.environ.get(")
    lines.append(f"    {data_env_var!r},")
    lines.append('    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")')
    lines.append('    if "__file__" in dir() else os.path.join(os.getcwd(), "data"),')
    lines.append(")")
    lines.append("")
    lines.append("")

    # ── Step functions (one per node) ──
    # Each node's code is wrapped in a named function. The function
    # takes no arguments (reads from `results` by closure) but has a
    # clear name and docstring describing what it does.
    for step_idx, node_id in enumerate(execution_order):
        node = node_map[node_id]
        fn_name = func_names[node_id]
        label = node_label_map.get(node_id, node_type_map[node_id])
        step_indent = indent

        lines.append(f"def {fn_name}(results):")
        lines.append(f'{step_indent}"""Step {step_idx + 1}: {label}."""')

        node_lines = _generate_node_python_lines(
            node_id,
            node,
            edges,
            dict_output_nodes,
            step_indent,
            use_scp,
            export_context,
        )
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

        lines.append("")
        lines.append("")

    # ── run_workflow() — the linear recipe ──
    lines.append("def run_workflow():")
    lines.append(f'{indent}"""Execute the workflow and return all intermediate results."""')
    lines.append(f"{indent}results = {{}}")
    lines.append("")

    for step_idx, node_id in enumerate(execution_order):
        fn_name = func_names[node_id]
        label = node_label_map.get(node_id, node_type_map[node_id])
        lines.append(f"{indent}# Step {step_idx + 1}: {label}")
        lines.append(f"{indent}{fn_name}(results)")
        lines.append("")

    lines.append(f"{indent}return results")
    lines.append("")
    lines.append("")

    # ── Main block ──
    wf_name_safe = workflow.name.replace(" ", "_").replace("/", "_")
    lines.append('if __name__ == "__main__":')
    lines.append(f"{indent}results = run_workflow()")
    lines.append("")
    lines.append(f'{indent}print("\\nWorkflow: {workflow.name}")')
    lines.append(f'{indent}print("=" * 60)')
    lines.append(f"{indent}for key, value in results.items():")
    lines.append(f"{indent}    if isinstance(value, SherpaDataset):")
    lines.append(f'{indent}        print(f"  {{key}}: SherpaDataset {{value.shape}}")')
    lines.append(f"{indent}    elif isinstance(value, dict):")
    lines.append(f'{indent}        print(f"  {{key}}: {{list(value.keys())}}")')
    lines.append(f"{indent}    else:")
    lines.append(f'{indent}        print(f"  {{key}}: {{type(value).__name__}}")')
    lines.append("")
    lines.append(f"{indent}export_artifacts(results, {wf_name_safe!r})")
    lines.append("")

    return "\n".join(lines)
