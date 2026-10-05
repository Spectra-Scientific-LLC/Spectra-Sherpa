"""Render a scientist-readable notebook around one canonical DAG execution.

Notebook cells explain and inspect the workflow; they never reimplement one
node at a time. The only computation cell calls the same digest-bound SDK
runtime used by the Python export and Workbench executor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.python_export import generate_notebook_module_code

if TYPE_CHECKING:
    from spectra_sherpa.app.models.workflow import Workflow
    from spectra_sherpa.app.services.workflow_export_context import WorkflowExportContext


NOTEBOOK_METADATA: dict[str, Any] = {
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


def _make_cell(cell_type: str, source_lines: list[str]) -> dict[str, Any]:
    if not source_lines:
        source: list[str] = []
    elif len(source_lines) == 1:
        source = [source_lines[0]]
    else:
        source = [line + "\n" for line in source_lines[:-1]] + [source_lines[-1]]
    cell: dict[str, Any] = {"cell_type": cell_type, "metadata": {}, "source": source}
    if cell_type == "code":
        cell.update({"execution_count": None, "outputs": []})
    return cell


def _inspection_lines(node_id: str, label: str) -> list[str]:
    return [
        f"# Inspect the canonical result from {label}",
        f"_value = results.get({node_id!r})",
        f"_diagnostics = diagnostics.get({node_id!r}, {{}})",
        "if isinstance(_value, dict):",
        "    print('Output ports:')",
        "    for _port, _item in _value.items():",
        "        if hasattr(_item, 'data'):",
        "            print(f'  {_port}: SherpaDataset {getattr(_item, \"shape\", None)}')",
        "        elif hasattr(_item, 'shape'):",
        "            print(f'  {_port}: {type(_item).__name__} {_item.shape}')",
        "        elif isinstance(_item, (str, int, float, bool)) or _item is None:",
        "            print(f'  {_port}: {_item!r}')",
        "        else:",
        "            print(f'  {_port}: {type(_item).__name__}')",
        "elif hasattr(_value, 'shape'):",
        "    print(f'Result: {type(_value).__name__} {_value.shape}')",
        "else:",
        "    print(f'Result: {type(_value).__name__}')",
        "print('Diagnostics:', dict(_diagnostics) if _diagnostics else 'none reported')",
    ]


def generate_notebook(
    workflow: Workflow,
    export_context: WorkflowExportContext | None = None,
) -> dict[str, Any]:
    """Generate the one current notebook representation of a workflow."""

    export, module_code = generate_notebook_module_code(workflow, export_context=export_context)
    cells: list[dict[str, Any]] = []

    title = [
        f"# {workflow.name}",
        "",
        "This notebook executes the exact typed DAG through the canonical Spectra Sherpa runtime.",
        "Its cells inspect results; they do not contain alternate scientific formulas.",
        "",
        f"**Workflow digest:** `{export.workflow.workflow_digest}`",
    ]
    description = str(getattr(workflow, "description", "") or "").strip()
    if description:
        title.extend(["", description])
    cells.append(_make_cell("markdown", title))

    cells.append(
        _make_cell(
            "markdown",
            [
                "## Getting started",
                "",
                "1. Install the current `spectra-sherpa` package.",
                "2. Keep the exported `data/` directory beside this notebook, or set `SHERPA_DATA_DIR`.",
                *(
                    [
                        (
                            "3. For a registered third-party reference, obtain it from its provider, "
                            "extract the required member, and set `SPECTRA_REFERENCE_DIR` to that file "
                            "or its containing directory."
                        ),
                        (
                            "4. Sherpa accepts only the exact recorded member size and SHA-256; "
                            "moving or renaming that member is safe."
                        ),
                        "5. Run the definition cell and then the single DAG execution cell.",
                        "6. Use the following cells to inspect each named result and diagnostic record.",
                    ]
                    if any(binding.external_reference is not None for binding in export.bundled_sources)
                    else [
                        "3. Run the definition cell and then the single DAG execution cell.",
                        "4. Use the following cells to inspect each named result and diagnostic record.",
                    ]
                ),
                "",
                f"This workflow contains **{len(export.execution_order)} canonical operations**.",
            ],
        )
    )
    cells.append(_make_cell("code", module_code.splitlines()))

    execution_lines = [
        "# Execute the complete DAG once through the canonical runtime",
        "if EXTERNAL_STREAMS:",
        "    raise ValueError(",
        "        'Provide deployment_inputs to execute_workflow(...) for streams ' + repr(EXTERNAL_STREAMS)",
        "    )",
        "execution = execute_workflow()",
        "results = dict(execution.results)",
        "diagnostics = {node_id: dict(value) for node_id, value in execution.diagnostics.items()}",
        "print(f'Completed {len(results)} canonical node results.')",
    ]
    cells.append(_make_cell("markdown", ["## Execute the canonical workflow"]))
    cells.append(_make_cell("code", execution_lines))

    node_parameters = {str(node["node_id"]): dict(node["parameters"]) for node in export.workflow.payload["nodes"]}
    for step, node_id in enumerate(export.execution_order, start=1):
        node_type = export.node_types[node_id]
        label = export.node_labels[node_id]
        metadata = node_registry.get_metadata(node_type)
        markdown = [
            f"## Step {step}: {label}",
            "",
            f"Canonical operation: `{node_type}` · node ID: `{node_id}`",
            "",
            metadata.description,
        ]
        parameters = node_parameters.get(node_id, {})
        if parameters:
            markdown.extend(["", f"Declared parameters: `{parameters!r}`"])
        cells.append(_make_cell("markdown", markdown))
        cells.append(_make_cell("code", _inspection_lines(node_id, label)))

    safe_name = str(workflow.name).replace(" ", "_").replace("/", "_")
    cells.append(
        _make_cell(
            "markdown",
            [
                "## Export artifacts",
                "",
                "Save the already-computed canonical results without rerunning scientific operations.",
            ],
        )
    )
    cells.append(_make_cell("code", [f"export_artifacts(results, {safe_name!r})"]))

    for index, cell in enumerate(cells):
        cell["id"] = f"canonical-cell-{index:03d}"

    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": NOTEBOOK_METADATA,
        "cells": cells,
    }


__all__ = ["NOTEBOOK_METADATA", "generate_notebook"]
