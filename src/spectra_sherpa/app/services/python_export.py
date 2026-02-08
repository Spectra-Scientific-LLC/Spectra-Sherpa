"""
Python code generator for workflows.

Exports workflows as standalone executable Python scripts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.workflow import Workflow
    from app.services.dag.executor import DAGExecutor


def generate_python_code(workflow: Workflow) -> str:
    """
    Generate executable Python code from a workflow.

    Args:
        workflow: Workflow model with nodes and edges

    Returns:
        Python code as a string
    """
    # Build dependency graph
    deps = {node.node_id: [] for node in workflow.nodes}
    for edge in workflow.edges:
        deps[edge.to_node_id].append(edge.from_node_id)

    # Topological sort for execution order
    execution_order = _topological_sort(deps)

    # Generate code
    lines = []

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
    lines.append("import asyncio")
    lines.append("import numpy as np")
    lines.append("import spectrochempy as scp")
    lines.append("from spectrochempy import NDDataset")
    lines.append("")

    # Determine unique imports needed
    node_types = {node.node_type for node in workflow.nodes}
    if any("model." in nt for nt in node_types):
        lines.append("# Modeling imports")
        if "model.pls" in node_types:
            lines.append("from sklearn.cross_decomposition import PLSRegression")
        if "model.linear_regression" in node_types:
            lines.append("from sklearn.linear_model import LinearRegression")
        lines.append("")

    # Main async function
    lines.append("")
    lines.append("async def run_workflow():")
    lines.append('    """Execute the workflow."""')
    lines.append('    print("=" * 60)')
    lines.append(f'    print("Workflow: {workflow.name}")')
    lines.append('    print("=" * 60)')
    lines.append("")

    # Add results dict
    lines.append("    # Store intermediate results")
    lines.append("    results = {}")
    lines.append("")

    # Generate code for each node in execution order
    node_map = {node.node_id: node for node in workflow.nodes}

    for node_id in execution_order:
        node = node_map[node_id]
        lines.extend(_generate_node_code(node, deps, 1))  # indent level 1
        lines.append("")

    # Return statement
    lines.append("    return results")
    lines.append("")
    lines.append("")

    # Main block
    lines.append('if __name__ == "__main__":')
    lines.append("    # Run the workflow")
    lines.append("    results = asyncio.run(run_workflow())")
    lines.append("")
    lines.append('    print("\\n\\nWorkflow completed successfully!")')
    lines.append("")

    return "\n".join(lines)


def _generate_node_code(
    node: Any, deps: dict[str, list[str]], indent_level: int = 0
) -> list[str]:
    """
    Generate Python code for a single node.

    Args:
        node: WorkflowNode model
        deps: Dependency graph
        indent_level: Indentation level

    Returns:
        List of code lines
    """
    indent = "    " * indent_level
    lines = []

    # Comment header
    lines.append(f"{indent}# Node: {node.node_id} ({node.node_type})")

    # Get input from dependencies
    node_deps = deps.get(node.node_id, [])
    if node_deps:
        input_var = f"results['{node_deps[0]}']"
    else:
        # Source node - needs data from user
        lines.append(f"{indent}# TODO: Provide input data for '{node.node_id}'")
        lines.append(
            f"{indent}# For example: results['{node.node_id}'] = your_nddataset"
        )
        lines.append(f"{indent}# Skipping this node for now")
        lines.append(f"{indent}pass")
        return lines

    # Generate node-specific code
    node_type = node.node_type

    if node_type == "smooth.savitzky_golay":
        lines.extend(
            _generate_smooth_code(node, input_var, indent_level)
        )

    elif node_type.startswith("baseline."):
        lines.extend(_generate_baseline_code(node, input_var, indent_level))

    elif node_type.startswith("normalize."):
        lines.extend(_generate_normalize_code(node, input_var, indent_level))

    elif node_type.startswith("derivative."):
        lines.extend(_generate_derivative_code(node, input_var, indent_level))

    elif node_type == "model.pca":
        lines.extend(_generate_pca_code(node, input_var, indent_level))

    elif node_type == "model.pls":
        lines.extend(_generate_pls_code(node, input_var, indent_level))

    elif node_type == "model.linear_regression":
        lines.extend(_generate_linear_regression_code(node, input_var, indent_level))

    else:
        lines.append(f"{indent}# Unknown node type: {node_type}")
        lines.append(f"{indent}pass")

    return lines


def _generate_smooth_code(node: Any, input_var: str, indent_level: int) -> list[str]:
    """Generate code for Savitzky-Golay smoothing node."""
    indent = "    " * indent_level
    lines = []

    size = node.parameters.get("size", 11)
    order = node.parameters.get("order", 2)

    lines.append(f"{indent}data = {input_var}.copy()")
    lines.append(f"{indent}data.smooth(size={size}, order={order})")
    lines.append(f"{indent}results['{node.node_id}'] = data")

    return lines


def _generate_baseline_code(node: Any, input_var: str, indent_level: int) -> list[str]:
    """Generate code for baseline correction nodes."""
    indent = "    " * indent_level
    lines = []

    lines.append(f"{indent}data = {input_var}.copy()")

    if node.node_type == "baseline.als":
        lam = node.parameters.get("lam", 1e5)
        p = node.parameters.get("p", 0.001)
        lines.append(f"{indent}data.basc(lamb={lam}, asymmetry={p})")
    elif node.node_type == "baseline.rubberband":
        lines.append(f"{indent}data.basc(method='rubberband')")

    lines.append(f"{indent}results['{node.node_id}'] = data")

    return lines


def _generate_normalize_code(
    node: Any, input_var: str, indent_level: int
) -> list[str]:
    """Generate code for normalization nodes."""
    indent = "    " * indent_level
    lines = []

    lines.append(f"{indent}data = {input_var}.copy()")

    if node.node_type == "normalize.snv":
        lines.append(f"{indent}data.snv()")
    elif node.node_type == "normalize.msc":
        reference = node.parameters.get("reference", "mean")
        lines.append(f"{indent}data.msc(reference='{reference}')")

    lines.append(f"{indent}results['{node.node_id}'] = data")

    return lines


def _generate_derivative_code(
    node: Any, input_var: str, indent_level: int
) -> list[str]:
    """Generate code for derivative nodes."""
    indent = "    " * indent_level
    lines = []

    size = node.parameters.get("size", 11)
    order = node.parameters.get("order", 2)

    lines.append(f"{indent}data = {input_var}.copy()")

    if node.node_type == "derivative.first":
        lines.append(f"{indent}data.deriv(size={size}, order={order}, deriv=1)")
    elif node.node_type == "derivative.second":
        lines.append(f"{indent}data.deriv(size={size}, order={order}, deriv=2)")

    lines.append(f"{indent}results['{node.node_id}'] = data")

    return lines


def _generate_pca_code(node: Any, input_var: str, indent_level: int) -> list[str]:
    """Generate code for PCA node."""
    indent = "    " * indent_level
    lines = []

    n_components = node.parameters.get("n_components", 5)
    standardized = node.parameters.get("standardized", False)
    scaled = node.parameters.get("scaled", False)

    # Quote n_components if it's a string (e.g., "mle", "auto")
    n_components_str = f'"{n_components}"' if isinstance(n_components, str) else str(n_components)

    lines.append(f"{indent}# Perform PCA")
    lines.append(
        f"{indent}pca = scp.PCA(n_components={n_components_str}, standardized={standardized}, scaled={scaled})"
    )
    lines.append(f"{indent}pca.fit({input_var})")
    lines.append("")
    lines.append(f"{indent}# Store PCA results")
    lines.append(f"{indent}pca_result = {{")
    lines.append(f"{indent}    'model': pca,")
    lines.append(f"{indent}    'scores': pca.transform(),")
    lines.append(f"{indent}    'loadings': pca.components,")
    lines.append(f"{indent}    'explained_variance': pca.explained_variance,")
    lines.append(
        f"{indent}    'explained_variance_ratio': pca.explained_variance_ratio,"
    )
    lines.append(f"{indent}    'n_components': {n_components},")
    lines.append(f"{indent}}}")
    lines.append(f"{indent}results['{node.node_id}'] = pca_result")
    lines.append("")
    lines.append(
        f"{indent}print(f'PCA: {{pca.explained_variance_ratio.sum():.2%}} variance explained')"
    )

    return lines


def _generate_pls_code(node: Any, input_var: str, indent_level: int) -> list[str]:
    """Generate code for PLS node."""
    indent = "    " * indent_level
    lines = []

    n_components = node.parameters.get("n_components", 3)
    scale = node.parameters.get("scale", True)

    lines.append(f"{indent}# TODO: Provide y data for PLS regression")
    lines.append(f"{indent}# y = your_target_values")
    lines.append("")
    lines.append(f"{indent}# pls = PLSRegression(n_components={n_components}, scale={scale})")
    lines.append(f"{indent}# pls.fit({input_var}.data, y)")
    lines.append(f"{indent}# results['{node.node_id}'] = {{'model': pls}}")

    return lines


def _generate_linear_regression_code(
    node: Any, input_var: str, indent_level: int
) -> list[str]:
    """Generate code for linear regression node."""
    indent = "    " * indent_level
    lines = []

    fit_intercept = node.parameters.get("fit_intercept", True)

    lines.append(f"{indent}# TODO: Provide X and y data for linear regression")
    lines.append(f"{indent}# X = your_feature_matrix")
    lines.append(f"{indent}# y = your_target_values")
    lines.append("")
    lines.append(
        f"{indent}# model = LinearRegression(fit_intercept={fit_intercept})"
    )
    lines.append(f"{indent}# model.fit(X, y)")
    lines.append(f"{indent}# results['{node.node_id}'] = {{'model': model}}")

    return lines


def _topological_sort(deps: dict[str, list[str]]) -> list[str]:
    """
    Perform topological sort on dependency graph.

    Args:
        deps: Dict mapping node_id to list of dependencies

    Returns:
        List of node IDs in execution order
    """
    in_degree = {node_id: len(dep_list) for node_id, dep_list in deps.items()}
    queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
    result = []

    # Build reverse dependency map (who depends on me?)
    reverse_deps = {node_id: [] for node_id in deps}
    for node_id, dep_list in deps.items():
        for dep in dep_list:
            reverse_deps[dep].append(node_id)

    while queue:
        node_id = queue.pop(0)
        result.append(node_id)

        # Reduce in-degree for dependent nodes
        for dependent in reverse_deps.get(node_id, []):
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                queue.append(dependent)

    if len(result) != len(deps):
        raise ValueError("Workflow contains cycles - cannot export")

    return result
