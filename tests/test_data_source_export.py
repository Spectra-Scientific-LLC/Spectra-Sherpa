"""Tests for DataSourceNode.generate_python() — Python export of standard data loaders.

Covers:
- sklearn datasets: iris, wine, breast_cancer, digits
- Eigenvector datasets: corn_m5, diesel_nir (with/without properties)
- SpectroChemPy example datasets: irdata (SCP mode), numpy mode fallback
- Multi-port output (default + target)
- supports_python_export() conditional on source type
- Orchestrator integration (exportable source nodes skip placeholder)
"""

from __future__ import annotations

import pytest

from spectra_sherpa.app.lib.scp_compat import HAS_SCP
from spectra_sherpa.app.services.dag.node_base import node_registry

# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _create_source(source: str, **extra) -> object:
    """Create a DataSourceNode with the given source type and extra params."""
    params = {"source": source, **extra}
    return node_registry.create_node("data.source", "src_1", params)


def _gen(node, *, multi_port: bool = False, use_scp: bool = True) -> str:
    """Run generate_python and return joined code."""
    inputs = {"_multi_port": str(multi_port)} if multi_port else {}
    lines = node.generate_python(inputs, indent="    ", use_scp=use_scp)
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# supports_python_export
# ═══════════════════════════════════════════════════════════════════════════


class TestSupportsExport:
    """DataSourceNode.supports_python_export() returns True only for
    sklearn / eigenvector / spectrochempy sources."""

    @pytest.mark.parametrize("source", ["sklearn", "eigenvector", "spectrochempy"])
    def test_supported_sources(self, source):
        node = _create_source(source)
        assert node.supports_python_export() is True

    @pytest.mark.parametrize("source", ["file", "experiment", "library", "synthetic", ""])
    def test_unsupported_sources(self, source):
        node = _create_source(source)
        assert node.supports_python_export() is False


# ═══════════════════════════════════════════════════════════════════════════
# sklearn
# ═══════════════════════════════════════════════════════════════════════════


class TestSklearnExport:
    """Sklearn source emits SherpaDataset construction with proper imports."""

    @pytest.mark.parametrize(
        "dataset,loader",
        [
            ("iris", "load_iris"),
            ("wine", "load_wine"),
            ("breast_cancer", "load_breast_cancer"),
            ("digits", "load_digits"),
        ],
    )
    def test_sklearn_loader_import(self, dataset, loader):
        node = _create_source("sklearn", sklearn_dataset=dataset)
        code = _gen(node)
        assert f"from sklearn.datasets import {loader}" in code

    def test_sherpa_dataset_import(self):
        code = _gen(_create_source("sklearn", sklearn_dataset="iris"))
        assert "from spectra_sherpa.app.lib.sherpa_dataset import" in code
        assert "SherpaDataset" in code
        assert "SpectralAxis" in code
        assert "SampleAxis" in code
        assert "TargetContext" in code

    def test_sherpa_dataset_construction(self):
        code = _gen(_create_source("sklearn", sklearn_dataset="iris"))
        assert "_ds = SherpaDataset(" in code
        assert "_bunch.data," in code
        assert "feature_axis=SpectralAxis(" in code
        assert "sample_axis=SampleAxis(" in code
        assert "target=_bunch.target," in code

    def test_target_context_categorical(self):
        code = _gen(_create_source("sklearn", sklearn_dataset="iris"))
        assert "target_type='categorical'" in code
        assert "target_names=list(_bunch.target_names)" in code

    def test_title_matches_dataset_name(self):
        code = _gen(_create_source("sklearn", sklearn_dataset="wine"))
        assert "title='wine'" in code

    def test_single_port_output(self):
        code = _gen(_create_source("sklearn"), multi_port=False)
        assert "results['src_1'] = _ds" in code
        assert "'default'" not in code

    def test_multi_port_output(self):
        code = _gen(_create_source("sklearn"), multi_port=True)
        assert "results['src_1'] = {'default': _ds, 'target': _ds.target}" in code

    def test_print_statement(self):
        code = _gen(_create_source("sklearn", sklearn_dataset="iris"))
        assert "Data Source (sklearn.iris)" in code

    def test_no_scp_dependency(self):
        """sklearn export should not reference scp (works in both modes)."""
        code = _gen(_create_source("sklearn"), use_scp=False)
        assert "scp." not in code
        assert "SherpaDataset" in code


# ═══════════════════════════════════════════════════════════════════════════
# Eigenvector
# ═══════════════════════════════════════════════════════════════════════════


