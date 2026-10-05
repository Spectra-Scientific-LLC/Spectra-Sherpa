"""Adversarial checks for the single canonical executable exporter."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.prepared_data import PreparedDataOverrides
from spectra_sherpa.app.services.python_export import generate_python_code
from spectra_sherpa.app.services.workflow_export_context import (
    BundledSourceFile,
    SourceExportSpec,
    WorkflowExportContext,
)


def _deployment_workflow(*, node_id: str = "input") -> SimpleNamespace:
    return SimpleNamespace(
        name='Workflow "quoted"\nname',
        description='Description with """ and\nif False: pass',
        integrity_hash="deployment-export",
        nodes=[
            SimpleNamespace(
                node_id=node_id,
                node_type="deploy.input",
                parameters={
                    "stream_name": "sample",
                    "schema_version": "spectrasherpa.deploy-input/1",
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
                from_node_id=node_id,
                to_node_id="normalize",
                from_output="default",
                to_input="default",
            )
        ],
    )


def test_exported_program_contains_data_not_generated_scientific_formulas() -> None:
    code = generate_python_code(_deployment_workflow())

    ast.parse(code)
    assert "WORKFLOW_MANIFEST" in code
    assert "preprocess.normalize" in code
    assert code.count("ss.runtime.execute_workflow(") == 1
    assert "np.mean" not in code
    assert "StandardScaler" not in code
    assert "PLSRegression" not in code
    assert "using standalone export" not in code


def test_untrusted_workflow_text_cannot_change_generated_program() -> None:
    code = generate_python_code(_deployment_workflow())
    module = ast.parse(code)

    assert ast.get_docstring(module) is not None
    assert 'Description with """' in ast.get_docstring(module)
    assert sum(isinstance(node, ast.If) for node in module.body) == 1  # only __main__


def test_external_deployment_input_runs_the_same_canonical_operation() -> None:
    code = generate_python_code(_deployment_workflow())
    namespace = {"__name__": "export_test"}
    exec(compile(code, "<deployment-export>", "exec"), namespace)
    dataset = SherpaDataset(np.array([[1.0, 2.0, 3.0], [2.0, 4.0, 8.0]]))

    results = namespace["run_workflow"]({"sample": dataset})
    expected = np.array(
        [[-1.224744871391589, 0.0, 1.224744871391589], [-1.0690449676496976, -0.2672612419124244, 1.3363062095621219]]
    )
    np.testing.assert_allclose(results["normalize"]["default"].data, expected, rtol=0, atol=1e-12)


def test_external_input_set_and_bundled_input_override_fail_closed(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source.csv"
    source.write_text("target,1000,1001\n1,1,2\n2,2,4\n", encoding="utf-8")
    workflow = SimpleNamespace(
        name="Bundled",
        description="",
        integrity_hash="bundled",
        nodes=[
            SimpleNamespace(
                node_id="source",
                node_type="data.file_load",
                parameters={"experiment_id": 1, "file_id": 2, "stage": "raw"},
            )
        ],
        edges=[],
    )
    context = WorkflowExportContext(
        source_specs={
            "source": SourceExportSpec(
                node_id="source",
                source="experiment",
                loader_mode="single_file",
                overrides=PreparedDataOverrides(),
                bundle_files=(
                    BundledSourceFile(
                        absolute_path=source,
                        source_relative_path=source.name,
                        bundle_relative_path="source/source.csv",
                    ),
                ),
            )
        }
    )
    code = generate_python_code(workflow, export_context=context)
    bundle = tmp_path / "source" / "source.csv"
    bundle.parent.mkdir()
    bundle.write_bytes(source.read_bytes())
    monkeypatch.setenv("SHERPA_DATA_DIR", str(tmp_path))
    namespace = {"__name__": "export_test", "__file__": str(tmp_path / "run.py")}
    exec(compile(code, "<bundled-export>", "exec"), namespace)

    with pytest.raises(ValueError, match="cannot replace bundled source streams"):
        namespace["run_workflow"]({"export.source.source": SherpaDataset(np.ones((2, 2)))})


def test_portable_node_id_punctuation_does_not_inject_python() -> None:
    code = generate_python_code(_deployment_workflow(node_id="source-a.b"))
    ast.parse(code)
    assert "source-a.b" in code


def test_export_artifacts_handles_string_targets_and_arrays(tmp_path: Path, monkeypatch) -> None:
    from spectra_sherpa.app.services.export_utils import export_artifacts

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SPECTRA_SHERPA_EXPORT_DIR", str(tmp_path))
    results = {
        "spectra": SherpaDataset(
            np.arange(6).reshape(3, 2),
            target=np.array(["class_a", "class_b", "class_c"], dtype=object),
        ),
        "labels": np.array(["alpha", "beta"], dtype=object),
        "metrics": {"classes": np.array(["yes", "no"], dtype=object), "note": "ok"},
    }

    zip_name = export_artifacts(results, workflow_name="robust")
    out_dir = tmp_path / Path(zip_name).stem
    assert (tmp_path / zip_name).exists()
    assert "class_a" in (out_dir / "spectra_target.csv").read_text(encoding="utf-8")
    assert "alpha" in (out_dir / "labels.csv").read_text(encoding="utf-8")
    assert (out_dir / "metrics_summary.json").exists()
