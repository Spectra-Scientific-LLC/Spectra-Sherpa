from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.nodes.output import ExportNode
from spectra_sherpa.app.services.python_export import generate_python_code


def _workflow(name: str = "Robust Export") -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description="",
        nodes=[],
        edges=[],
        integrity_hash="export_robustness",
    )


def _preprocess_workflow() -> SimpleNamespace:
    return SimpleNamespace(
        name="SDK Export",
        description="",
        nodes=[
            SimpleNamespace(
                node_id="src_1",
                node_type="data.source",
                parameters={"source": "sklearn", "sklearn_dataset": "iris"},
            ),
            SimpleNamespace(
                node_id="snv_1",
                node_type="preprocess.normalize",
                parameters={"method": "snv"},
            ),
        ],
        edges=[
            SimpleNamespace(from_node_id="src_1", to_node_id="snv_1", from_output="default", to_input="default"),
        ],
        integrity_hash="sdk_export",
    )


def test_python_export_defaults_to_sdk_mode_for_supported_wrappers() -> None:
    code = generate_python_code(_preprocess_workflow())

    ast.parse(code)
    assert "Export mode: sdk" in code
    assert "import spectra_sherpa.sdk as ss" in code
    assert "results['snv_1'] = ss.preprocess.snv(results['src_1'])" in code
    assert "using standalone export" in code


def test_python_export_sdk_mode_maps_model_nodes_to_sdk_wrappers() -> None:
    wf = SimpleNamespace(
        name="SDK Model Export",
        description="",
        nodes=[
            SimpleNamespace(
                node_id="src_1",
                node_type="data.source",
                parameters={"source": "sklearn", "sklearn_dataset": "iris"},
            ),
            SimpleNamespace(
                node_id="pca_1",
                node_type="model.pca",
                parameters={"n_components": 3, "scaled": True},
            ),
            SimpleNamespace(
                node_id="pls_1",
                node_type="model.pls",
                parameters={"n_components": 2, "cv_method": "none"},
            ),
        ],
        edges=[
            SimpleNamespace(from_node_id="src_1", to_node_id="pca_1", from_output="default", to_input="default"),
            SimpleNamespace(from_node_id="src_1", to_node_id="pls_1", from_output="default", to_input="X"),
        ],
        integrity_hash="sdk_model_export",
    )

    code = generate_python_code(wf)

    ast.parse(code)
    assert "results['pca_1'] = ss.explore.pca(results['src_1'], n_components=3, scaled=True)" in code
    assert "results['pls_1'] = ss.regression.pls(results['src_1'], n_components=2, cv_method='none')" in code


def test_python_export_sdk_mode_uses_sdk_read_csv_for_bundled_sources() -> None:
    class FakeOverrides:
        def is_empty(self) -> bool:
            return True

    source_spec = SimpleNamespace(
        loader_mode="single_file",
        bundle_files=[SimpleNamespace(bundle_relative_path="data/spectra.csv")],
        overrides=FakeOverrides(),
    )
    export_context = SimpleNamespace(
        data_env_var="SHERPA_DATA_DIR",
        source_spec_for=lambda node_id: source_spec if node_id == "src_1" else None,
    )
    wf = SimpleNamespace(
        name="SDK CSV Export",
        description="",
        nodes=[SimpleNamespace(node_id="src_1", node_type="data.source", parameters={})],
        edges=[],
        integrity_hash="sdk_csv_export",
    )

    code = generate_python_code(wf, export_context=export_context)

    ast.parse(code)
    assert "_ds = ss.data.read_csv(_bundle_path_src_1)" in code
    assert "results['src_1'] = _ds" in code


def test_python_export_standalone_mode_preserves_node_export_path() -> None:
    code = generate_python_code(_preprocess_workflow(), mode="standalone")

    ast.parse(code)
    assert "Export mode: sdk" not in code
    assert "import spectra_sherpa.sdk as ss" not in code
    assert "ss.preprocess.snv" not in code


def test_python_export_strict_sdk_rejects_unmapped_nodes() -> None:
    wf = SimpleNamespace(
        name="Unsupported SDK Export",
        description="",
        nodes=[
            SimpleNamespace(node_id="src_1", node_type="data.source", parameters={}),
            SimpleNamespace(node_id="pca_1", node_type="model.pca", parameters={"n_components": 2}),
        ],
        edges=[
            SimpleNamespace(from_node_id="src_1", to_node_id="pca_1", from_output="default", to_input="default"),
        ],
        integrity_hash="strict_sdk_export",
    )

    with pytest.raises(ValueError, match="has no SDK export wrapper"):
        generate_python_code(wf, strict_sdk=True)


def test_export_artifacts_handles_string_targets_and_arrays(tmp_path, monkeypatch) -> None:
    code = generate_python_code(_workflow())
    namespace: dict = {}
    exec(code, namespace)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SPECTRA_SHERPA_EXPORT_DIR", str(tmp_path))
    results = {
        "spectra": SherpaDataset(
            np.arange(6).reshape(3, 2),
            target=np.array(["class_a", "class_b", "class_c"], dtype=object),
        ),
        "labels": np.array(["alpha", "beta"], dtype=object),
        "metrics": {
            "classes": np.array(["yes", "no"], dtype=object),
            "note": "ok",
        },
    }

    zip_name = namespace["export_artifacts"](results, workflow_name="robust")
    out_dir = tmp_path / Path(zip_name).stem

    assert (tmp_path / zip_name).exists()
    assert (out_dir / "spectra_target.csv").exists()
    assert "class_a" in (out_dir / "spectra_target.csv").read_text(encoding="utf-8")
    assert (out_dir / "labels.csv").exists()
    assert "alpha" in (out_dir / "labels.csv").read_text(encoding="utf-8")
    assert (out_dir / "metrics_classes.csv").exists()
    assert (out_dir / "metrics_summary.json").exists()


def test_output_export_node_handles_string_arrays(tmp_path, monkeypatch) -> None:
    node = ExportNode(node_id="exp_1", parameters={"filename": "labels.csv", "format": "csv"})
    lines = node.generate_python({"default": "input_data"}, indent="    ", use_scp=False)
    code = "\n".join(
        [
            "import os",
            "import numpy as np",
            "results = {}",
            "def run_export(input_data):",
            *lines,
            "    return results",
        ]
    )

    namespace: dict = {}
    exec(code, namespace)

    monkeypatch.chdir(tmp_path)
    namespace["run_export"](np.array(["alpha", "beta"], dtype=object))

    output_path = tmp_path / "labels.csv"
    assert output_path.exists()
    assert "alpha" in output_path.read_text(encoding="utf-8")
