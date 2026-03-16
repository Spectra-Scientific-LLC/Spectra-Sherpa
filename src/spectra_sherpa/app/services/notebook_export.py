"""
Jupyter notebook generator for workflows.

Generates a per-node cell notebook with:
- Markdown cell before each step explaining what it does
- Code cell for the computation
- Inspection cells after key nodes (print shape, peek at data)
- Getting Started guide at the top
- Artifact export at the bottom

Falls back to splitting ``python_export.generate_python_code()`` for
the import preamble, but builds node cells directly from the DAG
structure for a true per-step interactive experience.

No external dependencies — ``.ipynb`` is just JSON.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spectra_sherpa.app.lib.scp_compat import HAS_SCP
from spectra_sherpa.app.services.dag.graph_utils import Edge, topological_sort
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.python_export import _generate_node_python_lines, generate_python_code

if TYPE_CHECKING:
    from spectra_sherpa.app.models.workflow import Workflow


# Standard Jupyter notebook metadata (Python 3 kernel)
NOTEBOOK_METADATA: dict = {
    "kernelspec": {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    },
    "language_info": {
        "codemirror_mode": {"name": "ipython", "version": 3},
        "file_extension": ".py",
        "mimetype": "text/x-python",
        "name": "python",
        "nbconvert_exporter": "python",
        "pygments_lexer": "ipython3",
        "version": "3.11.0",
    },
}

# Node descriptions for beginner chemometricians
_NODE_GUIDES: dict[str, str] = {
    "data.source": (
        "This step loads the spectral data into memory. "
        "The data is stored as a `SherpaDataset` — a rich container that "
        "holds the spectral matrix, wavelength/wavenumber axis, sample labels, "
        "and target values (if available)."
    ),
    "preprocess.smooth": (
        "Smoothing reduces high-frequency noise in the spectra using algorithms like "
        "Savitzky-Golay. This makes downstream analysis (PCA, PLS) more stable. "
        "Inspect the before/after to ensure genuine spectral features are preserved."
    ),
    "preprocess.normalize": (
        "Normalization scales each spectrum to a common magnitude, correcting for "
        "differences in path length or sample thickness. Common methods: SNV "
        "(Standard Normal Variate) divides by the spectrum's own standard deviation."
    ),
    "preprocess.scale": (
        "Autoscaling (mean-centering + unit-variance) treats every variable equally. "
        "This is essential before PCA/PLS when different spectral regions have "
        "different magnitudes."
    ),
    "preprocess.derivative": (
        "Taking derivatives removes baseline offsets (1st derivative) or both "
        "baseline and slope (2nd derivative). Savitzky-Golay derivatives also smooth. "
        "Higher derivatives increase noise — check the result carefully."
    ),
    "preprocess.clip_range": (
        "Spectral region selection — keep only the wavelengths/wavenumbers of interest. "
        "This removes uninformative regions (e.g., CO2 bands in IR, solvent peaks in NMR)."
    ),
    "baseline.penalized_ls": (
        "Baseline correction using penalized least squares (AsLS, ArPLS, or AirPLS). "
        "This removes the slowly-varying baseline that obscures spectral features. "
        "The smoothness parameter (lambda) controls how stiff the baseline is."
    ),
    "baseline.rubberband": (
        "Rubberband baseline correction fits a convex hull under the spectrum, "
        "then subtracts it. Works well for spectra with clear minima at the edges."
    ),
    "model.pca": (
        "Principal Component Analysis (PCA) decomposes the data into orthogonal "
        "components that capture maximum variance. **Scores** show how samples relate "
        "to each other; **loadings** show which wavelengths drive the variation. "
        "Check the explained variance — the first 2-3 PCs should capture >90%."
    ),
    "model.pls": (
        "Partial Least Squares (PLS) regression finds latent variables that maximize "
        "covariance between spectra (X) and target properties (y). The number of "
        "components controls model complexity — too many leads to overfitting. "
        "Evaluate with R² (closeness of fit) and RMSE (prediction error)."
    ),
    "model.mcr_als": (
        "Multivariate Curve Resolution with Alternating Least Squares (MCR-ALS) "
        "decomposes spectra into pure component spectra and their concentrations. "
        "Non-negativity constraints ensure physically meaningful results."
    ),
    "model.simplisma": (
        "SIMPLISMA identifies the purest variables (wavelengths) in a mixture dataset. "
        "These pure spectra serve as initial estimates for MCR-ALS or can be used "
        "directly for qualitative identification."
    ),
    "model.efa": (
        "Evolving Factor Analysis (EFA) tracks the appearance and disappearance "
        "of chemical species across an ordered sequence (time, temperature, etc.)."
    ),
    "model.hca": (
        "Hierarchical Cluster Analysis (HCA) groups similar samples into a tree "
        "(dendrogram). Cutting the tree at different heights gives different numbers "
        "of clusters. Useful for discovering natural groupings in your data."
    ),
    "model.pls_predict": (
        "Apply the trained PLS model to predict target values for new spectra. "
        "The prediction uses the same preprocessing and number of components as training."
    ),
    "classification.plsda": (
        "PLS Discriminant Analysis (PLS-DA) is the classification version of PLS. "
        "It predicts class membership based on spectral features. VIP scores show "
        "which wavelengths are most important for distinguishing classes."
    ),
    "classification.knn": (
        "K-Nearest Neighbors (KNN) classifies samples by finding the K most similar "
        "samples in the calibration set and using majority voting. Simple but effective "
        "for well-separated classes."
    ),
    "classification.simca": (
        "Soft Independent Modeling of Class Analogy (SIMCA) builds a separate PCA "
        "model for each class. New samples are projected and classified based on "
        "residual distance. Can identify outliers that don't fit any class."
    ),
    "selection.sample_partition": (
        "Splits data into calibration and test sets. Kennard-Stone selects "
        "representative calibration samples by maximizing coverage of the spectral "
        "space. Always validate on an independent test set!"
    ),
    "selection.variable_select": (
        "Variable (wavelength) selection identifies the most informative spectral "
        "regions. This can improve prediction accuracy and model interpretability. "
        "Methods include VIP, interval PLS, and selectivity ratio."
    ),
    "selection.nested_cv": (
        "Nested cross-validation performs variable selection INSIDE each CV fold, "
        "preventing information leakage. This gives an honest, unbiased estimate "
        "of prediction performance — essential for publishable results."
    ),
    "transfer.pds": (
        "Piecewise Direct Standardization (PDS) corrects for differences between "
        "instruments by fitting local regression models in sliding wavelength windows. "
        "Requires paired transfer samples measured on both instruments."
    ),
    "transfer.sbc": (
        "Slope/Bias Correction (SBC) applies a per-wavelength linear correction "
        "to map secondary instrument spectra to the primary instrument's space. "
        "Simpler than PDS but effective for linear intensity/offset differences."
    ),
    "output.plot": (
        "Visualization of the results. In the exported notebook, plots are rendered "
        "using matplotlib. Examine the plots to verify each processing step."
    ),
    "output.export": (
        "Saves the data to a file (CSV, JSON, etc.). The exported file can be "
        "loaded in other software for further analysis."
    ),
    "stats.summary": (
        "Computes descriptive statistics: mean, standard deviation, min, max, median. "
        "A quick sanity check — look for unexpected values that might indicate "
        "data loading or preprocessing issues."
    ),
    "analysis.peak_finding": (
        "Identifies peaks in the spectra using scipy's signal processing. "
        "Parameters like prominence, distance, and height control which peaks "
        "are detected. Consensus peak binning groups peaks found across samples."
    ),
    "diagnostics.outliers": (
        "Detects outliers using Hotelling T² and Q residuals from PCA. "
        "Outliers should be investigated — they may be measurement errors "
        "or genuinely unusual samples."
    ),
    "diagnostics.cross_validation": (
        "Cross-validation estimates how well the model will predict new samples. "
        "RMSECV (Root Mean Square Error of CV) and Q² are key metrics. "
        "RPD > 2.5 and RER > 10 indicate useful predictive models."
    ),
}


def _make_cell(cell_type: str, source_lines: list[str]) -> dict:
    """Build a single notebook cell dict.

    Args:
        cell_type: ``"markdown"`` or ``"code"``.
        source_lines: Lines of text **without** trailing newlines.
            The function adds ``\\n`` to every line except the last,
            matching the Jupyter spec.
    """
    if not source_lines:
        formatted: list[str] = []
    elif len(source_lines) == 1:
        formatted = [source_lines[0]]
    else:
        formatted = [line + "\n" for line in source_lines[:-1]] + [source_lines[-1]]

    cell: dict = {
        "cell_type": cell_type,
        "metadata": {},
        "source": formatted,
    }
    if cell_type == "code":
        cell["execution_count"] = None
        cell["outputs"] = []
    return cell


def _split_python_code(code: str) -> dict[str, list[str]]:
    """Split generated Python code into named sections.

    Returns a dict with keys ``docstring``, ``imports``, ``function``,
    ``main``, each containing a list of lines (without newlines).
    """
    lines = code.split("\n")

    docstring: list[str] = []
    imports: list[str] = []
    function: list[str] = []
    main: list[str] = []

    # State machine to walk through the sections
    section = "start"
    docstring_open = False

    for line in lines:
        if section == "start":
            if line.strip() == '"""' and not docstring_open:
                docstring_open = True
                docstring.append(line)
                continue
            if docstring_open:
                docstring.append(line)
                if line.strip() == '"""' and len(docstring) > 1:
                    docstring_open = False
                    section = "imports"
                continue
            # No docstring — jump to imports
            if line.startswith("import ") or line.startswith("from "):
                section = "imports"
                imports.append(line)
                continue

        elif section == "imports":
            if line.startswith("import ") or line.startswith("from "):
                imports.append(line)
            elif line.strip() == "":
                imports.append(line)
            elif line.startswith("def "):
                section = "function"
                function.append(line)
            else:
                imports.append(line)

        elif section == "function":
            if line.startswith("if __name__"):
                section = "main"
                main.append(line)
            else:
                function.append(line)

        elif section == "main":
            main.append(line)

    # Strip trailing empty lines from each section
    for section_lines in (docstring, imports, function, main):
        while section_lines and section_lines[-1].strip() == "":
            section_lines.pop()

    return {
        "docstring": docstring,
        "imports": imports,
        "function": function,
        "main": main,
    }


