"""Canonical notebook export qualification."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from spectra_sherpa.app.services.notebook_export import generate_notebook
from spectra_sherpa.app.services.prepared_data import PreparedDataOverrides
from spectra_sherpa.app.services.workflow_export_context import (
    BundledSourceFile,
    SourceExportSpec,
    WorkflowExportContext,
)

_SOURCE_TEXT = "target,1000,1001\n1,1,2\n2,2,4\n"
_SOURCE_SHA256 = hashlib.sha256(_SOURCE_TEXT.encode("utf-8")).hexdigest()


def _workflow() -> SimpleNamespace:
    return SimpleNamespace(
        name='Canonical "Notebook"',
        description='A description containing """ cannot alter Python.',
        integrity_hash="notebook-integrity",
        nodes=[
            SimpleNamespace(
                node_id="source",
                node_type="data.file_load",
                parameters={
                    "experiment_id": 1,
                    "file_id": 2,
                    "stage": "raw",
                    "target_authority": {
                        "schema_version": "spectrasherpa-target-authority/1",
                        "column": "target",
                        "target_type": "continuous",
                        "units": None,
                        "source_digest": _SOURCE_SHA256,
                    },
                },
            ),
            SimpleNamespace(
                node_id="normalize",
                node_type="preprocess.normalize",
                parameters={"method": "snv"},
            ),
        ],
        edges=[
            SimpleNamespace(
                from_node_id="source",
                to_node_id="normalize",
                from_output="default",
                to_input="default",
            )
        ],
    )


def _context(tmp_path: Path) -> WorkflowExportContext:
    source = tmp_path / "source.csv"
    source.write_bytes(_SOURCE_TEXT.encode("utf-8"))
    return WorkflowExportContext(
        source_specs={
            "source": SourceExportSpec(
                node_id="source",
                source="experiment",
                loader_mode="single_file",
                overrides=PreparedDataOverrides(
                    target_column="target",
                    selected_target="target",
                    target_type="continuous",
                    target_mode="single",
                ),
                bundle_files=(
                    BundledSourceFile(
                        absolute_path=source,
                        source_relative_path="source.csv",
                        bundle_relative_path="source/source.csv",
                    ),
                ),
            )
        }
    )


def _cell_source(cell: dict) -> str:
    return "".join(cell["source"])


def test_notebook_is_valid_and_binds_one_canonical_execution(tmp_path: Path) -> None:
    notebook = generate_notebook(_workflow(), export_context=_context(tmp_path))

    assert set(notebook) == {"nbformat", "nbformat_minor", "metadata", "cells"}
    assert notebook["nbformat"] == 4
    assert notebook["nbformat_minor"] == 5
    assert isinstance(notebook["metadata"], dict)
    assert isinstance(notebook["cells"], list)
    for cell in notebook["cells"]:
        assert cell["cell_type"] in {"code", "markdown"}
        assert isinstance(cell["source"], list)
        if cell["cell_type"] == "code":
            ast.parse(_cell_source(cell))
    source = "\n".join(_cell_source(cell) for cell in notebook["cells"])
    assert "WORKFLOW_MANIFEST" in source
    assert "WorkflowSpec.from_dict" in source
    assert source.count("ss.runtime.execute_workflow(") == 1
    assert "node.generate_python" not in source
    assert "using standalone export" not in source
    assert "sklearn." not in source


def test_notebook_definitions_are_valid_python_and_do_not_auto_execute(tmp_path: Path) -> None:
    notebook = generate_notebook(_workflow(), export_context=_context(tmp_path))
    definition = next(
        _cell_source(cell)
        for cell in notebook["cells"]
        if cell["cell_type"] == "code" and "WORKFLOW_MANIFEST" in _cell_source(cell)
    )

    ast.parse(definition)
    assert "if __name__" not in definition
    assert "results = run_workflow()" not in definition


def test_notebook_keeps_explanation_and_inspection_separate_from_science(tmp_path: Path) -> None:
    notebook = generate_notebook(_workflow(), export_context=_context(tmp_path))
    markdown = [_cell_source(cell) for cell in notebook["cells"] if cell["cell_type"] == "markdown"]
    code = [_cell_source(cell) for cell in notebook["cells"] if cell["cell_type"] == "code"]

    assert any("Canonical operation: `deploy.input`" in value for value in markdown)
    assert not any("Canonical operation: `data.file_load`" in value for value in markdown)
    assert any("Canonical operation: `preprocess.normalize`" in value for value in markdown)
    assert any("Inspect the canonical result" in value for value in code)
    assert sum("execute_workflow()" in value for value in code) == 1
    assert any("Diagnostics:" in value for value in code)


def test_notebook_cells_use_jupyter_source_line_shape(tmp_path: Path) -> None:
    notebook = generate_notebook(_workflow(), export_context=_context(tmp_path))
    for cell in notebook["cells"]:
        assert isinstance(cell["source"], list)
        assert all(isinstance(line, str) for line in cell["source"])
        if cell["source"]:
            assert all(line.endswith("\n") for line in cell["source"][:-1])
            assert not cell["source"][-1].endswith("\n")
        if cell["cell_type"] == "code":
            assert cell["execution_count"] is None
            assert cell["outputs"] == []


def test_notebook_refuses_bundled_bytes_that_changed_after_target_selection(tmp_path: Path) -> None:
    context = _context(tmp_path)
    generate_notebook(_workflow(), export_context=context)
    context.source_specs["source"].bundle_files[0].absolute_path.write_text(
        "target,1000,1001\n1,9,9\n2,8,8\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="target authority differs from its source"):
        generate_notebook(_workflow(), export_context=context)
