"""
Jupyter notebook generator for workflows.

Wraps the output of ``python_export.generate_python_code()`` into a
standard ``.ipynb`` (nbformat 4) JSON structure, splitting the script
into logical cells: title/description (markdown), imports, workflow
function body, and main execution block.

No external dependencies — ``.ipynb`` is just JSON.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spectra_sherpa.app.services.python_export import generate_python_code

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
                # Blank line — could be separator or end of imports
                # Peek ahead logic: if next substantive line is still an import, continue
                imports.append(line)
            elif line.startswith("def "):
                section = "function"
                function.append(line)
            else:
                # Transition: not an import, not blank, not def — accumulate in imports
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
    """Convert Python docstring lines into markdown cell content.

    Strips the ``\"\"\"`` delimiters and converts the first line into a
    markdown heading.
    """
    # Remove triple-quote delimiters
    inner = [line for line in docstring_lines if line.strip() != '"""']
    if not inner:
        return ["# Workflow"]

    md: list[str] = []
    # First line becomes heading
    first = inner[0].strip()
    if first.startswith("Generated workflow: "):
        name = first.replace("Generated workflow: ", "")
        md.append(f"# {name}")
    else:
        md.append(f"# {first}")

    # Remaining lines become body text
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


def generate_notebook(workflow: Workflow) -> dict:
    """Generate a Jupyter notebook dict from a workflow.

    Calls ``generate_python_code()`` to get the full Python script,
    then splits it into logical cells for an interactive notebook
    experience.

    Args:
        workflow: Workflow model with nodes and edges.

    Returns:
        A dict representing a valid ``.ipynb`` file (nbformat 4).

    Raises:
        ValueError: If the workflow contains unsupported nodes
            (propagated from ``generate_python_code``).
    """
    python_code = generate_python_code(workflow)
    sections = _split_python_code(python_code)

    cells: list[dict] = []

    # Cell 1: Markdown title + description
    if sections["docstring"]:
        md_lines = _docstring_to_markdown(sections["docstring"])
        cells.append(_make_cell("markdown", md_lines))
    else:
        cells.append(_make_cell("markdown", [f"# {workflow.name}"]))

    # Cell 2: Imports
    if sections["imports"]:
        cells.append(_make_cell("code", sections["imports"]))

    # Cell 3: Workflow function body
    if sections["function"]:
        cells.append(_make_cell("code", sections["function"]))

    # Cell 4: Main execution block
    if sections["main"]:
        # Replace `if __name__ == "__main__":` with direct calls
        # so the cell is immediately runnable in a notebook
        main_lines = []
        for line in sections["main"]:
            if line.startswith("if __name__"):
                main_lines.append("# Run the workflow")
            else:
                # Remove one level of indentation (4 spaces)
                if line.startswith("    "):
                    main_lines.append(line[4:])
                else:
                    main_lines.append(line)
        cells.append(_make_cell("code", main_lines))

    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": NOTEBOOK_METADATA,
        "cells": cells,
    }
