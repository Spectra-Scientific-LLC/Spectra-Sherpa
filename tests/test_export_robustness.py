from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

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


def test_export_artifacts_handles_string_targets_and_arrays(tmp_path, monkeypatch) -> None:
    code = generate_python_code(_workflow())
    namespace: dict = {}
    exec(code, namespace)

    monkeypatch.chdir(tmp_path)
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