def _docstring_to_markdown(docstring_lines: list[str]) -> list[str]:
    """Convert Python docstring lines into markdown cell content."""
    inner = [line for line in docstring_lines if line.strip() != '"""']
    if not inner:
        return ["# Workflow"]

    md: list[str] = []
    first = inner[0].strip()
    if first.startswith("Generated workflow: "):
        name = first.replace("Generated workflow: ", "")
        md.append(f"# {name}")
    else:
        md.append(f"# {first}")

    for line in inner[1:]:
        stripped = line.strip()
        if stripped.startswith("Integrity Hash:"):
            md.append("")
            md.append(f"**{stripped}**")
        elif stripped:
            md.append(stripped)
        else:
            md.append("")

    return md


def _node_description(node_type: str) -> str:
    """Get a beginner-friendly description for a node type."""
    return _NODE_GUIDES.get(node_type, f"Processing step: {node_type}")


def _is_inspection_worthy(node_type: str) -> bool:
    """Return True if this node type merits an inspection cell after it."""
    return any(
        node_type.startswith(prefix)
        for prefix in (
            "data.",
            "preprocess.",
            "baseline.",
            "model.",
            "classification.",
            "selection.",
            "transfer.",
        )
    )


def _extract_node_id_from_marker(stripped: str) -> str | None:
    """Extract node_id from a ``# --- Label (node_id) ---`` comment."""
    if "(" in stripped and ")" in stripped:
        start = stripped.index("(") + 1
        end = stripped.index(")")
        return stripped[start:end].strip()
    if "Source:" in stripped:
        parts = stripped.split("Source:")
        if len(parts) > 1:
            return parts[1].strip().split()[0].strip()
    return None