class TestEigenvectorExport:
    """Eigenvector source emits SherpaDataset with catalog metadata."""

    def test_eigenvector_import(self):
        code = _gen(_create_source("eigenvector", eigenvector_dataset="corn_m5"))
        assert "from spectra_sherpa.app.lib.eigenvector import load_eigenvector_dataset" in code

    def test_sherpa_dataset_construction(self):
        code = _gen(_create_source("eigenvector", eigenvector_dataset="corn_m5"))
        assert "_ev = load_eigenvector_dataset('corn_m5')" in code
        assert "_ds = SherpaDataset(" in code
        assert "_ev['spectra']," in code

    def test_feature_axis_with_wavelengths(self):
        code = _gen(_create_source("eigenvector", eigenvector_dataset="corn_m5"))
        assert "feature_axis=SpectralAxis(" in code
        assert "_wavelengths" in code

    def test_catalog_x_title(self):
        """corn_m5 has x_title='Channel'."""
        code = _gen(_create_source("eigenvector", eigenvector_dataset="corn_m5"))
        assert "title='Channel'" in code

    def test_catalog_x_units_present(self):
        """diesel_nir has x_units='nm'."""
        code = _gen(_create_source("eigenvector", eigenvector_dataset="diesel_nir"))
        assert "units='nm'" in code

    def test_catalog_x_units_absent(self):
        """corn_m5 has x_units=None — no units= line emitted."""
        code = _gen(_create_source("eigenvector", eigenvector_dataset="corn_m5"))
        # Should not contain units= inside SpectralAxis for corn_m5
        lines = code.split("\n")
        spectral_block = []
        in_spectral = False
        for line in lines:
            if "feature_axis=SpectralAxis(" in line:
                in_spectral = True
            if in_spectral:
                spectral_block.append(line)
                if line.strip().startswith("),"):
                    break
        spectral_code = "\n".join(spectral_block)
        assert "units=" not in spectral_code

    def test_target_with_prop_names(self):
        """corn_m5 has prop_names=['Moisture', 'Oil', 'Protein', 'Starch']."""
        code = _gen(_create_source("eigenvector", eigenvector_dataset="corn_m5"))
        assert "target=_ev.get('properties')" in code
        assert "target_type='continuous'" in code
        assert "'Moisture'" in code
        assert "'Protein'" in code

    def test_label_from_catalog(self):
        code = _gen(_create_source("eigenvector", eigenvector_dataset="corn_m5"))
        assert "Corn M5 NIR" in code

    def test_single_port_output(self):
        code = _gen(_create_source("eigenvector", eigenvector_dataset="corn_m5"), multi_port=False)
        assert "results['src_1'] = _ds" in code

    def test_multi_port_output(self):
        code = _gen(_create_source("eigenvector", eigenvector_dataset="corn_m5"), multi_port=True)
        assert "'default': _ds" in code
        assert "'target': _ds.target" in code

    def test_no_scp_dependency(self):
        code = _gen(_create_source("eigenvector"), use_scp=False)
        assert "scp." not in code


# ═══════════════════════════════════════════════════════════════════════════
# SpectroChemPy
# ═══════════════════════════════════════════════════════════════════════════


class TestSpectrochempyExport:
    """SpectroChemPy source emits scp.read() → from_nddataset() conversion."""

    def test_scp_mode_reads_file(self):
        code = _gen(_create_source("spectrochempy", example_dataset="irdata"), use_scp=True)
        assert "scp.read(" in code

    def test_scp_known_default_path(self):
        """irdata has a known default path."""
        code = _gen(_create_source("spectrochempy", example_dataset="irdata"), use_scp=True)
        assert "irdata/nh4y-activation.spg" in code

    def test_from_nddataset_conversion(self):
        code = _gen(_create_source("spectrochempy", example_dataset="irdata"), use_scp=True)
        assert "from spectra_sherpa.app.lib.scp_compat import from_nddataset" in code
        assert "_ds = from_nddataset(_ndd)" in code

    def test_unknown_dataset_placeholder(self):
        """Datasets without known defaults get EDIT comment."""
        code = _gen(_create_source("spectrochempy", example_dataset="ramandata"), use_scp=True)
        assert "YOUR_FILE_HERE" in code
        assert "EDIT" in code

    def test_custom_example_file(self):
        """Specific example_file overrides the default path."""
        node = _create_source("spectrochempy", example_dataset="irdata", example_file="CO@Mo_Al2O3.SPG")
        code = _gen(node, use_scp=True)
        assert "irdata/CO@Mo_Al2O3.SPG" in code

    def test_numpy_mode_raises_import_error(self):
        code = _gen(_create_source("spectrochempy"), use_scp=False)
        assert "raise ImportError" in code
        assert "spectrochempy" in code

    def test_single_port_output(self):
        code = _gen(_create_source("spectrochempy", example_dataset="irdata"), use_scp=True, multi_port=False)
        assert "results['src_1'] = _ds" in code

    def test_multi_port_output(self):
        code = _gen(_create_source("spectrochempy", example_dataset="irdata"), use_scp=True, multi_port=True)
        assert "'default': _ds" in code


