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
    from spectra_sherpa.app.services.workflow_export_context import WorkflowExportContext


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
        "as Plotly figures so you can inspect and zoom them interactively."
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


def generate_notebook(
    workflow: Workflow,
    export_context: "WorkflowExportContext | None" = None,
) -> dict:
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
    python_code = generate_python_code(workflow, export_context=export_context)
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
        "pip install spectra-sherpa numpy scipy scikit-learn plotly",
        "```",
        "",
        "### Data",
        "Place your source files in a `data/` folder next to this notebook, or set "
        "`SHERPA_DATA_DIR` to point somewhere else. The first code cell sets `DATA_DIR`.",
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

    # ── Cell 4: Results dict ──
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

        # Code cell — generate directly from the DAG
        node = node_map[nid]
        block_lines = _generate_node_python_lines(
            nid,
            node,
            edges,
            dict_output_nodes,
            indent="",
            use_scp=HAS_SCP,
            export_context=export_context,
        )
        # Strip trailing blank lines
        while block_lines and block_lines[-1].strip() == "":
            block_lines.pop()
        if block_lines:
            cells.append(_make_cell("code", block_lines))

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

    wf_name_safe = workflow.name.replace(" ", "_").replace("/", "_")
    cells.append(
        _make_cell(
            "code",
            [
                f"export_artifacts(results, {wf_name_safe!r})",
            ],
        )
    )

    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": NOTEBOOK_METADATA,
        "cells": cells,
    }
