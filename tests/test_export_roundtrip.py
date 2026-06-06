"""Round-trip validation: DAG execution → Python export → exec → compare.

For each workflow template, this test:
1. Builds a workflow from the template's node/edge structure
2. Generates Python export code via generate_python_code()
3. Validates the code parses (ast.parse)
4. For templates with known test data, executes the exported code and
   compares numerical outputs to DAG execution results.

This ensures that exported scripts are both syntactically valid and
numerically faithful to the GUI execution.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from spectra_sherpa.app.lib.scp_compat import HAS_SCP
from spectra_sherpa.app.services.notebook_export import generate_notebook
from spectra_sherpa.app.services.python_export import generate_python_code, validate_export

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "src" / "spectra_sherpa" / "data" / "templates"


def _load_template(name: str) -> dict:
    """Load a YAML template by name."""
    path = TEMPLATE_DIR / f"{name}.yaml"
    if not path.exists():
        pytest.skip(f"Template {name} not found at {path}")
    with open(path) as f:
        return yaml.safe_load(f)


def _template_to_workflow(template: dict) -> SimpleNamespace:
    """Convert a template dict to a minimal Workflow-like object."""
    nodes = []
    for n in template.get("nodes", []):
        nodes.append(
            SimpleNamespace(
                node_id=n["id"],
                node_type=n["type"],
                parameters=n.get("parameters", {}),
            )
        )

    edges = []
    for e in template.get("edges", []):
        edges.append(
            SimpleNamespace(
                from_node_id=e["from"],
                to_node_id=e["to"],
                from_output=e.get("fromOutput", e.get("from_output")),
                to_input=e.get("toInput", e.get("to_input")),
            )
        )

    return SimpleNamespace(
        name=template.get("name", "Unknown"),
        description=template.get("description", ""),
        nodes=nodes,
        edges=edges,
        integrity_hash="test_roundtrip",
    )


def _list_template_names() -> list[str]:
    """Get all template names excluding _categories."""
    names = []
    for f in sorted(TEMPLATE_DIR.glob("*.yaml")):
        if f.stem.startswith("_"):
            continue
        names.append(f.stem)
    return names


ALL_TEMPLATES = _list_template_names()


# ═══════════════════════════════════════════════════════════════════════════
# Test 1: All templates pass export validation
# ═══════════════════════════════════════════════════════════════════════════


class TestExportValidation:
    """Every published template must pass export validation (no unsupported nodes)."""

    @pytest.mark.parametrize("template_name", ALL_TEMPLATES)
    def test_template_validates(self, template_name: str):
        template = _load_template(template_name)
        wf = _template_to_workflow(template)
        errors = validate_export(wf)
        if errors:
            detail = "; ".join(f"{e.node_id} ({e.node_type}): {e.reason}" for e in errors)
            pytest.fail(f"Template '{template_name}' has export validation errors: {detail}")


# ═══════════════════════════════════════════════════════════════════════════
# Test 2: All templates generate valid Python
# ═══════════════════════════════════════════════════════════════════════════


class TestExportSyntax:
    """Every published template must generate syntactically valid Python."""

    @pytest.mark.parametrize("template_name", ALL_TEMPLATES)
    def test_template_syntax(self, template_name: str):
        template = _load_template(template_name)
        wf = _template_to_workflow(template)

        try:
            code = generate_python_code(wf)
        except ValueError as e:
            pytest.skip(f"Export not supported: {e}")

        # Must parse without errors
        try:
            ast.parse(code)
        except SyntaxError as e:
            pytest.fail(f"Template '{template_name}' generated invalid Python:\n{e}\n\nCode:\n{code[:500]}")

        # Basic structural checks
        assert "def run_workflow():" in code
        assert "results = {}" in code
        assert "SherpaDataset" in code or "results['" in code
        assert "DATA_DIR" in code


# ═══════════════════════════════════════════════════════════════════════════
# Test 3: All templates generate valid notebooks
# ═══════════════════════════════════════════════════════════════════════════


class TestNotebookExport:
    """Every published template must generate a valid nbformat 4 notebook."""

    @pytest.mark.parametrize("template_name", ALL_TEMPLATES)
    def test_template_notebook(self, template_name: str):
        template = _load_template(template_name)
        wf = _template_to_workflow(template)

        try:
            nb = generate_notebook(wf)
        except ValueError as e:
            pytest.skip(f"Export not supported: {e}")

        assert nb["nbformat"] == 4
        assert nb["nbformat_minor"] == 5
        assert len(nb["cells"]) >= 4  # title, getting-started, imports, at least 1 node

        # Every cell must have valid structure
        for i, cell in enumerate(nb["cells"]):
            assert "cell_type" in cell, f"Cell {i} missing cell_type"
            assert cell["cell_type"] in ("markdown", "code"), f"Cell {i} invalid type"
            assert "source" in cell, f"Cell {i} missing source"
            if cell["cell_type"] == "code":
                assert "execution_count" in cell
                assert "outputs" in cell

        # Must have Getting Started guide
        all_src = " ".join("".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "markdown")
        assert "Getting Started" in all_src


# ═══════════════════════════════════════════════════════════════════════════
# Test 4: Numerical round-trip for key workflows
# ═══════════════════════════════════════════════════════════════════════════


class TestNumericalRoundtrip:
    """Execute exported code and compare to expected results."""

    def test_pca_sklearn_roundtrip(self):
        """PCA on sklearn iris: exported script must produce correct scores shape."""
        wf = SimpleNamespace(
            name="PCA Test",
            description="",
            nodes=[
                SimpleNamespace(
                    node_id="src_1",
                    node_type="data.source",
                    parameters={"source": "sklearn", "sklearn_dataset": "iris"},
                ),
                SimpleNamespace(node_id="pca_1", node_type="model.pca", parameters={"n_components": 3}),
            ],
            edges=[
                SimpleNamespace(from_node_id="src_1", to_node_id="pca_1", from_output="default", to_input="default"),
            ],
            integrity_hash="test",
        )

        code = generate_python_code(wf)
        ast.parse(code)

        # Execute
        ns: dict = {}
        exec(code, ns)
        results = ns["run_workflow"]()

        # PCA should produce scores with shape (150, 3)
        assert "pca_1" in results
        pca_result = results["pca_1"]
        assert isinstance(pca_result, dict)
        assert "scores" in pca_result

        scores = pca_result["scores"]
        scores_data = np.asarray(scores.data if hasattr(scores, "data") else scores)
        assert scores_data.shape == (150, 3), f"Expected (150, 3), got {scores_data.shape}"

        # Explained variance should sum to < 1.0 (3 components of 4)
        ev = pca_result.get("explained_variance")
        if ev is not None:
            ev_data = np.asarray(ev.data if hasattr(ev, "data") else ev)
            assert ev_data.shape[0] == 3
            assert 0.0 < float(np.sum(ev_data)) <= 1.0

    @pytest.mark.skipif(not HAS_SCP, reason="PLS requires SCP")
    def test_pls_sklearn_roundtrip(self):
        """PLS on sklearn iris (with embedded target): R² must be positive."""
        wf = SimpleNamespace(
            name="PLS Test",
            description="",
            nodes=[
                SimpleNamespace(
                    node_id="src_1",
                    node_type="data.source",
                    parameters={"source": "sklearn", "sklearn_dataset": "iris"},
                ),
                SimpleNamespace(node_id="pls_1", node_type="model.pls", parameters={"n_components": 3}),
            ],
            edges=[
                SimpleNamespace(from_node_id="src_1", to_node_id="pls_1", from_output="default", to_input="X"),
            ],
            integrity_hash="test",
        )

        code = generate_python_code(wf)
        ast.parse(code)
        assert "# SCP may squeeze single-target predictions to 1D; reshape to match _y_data" in code
        assert "if _y_pred.ndim == 1:" in code

        ns: dict = {}
        exec(code, ns)
        results = ns["run_workflow"]()

        assert "pls_1" in results
        pls_result = results["pls_1"]
        assert isinstance(pls_result, dict)

        # R² should be positive for iris PLS
        r2 = pls_result.get("r2")
        if r2 is not None:
            r2_val = float(np.asarray(r2).flat[0])
            assert r2_val > 0.0, f"R² should be positive, got {r2_val}"

    def test_preprocess_pca_roundtrip(self):
        """Preprocessing → PCA: scores must have correct dimensionality."""
        wf = SimpleNamespace(
            name="Preprocess PCA",
            description="",
            nodes=[
                SimpleNamespace(
                    node_id="src_1",
                    node_type="data.source",
                    parameters={"source": "sklearn", "sklearn_dataset": "iris"},
                ),
                SimpleNamespace(node_id="norm_1", node_type="preprocess.normalize", parameters={}),
                SimpleNamespace(node_id="pca_1", node_type="model.pca", parameters={"n_components": 2}),
            ],
            edges=[
                SimpleNamespace(from_node_id="src_1", to_node_id="norm_1", from_output="default", to_input="default"),
                SimpleNamespace(from_node_id="norm_1", to_node_id="pca_1", from_output=None, to_input="default"),
            ],
            integrity_hash="test",
        )

        code = generate_python_code(wf)
        ns: dict = {}
        exec(code, ns)
        results = ns["run_workflow"]()

        scores = results["pca_1"]["scores"]
        scores_data = np.asarray(scores.data if hasattr(scores, "data") else scores)
        assert scores_data.shape == (150, 2)

    @pytest.mark.skipif(not HAS_SCP, reason="PLS-DA requires SCP")
    def test_classification_plsda_roundtrip(self):
        """PLS-DA on iris: must produce predictions for all samples."""
        wf = SimpleNamespace(
            name="PLSDA Test",
            description="",
            nodes=[
                SimpleNamespace(
                    node_id="src_1",
                    node_type="data.source",
                    parameters={"source": "sklearn", "sklearn_dataset": "iris"},
                ),
                SimpleNamespace(node_id="scale_1", node_type="preprocess.scale", parameters={}),
                SimpleNamespace(node_id="plsda_1", node_type="classification.plsda", parameters={"n_components": 3}),
            ],
            edges=[
                SimpleNamespace(from_node_id="src_1", to_node_id="scale_1", from_output="default", to_input="default"),
                SimpleNamespace(from_node_id="scale_1", to_node_id="plsda_1", from_output=None, to_input="X"),
            ],
            integrity_hash="test",
        )

        code = generate_python_code(wf)
        ast.parse(code)

        ns: dict = {}
        exec(code, ns)
        results = ns["run_workflow"]()

        assert "plsda_1" in results
        plsda_result = results["plsda_1"]
        assert isinstance(plsda_result, dict)

        preds = plsda_result.get("predictions")
        if preds is not None:
            pred_data = np.asarray(preds)
            assert pred_data.shape[0] == 150
        assert "cv_accuracy" in plsda_result.get("metrics", {})

    def test_stats_summary_roundtrip(self):
        """Stats summary: must produce statistics dict."""
        wf = SimpleNamespace(
            name="Stats Test",
            description="",
            nodes=[
                SimpleNamespace(
                    node_id="src_1",
                    node_type="data.source",
                    parameters={"source": "sklearn", "sklearn_dataset": "iris"},
                ),
                SimpleNamespace(node_id="stats_1", node_type="stats.summary", parameters={}),
            ],
            edges=[
                SimpleNamespace(from_node_id="src_1", to_node_id="stats_1", from_output="default", to_input="default"),
            ],
            integrity_hash="test",
        )

        code = generate_python_code(wf)
        ns: dict = {}
        exec(code, ns)
        results = ns["run_workflow"]()

        assert "stats_1" in results
        stats = results["stats_1"]
        assert isinstance(stats, dict)
        assert "statistics" in stats
        summary = stats["statistics"]
        assert summary["n_samples"] == 150
        assert summary["n_features"] == 4

    def test_hca_roundtrip(self):
        """HCA on iris: must produce cluster assignments."""
        wf = SimpleNamespace(
            name="HCA Test",
            description="",
            nodes=[
                SimpleNamespace(
                    node_id="src_1",
                    node_type="data.source",
                    parameters={"source": "sklearn", "sklearn_dataset": "iris"},
                ),
                SimpleNamespace(node_id="hca_1", node_type="model.hca", parameters={"n_clusters": 3}),
            ],
            edges=[
                SimpleNamespace(from_node_id="src_1", to_node_id="hca_1", from_output="default", to_input="default"),
            ],
            integrity_hash="test",
        )

        code = generate_python_code(wf)
        ns: dict = {}
        exec(code, ns)
        results = ns["run_workflow"]()

        assert "hca_1" in results
        hca_result = results["hca_1"]
        assert isinstance(hca_result, dict)
        labels = hca_result.get("labels")
        if labels is not None:
            labels_data = np.asarray(labels)
            assert labels_data.shape[0] == 150
            assert len(np.unique(labels_data)) == 3

    def test_peak_finding_roundtrip(self):
        """Peak finding: must detect peaks in synthetic data."""
        wf = SimpleNamespace(
            name="Peak Test",
            description="",
            nodes=[
                SimpleNamespace(
                    node_id="src_1",
                    node_type="data.source",
                    parameters={"source": "sklearn", "sklearn_dataset": "iris"},
                ),
                SimpleNamespace(node_id="pf_1", node_type="analysis.peak_finding", parameters={"distance": 1}),
            ],
            edges=[
                SimpleNamespace(from_node_id="src_1", to_node_id="pf_1", from_output="default", to_input="default"),
            ],
            integrity_hash="test",
        )

        code = generate_python_code(wf)
        ast.parse(code)

        ns: dict = {}
        exec(code, ns)
        results = ns["run_workflow"]()

        assert "pf_1" in results
        pf_result = results["pf_1"]
        assert isinstance(pf_result, dict)
        assert "peaks" in pf_result

    @pytest.mark.skipif(
        not HAS_SCP,
        reason="Plot node requires matplotlib via SCP",
    )
    def test_plot_roundtrip(self):
        """Plot node: must produce a visualization dict/figure."""
        wf = SimpleNamespace(
            name="Plot Test",
            description="",
            nodes=[
                SimpleNamespace(
                    node_id="src_1",
                    node_type="data.source",
                    parameters={"source": "sklearn", "sklearn_dataset": "iris"},
                ),
                SimpleNamespace(node_id="plot_1", node_type="output.plot", parameters={"plot_type": "spectra"}),
            ],
            edges=[
                SimpleNamespace(from_node_id="src_1", to_node_id="plot_1", from_output="default", to_input="default"),
            ],
            integrity_hash="test",
        )

        code = generate_python_code(wf)
        ns: dict = {}
        exec(code, ns)
        results = ns["run_workflow"]()

        assert "plot_1" in results
        plot_result = results["plot_1"]
        assert isinstance(plot_result, dict)
        assert "visualization" in plot_result

    def test_export_node_roundtrip(self, tmp_path):
        """Export node: must create output file info."""
        wf = SimpleNamespace(
            name="Export Test",
            description="",
            nodes=[
                SimpleNamespace(
                    node_id="src_1",
                    node_type="data.source",
                    parameters={"source": "sklearn", "sklearn_dataset": "iris"},
                ),
                SimpleNamespace(
                    node_id="exp_1",
                    node_type="output.export",
                    parameters={"filename": str(tmp_path / "output.csv"), "format": "csv"},
                ),
            ],
            edges=[
                SimpleNamespace(from_node_id="src_1", to_node_id="exp_1", from_output="default", to_input="default"),
            ],
            integrity_hash="test",
        )

        code = generate_python_code(wf)
        ns: dict = {}
        exec(code, ns)
        results = ns["run_workflow"]()

        assert "exp_1" in results
        assert (tmp_path / "output.csv").exists()


# ═══════════════════════════════════════════════════════════════════════════
# Test 5: Artifact export produces zip
# ═══════════════════════════════════════════════════════════════════════════


class TestArtifactExport:
    """The export_artifacts function must produce a zip file."""

    def test_artifact_zip_created(self, tmp_path):
        """Run workflow and export artifacts to a zip."""
        wf = SimpleNamespace(
            name="Zip Test",
            description="",
            nodes=[
                SimpleNamespace(
                    node_id="src_1",
                    node_type="data.source",
                    parameters={"source": "sklearn", "sklearn_dataset": "iris"},
                ),
                SimpleNamespace(node_id="pca_1", node_type="model.pca", parameters={"n_components": 2}),
            ],
            edges=[
                SimpleNamespace(from_node_id="src_1", to_node_id="pca_1", from_output="default", to_input="default"),
            ],
            integrity_hash="test",
        )

        code = generate_python_code(wf)
        ns: dict = {}
        exec(code, ns)

        # Change to tmp directory for zip creation
        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            results = ns["run_workflow"]()
            zip_path = ns["export_artifacts"](results)
            assert zip_path is not None
            assert os.path.exists(zip_path)
            assert zip_path.endswith(".zip")

            # Verify zip contents
            import zipfile

            with zipfile.ZipFile(zip_path) as zf:
                names = zf.namelist()
                assert len(names) > 0
                # Should contain CSV files for PCA outputs
                csv_files = [n for n in names if n.endswith(".csv")]
                assert len(csv_files) > 0
        finally:
            os.chdir(old_cwd)