# ═══════════════════════════════════════════════════════════════════════════
# Orchestrator integration
# ═══════════════════════════════════════════════════════════════════════════


class TestOrchestratorIntegration:
    """The python_export orchestrator delegates to generate_python for
    exportable source nodes instead of emitting generic placeholders."""

    def test_sklearn_source_no_placeholder(self):
        """Exported code for sklearn source should not contain '>>> EDIT' placeholder."""
        from spectra_sherpa.app.services.python_export import generate_python_code

        wf = _make_workflow(
            "test sklearn export",
            nodes=[
                _wf_node("src", "data.source", {"source": "sklearn", "sklearn_dataset": "iris"}),
                _wf_node("pca", "model.pca", {"n_components": 3}),
            ],
            edges=[_wf_edge("src", "pca")],
        )

        code = generate_python_code(wf)
        assert "SherpaDataset(" in code
        assert "load_iris" in code
        # Should NOT contain the generic placeholder
        assert ">>> EDIT: provide your data below <<<" not in code

    def test_file_source_still_placeholder(self):
        """File source (non-exportable) should still get the generic placeholder."""
        from spectra_sherpa.app.services.python_export import generate_python_code

        wf = _make_workflow(
            "test file export",
            nodes=[
                _wf_node("src", "data.source", {"source": "file", "file_path": "/tmp/data.csv"}),
                _wf_node("pca", "model.pca", {"n_components": 3}),
            ],
            edges=[_wf_edge("src", "pca")],
        )

        code = generate_python_code(wf)
        # Placeholder now uses a DATA LOADING banner instead of ">>> EDIT"
        assert "DATA LOADING" in code
        assert "SherpaDataset.from_nddataset" not in code
        assert "from spectra_sherpa.app.lib.scp_compat import from_nddataset" in code

    def test_eigenvector_multi_port_export(self):
        """Eigenvector source with both default and target ports connected."""
        from spectra_sherpa.app.services.python_export import generate_python_code

        wf = _make_workflow(
            "test eigenvector multi-port",
            nodes=[
                _wf_node("src", "data.source", {"source": "eigenvector", "eigenvector_dataset": "corn_m5"}),
                _wf_node("pls", "model.pls", {"n_components": 3}),
            ],
            edges=[
                _wf_edge("src", "pls", from_output="default", to_input="default"),
                _wf_edge("src", "pls", from_output="target", to_input="y"),
            ],
        )

        code = generate_python_code(wf)
        assert "SherpaDataset(" in code
        assert "load_eigenvector_dataset('corn_m5')" in code
        assert "'default': _ds" in code
        assert "'target': _ds.target" in code


# ═══════════════════════════════════════════════════════════════════════════
# Code executability
# ═══════════════════════════════════════════════════════════════════════════


class TestCodeExecutability:
    """Generated code should be syntactically valid Python."""

    @pytest.mark.parametrize(
        "source,extra",
        [
            ("sklearn", {"sklearn_dataset": "iris"}),
            ("eigenvector", {"eigenvector_dataset": "corn_m5"}),
            ("spectrochempy", {"example_dataset": "irdata"}),
        ],
    )
    def test_syntax_valid(self, source, extra):
        """Generated code compiles without SyntaxError."""
        node = _create_source(source, **extra)
        code = _gen(node, use_scp=True)
        # Wrap in a function so indentation is valid
        wrapped = f"def _test():\n{code}"
        compile(wrapped, "<test>", "exec")

    def test_sklearn_executes(self):
        """sklearn export actually runs and produces a SherpaDataset."""
        node = _create_source("sklearn", sklearn_dataset="iris")
        code = _gen(node, use_scp=False)

        ns = {"np": __import__("numpy"), "results": {}}
        wrapped = f"def _run():\n{code}\n    return results"
        exec(compile(wrapped, "<test>", "exec"), ns)
        result = ns["_run"]()
        ds = result["src_1"]

        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        assert isinstance(ds, SherpaDataset)
        assert ds.shape == (150, 4)
        assert ds.target is not None
        assert len(ds.target) == 150

    def test_eigenvector_executes(self):
        """Eigenvector export actually runs and produces a SherpaDataset."""
        node = _create_source("eigenvector", eigenvector_dataset="corn_m5")
        code = _gen(node, use_scp=False)

        ns = {"np": __import__("numpy"), "results": {}}
        wrapped = f"def _run():\n{code}\n    return results"
        exec(compile(wrapped, "<test>", "exec"), ns)
        result = ns["_run"]()
        ds = result["src_1"]

        from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

        assert isinstance(ds, SherpaDataset)
        assert ds.shape == (80, 700)
        assert ds.target is not None
        assert ds.target.shape[0] == 80