def _extract_node_blocks(
    func_lines: list[str],
    has_step_wrappers: bool,
) -> tuple[list[tuple[str, list[str]]], int]:
    """Split ``run_workflow()`` body into per-node ``(node_id, lines)`` blocks.

    Handles two formats:

    * **Wrapped** (new): each node lives inside ``def _step_X(): ...``
      — split on ``def _step_`` boundaries, de-indent 8 spaces.
    * **Legacy**: nodes delimited by ``# --- `` comment markers
      — split on markers, de-indent 4 spaces.

    Returns ``(blocks, deindent_spaces)``.
    """
    # --- collect body lines, skipping run_workflow boilerplate ----
    body_lines: list[str] = []
    past_header = False

    if has_step_wrappers:
        trigger = "def _step_"
    else:
        trigger = None  # fall through to legacy markers

    for line in func_lines:
        stripped = line.strip()
        if not past_header:
            if trigger and stripped.startswith(trigger):
                past_header = True
                body_lines.append(line)
            elif not trigger and (stripped.startswith("# --- ") or stripped.startswith("# ╔")):
                past_header = True
                body_lines.append(line)
            continue
        body_lines.append(line)

    # Remove trailing "return results" / blanks
    while body_lines and body_lines[-1].strip() in ("return results", ""):
        body_lines.pop()

    # --- split into blocks ----------------------------------------
    node_blocks: list[tuple[str, list[str]]] = []
    current_block: list[str] = []
    current_node_id: str | None = None

    if has_step_wrappers:
        # Split on ``def _step_`` boundaries
        for line in body_lines:
            stripped = line.strip()
            if stripped.startswith("def _step_"):
                if current_block:
                    node_blocks.append((current_node_id or "unknown", current_block))
                current_block = [line]
                current_node_id = None
            else:
                if current_node_id is None and (stripped.startswith("# --- ") or stripped.startswith("# ╔")):
                    current_node_id = _extract_node_id_from_marker(stripped)
                current_block.append(line)
    else:
        # Legacy: split on ``# --- `` or ``# ╔`` markers
        for line in body_lines:
            stripped = line.strip()
            if stripped.startswith("# --- ") or stripped.startswith("# ╔"):
                if current_block:
                    node_blocks.append((current_node_id or "unknown", current_block))
                current_block = [line]
                current_node_id = _extract_node_id_from_marker(stripped)
            else:
                current_block.append(line)

    if current_block:
        node_blocks.append((current_node_id or "unknown", current_block))

    deindent = 8 if has_step_wrappers else 4
    return node_blocks, deindent


