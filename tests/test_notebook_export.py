"""
Tests for Jupyter notebook export (notebook_export.py).

Validates that generate_notebook() produces a valid .ipynb structure
by mocking generate_python_code() with a known script string.

Run:
    PYTHONPATH=src/spectra_sherpa python -m pytest tests/test_notebook_export.py -v --no-cov
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest


# Sample Python code matching the output format of generate_python_code()
SAMPLE_PYTHON_CODE = '''\
"""
Generated workflow: Test Workflow

A sample IR preprocessing pipeline.

Integrity Hash: abc123def456
"""

import numpy as np
import spectrochempy as scp
from spectrochempy import NDDataset

def run_workflow():
    """Execute the workflow."""
    print("=" * 60)
    print("Workflow: Test Workflow")
    print("=" * 60)

    # Store intermediate results
    results = {}

    # --- Source: node_1 (LoadFileNode) ---
    # >>> EDIT: provide your data below <<<
    # results['node_1'] = scp.read('your_file.scp')
    # results['node_1'] = scp.load_iris()

    # --- node_2: BaselineCorrection ---
    results['node_2'] = results['node_1'].snip()

    return results


if __name__ == "__main__":
    results = run_workflow()

    print("\\nWorkflow completed successfully!")
    for key, value in results.items():
        print(f"  {key}: {type(value).__name__}")
'''

SAMPLE_PYTHON_CODE_NO_DESC = '''\
"""
Generated workflow: Minimal
"""

import numpy as np
import spectrochempy as scp
from spectrochempy import NDDataset

def run_workflow():
    """Execute the workflow."""
    results = {}
    return results


if __name__ == "__main__":
    results = run_workflow()
'''


def _make_mock_workflow(name: str = "Test Workflow", description: str | None = "A sample IR preprocessing pipeline."):
    return SimpleNamespace(
        name=name,
        description=description,
        integrity_hash="abc123def456",
        nodes=[],
        edges=[],
    )


@pytest.fixture
def mock_generate():
    """Patch generate_python_code to return our sample code."""
    with patch("app.services.notebook_export.generate_python_code") as mock:
        mock.return_value = SAMPLE_PYTHON_CODE
        yield mock


@pytest.fixture
def mock_generate_minimal():
    """Patch generate_python_code to return minimal code (no description)."""
    with patch("app.services.notebook_export.generate_python_code") as mock:
        mock.return_value = SAMPLE_PYTHON_CODE_NO_DESC
        yield mock


class TestGenerateNotebook:
    """Test the generate_notebook() function."""

    def test_returns_valid_nbformat_structure(self, mock_generate):
        from app.services.notebook_export import generate_notebook

        workflow = _make_mock_workflow()
        nb = generate_notebook(workflow)

        assert nb["nbformat"] == 4
        assert nb["nbformat_minor"] == 5
        assert "metadata" in nb
        assert "cells" in nb
        assert isinstance(nb["cells"], list)
        assert len(nb["cells"]) == 4  # markdown + imports + function + main

    def test_metadata_has_kernel_info(self, mock_generate):
        from app.services.notebook_export import generate_notebook

        nb = generate_notebook(_make_mock_workflow())
        meta = nb["metadata"]

        assert "kernelspec" in meta
        assert meta["kernelspec"]["language"] == "python"
        assert meta["kernelspec"]["name"] == "python3"
        assert "language_info" in meta
        assert meta["language_info"]["name"] == "python"

    def test_first_cell_is_markdown_with_title(self, mock_generate):
        from app.services.notebook_export import generate_notebook

        nb = generate_notebook(_make_mock_workflow())
        cell = nb["cells"][0]

        assert cell["cell_type"] == "markdown"
        source_text = "".join(cell["source"])
        assert "# Test Workflow" in source_text

    def test_markdown_cell_includes_description(self, mock_generate):
        from app.services.notebook_export import generate_notebook

        nb = generate_notebook(_make_mock_workflow())
        source_text = "".join(nb["cells"][0]["source"])

        assert "IR preprocessing pipeline" in source_text

    def test_markdown_cell_includes_integrity_hash(self, mock_generate):
        from app.services.notebook_export import generate_notebook

        nb = generate_notebook(_make_mock_workflow())
        source_text = "".join(nb["cells"][0]["source"])

        assert "abc123def456" in source_text

    def test_second_cell_is_code_with_imports(self, mock_generate):
        from app.services.notebook_export import generate_notebook

        nb = generate_notebook(_make_mock_workflow())
        cell = nb["cells"][1]

        assert cell["cell_type"] == "code"
        assert cell["execution_count"] is None
        assert cell["outputs"] == []

        source_text = "".join(cell["source"])
        assert "import numpy as np" in source_text
        assert "import spectrochempy as scp" in source_text

    def test_third_cell_has_workflow_function(self, mock_generate):
        from app.services.notebook_export import generate_notebook

        nb = generate_notebook(_make_mock_workflow())
        cell = nb["cells"][2]

        assert cell["cell_type"] == "code"
        source_text = "".join(cell["source"])
        assert "def run_workflow():" in source_text
        assert "return results" in source_text

    def test_fourth_cell_is_runnable_main_block(self, mock_generate):
        from app.services.notebook_export import generate_notebook

        nb = generate_notebook(_make_mock_workflow())
        cell = nb["cells"][3]

        assert cell["cell_type"] == "code"
        source_text = "".join(cell["source"])
        # Should NOT have `if __name__` — replaced with direct calls
        assert 'if __name__' not in source_text
        # Should have the execution calls (de-indented)
        assert "results = run_workflow()" in source_text

    def test_cell_source_is_list_of_strings(self, mock_generate):
        from app.services.notebook_export import generate_notebook

        nb = generate_notebook(_make_mock_workflow())

        for cell in nb["cells"]:
            assert isinstance(cell["source"], list)
            for line in cell["source"]:
                assert isinstance(line, str)

    def test_cell_source_lines_end_with_newline_except_last(self, mock_generate):
        from app.services.notebook_export import generate_notebook

        nb = generate_notebook(_make_mock_workflow())

        for cell in nb["cells"]:
            source = cell["source"]
            if len(source) > 1:
                for line in source[:-1]:
                    assert line.endswith("\n"), f"Non-last line should end with \\n: {line!r}"

    def test_minimal_workflow_without_description(self, mock_generate_minimal):
        from app.services.notebook_export import generate_notebook

        workflow = _make_mock_workflow(name="Minimal", description=None)
        nb = generate_notebook(workflow)

        assert nb["nbformat"] == 4
        assert len(nb["cells"]) >= 3  # at least markdown + imports + function
        source_text = "".join(nb["cells"][0]["source"])
        assert "# Minimal" in source_text


class TestSplitPythonCode:
    """Test the _split_python_code helper directly."""

    def test_splits_into_four_sections(self):
        from app.services.notebook_export import _split_python_code

        sections = _split_python_code(SAMPLE_PYTHON_CODE)

        assert "docstring" in sections
        assert "imports" in sections
        assert "function" in sections
        assert "main" in sections

    def test_docstring_section_contains_triple_quotes(self):
        from app.services.notebook_export import _split_python_code

        sections = _split_python_code(SAMPLE_PYTHON_CODE)
        text = "\n".join(sections["docstring"])
        assert '"""' in text
        assert "Generated workflow" in text

    def test_imports_section_has_numpy_and_scp(self):
        from app.services.notebook_export import _split_python_code

        sections = _split_python_code(SAMPLE_PYTHON_CODE)
        text = "\n".join(sections["imports"])
        assert "numpy" in text
        assert "spectrochempy" in text

    def test_function_section_has_def_and_return(self):
        from app.services.notebook_export import _split_python_code

        sections = _split_python_code(SAMPLE_PYTHON_CODE)
        text = "\n".join(sections["function"])
        assert "def run_workflow():" in text
        assert "return results" in text

    def test_main_section_has_name_check(self):
        from app.services.notebook_export import _split_python_code

        sections = _split_python_code(SAMPLE_PYTHON_CODE)
        text = "\n".join(sections["main"])
        assert '__name__' in text


class TestDocstringToMarkdown:
    """Test the _docstring_to_markdown helper."""

    def test_converts_generated_workflow_to_heading(self):
        from app.services.notebook_export import _docstring_to_markdown

        lines = ['"""', 'Generated workflow: My Pipeline', '"""']
        md = _docstring_to_markdown(lines)

        assert md[0] == "# My Pipeline"

    def test_preserves_description(self):
        from app.services.notebook_export import _docstring_to_markdown

        lines = ['"""', 'Generated workflow: Test', '', 'Description text here', '"""']
        md = _docstring_to_markdown(lines)

        assert "# Test" in md[0]
        assert "Description text here" in md

    def test_formats_integrity_hash_as_bold(self):
        from app.services.notebook_export import _docstring_to_markdown

        lines = ['"""', 'Generated workflow: Test', '', 'Integrity Hash: abc123', '"""']
        md = _docstring_to_markdown(lines)

        assert any("**Integrity Hash:" in line for line in md)

    def test_empty_docstring_returns_default(self):
        from app.services.notebook_export import _docstring_to_markdown

        md = _docstring_to_markdown(['"""', '"""'])
        assert md == ["# Workflow"]