# ═══════════════════════════════════════════════════════════════════════════
# Workflow model helpers (lightweight mocks for orchestrator tests)
# ═══════════════════════════════════════════════════════════════════════════

from types import SimpleNamespace


def _wf_node(node_id: str, node_type: str, parameters: dict) -> SimpleNamespace:
    """Create a lightweight workflow node duck-type."""
    return SimpleNamespace(node_id=node_id, node_type=node_type, parameters=parameters)


def _wf_edge(
    from_id: str,
    to_id: str,
    from_output: str = "default",
    to_input: str = "default",
) -> SimpleNamespace:
    """Create a lightweight workflow edge duck-type."""
    return SimpleNamespace(
        from_node_id=from_id,
        to_node_id=to_id,
        from_output=from_output,
        to_input=to_input,
    )


def _make_workflow(name: str, nodes: list, edges: list) -> SimpleNamespace:
    """Create a lightweight workflow duck-type."""
    return SimpleNamespace(
        name=name,
        description="",
        nodes=nodes,
        edges=edges,
    )


@pytest.mark.skipif(not HAS_SCP, reason="SCP required for export execution")
def test_preprocess_normalize_then_pls_export_preserves_embedded_targets():
    """Preprocessing export should preserve embedded targets for downstream PLS."""
    import spectra_sherpa.app.services.dag.nodes.data.source  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.modeling.pls_nodes  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
    from spectra_sherpa.app.services.python_export import generate_python_code, validate_export

    wf = _make_workflow(
        "normalize to pls",
        nodes=[
            _wf_node("src", "data.source", {"source": "eigenvector", "eigenvector_dataset": "corn_m5"}),
            _wf_node("norm", "preprocess.normalize", {"method": "snv"}),
            _wf_node("pls", "model.pls", {"n_components": 3, "scale": True}),
        ],
        edges=[
            _wf_edge("src", "norm", from_output="default", to_input="default"),
            _wf_edge("norm", "pls", from_output="default", to_input="X"),
        ],
    )

    assert validate_export(wf) == []

    ns = {"__name__": "__main__"}
    exec(generate_python_code(wf), ns)
    results = ns["run_workflow"]()

    assert results["pls"]["y_true"].shape == (80, 4)
    assert results["pls"]["r2"].shape == (4,)


@pytest.mark.skipif(not HAS_SCP, reason="SIMCA export requires spectrochempy")
def test_simca_to_classifier_predict_export_uses_model_port():
    """SIMCA export should validate when wired through the wrapped model port."""
    import spectra_sherpa.app.services.dag.nodes.classification.predict_node  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.classification.simca_nodes  # noqa: F401
    import spectra_sherpa.app.services.dag.nodes.data.source  # noqa: F401
    from spectra_sherpa.app.services.python_export import generate_python_code, validate_export

    wf = _make_workflow(
        "simca predict",
        nodes=[
            _wf_node("src", "data.source", {"source": "sklearn", "sklearn_dataset": "iris"}),
            _wf_node("train", "classification.simca", {"n_components": 2}),
            _wf_node("pred", "classification.predict", {}),
        ],
        edges=[
            _wf_edge("src", "train", from_output="default", to_input="X"),
            _wf_edge("src", "train", from_output="target", to_input="y"),
            _wf_edge("src", "pred", from_output="default", to_input="X_new"),
            _wf_edge("train", "pred", from_output="model", to_input="model"),
        ],
    )

    assert validate_export(wf) == []

    code = generate_python_code(wf)
    assert "results['train']['model']" in code
    assert "'model': {" in code


def test_knn_export_emits_plots_port():
    """KNN export should emit every declared output port, including plots."""
    import spectra_sherpa.app.services.dag.nodes.classification.knn_nodes  # noqa: F401

    node = node_registry.create_node("classification.knn", "knn_1", {})
    code = "\n".join(node.generate_python({}, indent="    ", use_scp=True))

    assert "'plots': {}" in code