def _deindent_block(
    block_lines: list[str],
    n_spaces: int,
    *,
    strip_wrappers: bool = False,
) -> list[str]:
    """De-indent *block_lines* by *n_spaces* spaces.

    When *strip_wrappers* is True, ``def _step_…():`` and ``_step_…()``
    call lines are dropped so notebook cells contain only the node logic.
    """
    prefix = " " * n_spaces
    out: list[str] = []
    for line in block_lines:
        stripped = line.strip()
        if strip_wrappers:
            if stripped.startswith("def _step_") and stripped.endswith(":"):
                continue
            if stripped.startswith("_step_") and stripped.endswith("()"):
                continue
        if line.startswith(prefix):
            out.append(line[n_spaces:])
        elif line.startswith("    "):
            out.append(line[4:])
        else:
            out.append(line)
    return out


def generate_notebook(workflow: Workflow) -> dict:
    """Generate a Jupyter notebook dict from a workflow.

    Produces a per-node cell notebook with:
    - A Getting Started markdown cell
    - Import code cell
    - Per-node: markdown explanation + code cell + optional inspection cell
    - Final execution + artifact export cell

    Args:
        workflow: Workflow model with nodes and edges.

    Returns:
        A dict representing a valid ``.ipynb`` file (nbformat 4).

    Raises:
        ValueError: If the workflow contains unsupported nodes
            (propagated from ``generate_python_code``).
    """
    # Generate the full Python code (validates and creates the script)
    python_code = generate_python_code(workflow)
    sections = _split_python_code(python_code)

    # --- Also get the per-node structure from the workflow ---
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
    execution_order = topological_sort(node_ids, edges)

    node_type_map = {n.node_id: n.node_type for n in workflow.nodes}
    node_label_map = {}
    for wf_node in workflow.nodes:
        try:
            meta = node_registry.get_metadata(wf_node.node_type)
            node_label_map[wf_node.node_id] = meta.label if meta else wf_node.node_type
        except (KeyError, AttributeError):
            node_label_map[wf_node.node_id] = wf_node.node_type

    cells: list[dict] = []

    # ── Cell 1: Title ──
    if sections["docstring"]:
        md_lines = _docstring_to_markdown(sections["docstring"])
    else:
        md_lines = [f"# {workflow.name}"]
    cells.append(_make_cell("markdown", md_lines))

    # ── Cell 2: Getting Started guide ──
    getting_started = [
        "## Getting Started",
        "",
        "This notebook was exported from **Spectra Sherpa** and contains your "
        "complete chemometric workflow as executable code.",
        "",
        "### Prerequisites",
        "```",
        "pip install spectra-sherpa numpy scipy scikit-learn matplotlib",
        "```",
        "",
        "### Data",
        "Place your spectral data files in a `data/` folder next to this notebook. "
        "The first code cell sets up the `DATA_DIR` variable pointing to this folder.",
        "",
        "### How to use",
        "1. Run cells in order (Shift+Enter)",
        "2. Each step has an explanation above it",
        "3. Inspect intermediate results to verify each step",
        "4. The final cell exports all artifacts to a zip file",
        "",
        f"**Workflow steps:** {len(execution_order)} nodes in this pipeline.",
    ]
    cells.append(_make_cell("markdown", getting_started))

    # ── Cell 3: Imports + setup ──
    if sections["imports"]:
        cells.append(_make_cell("code", sections["imports"]))

    # ── Cell 4: Results dict + DATA_DIR ──
    cells.append(
        _make_cell(
            "code",
            [
                "# Store intermediate results across cells",
                "results = {}",
            ],
        )
    )

    node_map = {
        wf_node.node_id: node_registry.create_node(wf_node.node_type, wf_node.node_id, wf_node.parameters)
        for wf_node in workflow.nodes
    }
    nodes_with_incoming = {e.to_node for e in edges}
    dict_output_nodes = frozenset(
        nid for nid, node in node_map.items() if nid in nodes_with_incoming and node.exported_output_ports() is not None
    )

    # ── Per-node cells ──
    for block_idx, nid in enumerate(execution_order):
        node_type = node_type_map.get(nid, "")
        label = node_label_map.get(nid, node_type or f"Step {block_idx + 1}")
        step_num = block_idx + 1

        # Markdown explanation
        description = _node_description(node_type)
        md = [
            f"## Step {step_num}: {label}",
            "",
            description,
        ]
        cells.append(_make_cell("markdown", md))

        # Code cell — generate directly from the DAG so notebook structure
        # does not depend on comment-marker formatting in Python export.
        node = node_map[nid]
        block_lines = _generate_node_python_lines(
            nid,
            node,
            edges,
            dict_output_nodes,
            indent="    ",
            use_scp=HAS_SCP,
        )
        code_lines = _deindent_block(block_lines, 4)
        # Strip trailing blank lines
        while code_lines and code_lines[-1].strip() == "":
            code_lines.pop()
        if code_lines:
            cells.append(_make_cell("code", code_lines))

        # Inspection cell for key node types
        if _is_inspection_worthy(node_type) and nid in node_type_map:
            inspect_lines = [
                f"# Inspect results from: {label}",
            ]
            if node_type.startswith("data."):
                inspect_lines.extend(
                    [
                        f"_r = results.get('{nid}')",
                        "if _r is not None:",
                        "    if isinstance(_r, dict):",
                        "        _d = _r.get('default', _r)",
                        "    else:",
                        "        _d = _r",
                        "    if hasattr(_d, 'data'):",
                        "        print(f'Shape: {np.asarray(_d.data).shape}')",
                        "        print(f'Data range: [{np.min(_d.data):.4f}, {np.max(_d.data):.4f}]')",
                        "        if hasattr(_d, 'target') and _d.target is not None:",
                        "            print(f'Target shape: {np.asarray(_d.target).shape}')",
                    ]
                )
            elif node_type.startswith(("preprocess.", "baseline.")):
                inspect_lines.extend(
                    [
                        f"_r = results.get('{nid}')",
                        "if _r is not None and hasattr(_r, 'data'):",
                        "    _d = np.asarray(_r.data)",
                        "    print(f'Shape: {_d.shape}')",
                        "    print(f'Mean: {np.mean(_d):.4f}, Std: {np.std(_d):.4f}')",
                        "    print(f'Range: [{np.min(_d):.4f}, {np.max(_d):.4f}]')",
                    ]
                )
            elif node_type.startswith("model.") or node_type.startswith("classification."):
                inspect_lines.extend(
                    [
                        f"_r = results.get('{nid}')",
                        "if isinstance(_r, dict):",
                        "    print('Output keys:', list(_r.keys()))",
                        "    for _k, _v in _r.items():",
                        "        if hasattr(_v, 'shape'): print(f'  {_k}: shape={_v.shape}')",
                        "        elif hasattr(_v, 'data'): print(f'  {_k}: SherpaDataset {np.asarray(_v.data).shape}')",
                        "        elif isinstance(_v, (int, float)): print(f'  {_k}: {_v:.4f}')",
                        "        else: print(f'  {_k}: {type(_v).__name__}')",
                    ]
                )
            elif node_type.startswith("selection."):
                inspect_lines.extend(
                    [
                        f"_r = results.get('{nid}')",
                        "if isinstance(_r, dict):",
                        "    print('Output keys:', list(_r.keys()))",
                        "    for _k, _v in _r.items():",
                        "        if isinstance(_v, dict): print(f'  {_k}: {_v}')",
                        "        elif hasattr(_v, 'shape'): print(f'  {_k}: shape={_v.shape}')",
                        "        elif hasattr(_v, 'data'): print(f'  {_k}: SherpaDataset {np.asarray(_v.data).shape}')",
                    ]
                )
            elif node_type.startswith("transfer."):
                inspect_lines.extend(
                    [
                        f"_r = results.get('{nid}')",
                        "if isinstance(_r, dict):",
                        "    print('Output keys:', list(_r.keys()))",
                        "    if 'X_standardized' in _r and hasattr(_r['X_standardized'], 'data'):",
                        "        print(f'Standardized shape: {np.asarray(_r[\"X_standardized\"].data).shape}')",
                        "    if 'transfer_error' in _r:",
                        '        print(f\'Transfer RMSE: {_r["transfer_error"].get("rmse_transfer", "N/A")}\')',
                    ]
                )

            cells.append(_make_cell("code", inspect_lines))

    # ── Export artifacts cell ──
    cells.append(
        _make_cell(
            "markdown",
            [
                "## Export Artifacts",
                "",
                "Save all results to individual files and create a zip archive.",
            ],
        )
    )

    # Build the main/export block
    if sections["main"]:
        main_lines = []
        for line in sections["main"]:
            if line.startswith("if __name__"):
                continue
            if line.startswith("    "):
                main_lines.append(line[4:])
            else:
                main_lines.append(line)

        # Remove "results = run_workflow()" and export calls since the notebook
        # has already executed the steps incrementally and exposes a single
        # dedicated export cell below.
        filtered = []
        for line in main_lines:
            if "run_workflow()" in line:
                continue
            if "export_artifacts(" in line:
                continue
            filtered.append(line)

        # Strip leading/trailing blanks
        while filtered and filtered[0].strip() == "":
            filtered.pop(0)
        while filtered and filtered[-1].strip() == "":
            filtered.pop()

        if filtered:
            cells.append(_make_cell("code", filtered))

    # Also include the export_artifacts function and call
    # Extract it from the generated code
    export_func_lines = []
    in_export_func = False
    for line in python_code.split("\n"):
        if line.startswith("def export_artifacts("):
            in_export_func = True
        if in_export_func:
            if line.startswith("def export_artifacts(") or line.startswith("    "):
                export_func_lines.append(line)
            elif line.strip() == "" and export_func_lines:
                export_func_lines.append(line)
            else:
                if export_func_lines and not line.startswith("def ") and line.strip() == "":
                    continue
                if line.startswith("if __name__") or line.startswith("def "):
                    break

    # Strip trailing blanks
    while export_func_lines and export_func_lines[-1].strip() == "":
        export_func_lines.pop()

    if export_func_lines:
        export_func_lines.append("")
        export_func_lines.append("# Run export")
        export_func_lines.append("export_artifacts(results)")
        cells.append(_make_cell("code", export_func_lines))

    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": NOTEBOOK_METADATA,
        "cells": cells,
    }
