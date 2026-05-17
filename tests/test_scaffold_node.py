from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_scaffold_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "scaffold_node.py"
    spec = importlib.util.spec_from_file_location("scaffold_node", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_scaffold_generation_uses_current_preprocessing_layout(tmp_path: Path) -> None:
    scaffold = _load_scaffold_module()

    scaffold.generate_scaffold(
        class_name="MedianFilterNode",
        node_type="chemometrics",
        category="preprocessing",
        description="Median filter smoothing",
        repo_root=tmp_path,
    )

    node_file = (
        tmp_path
        / "src"
        / "spectra_sherpa"
        / "app"
        / "services"
        / "dag"
        / "nodes"
        / "preprocessing"
        / "median_filter_node.py"
    )
    test_file = tmp_path / "tests" / "nodes" / "test_median_filter_node.py"
    docs_file = tmp_path / "docs" / "dev" / "generated_nodes" / "median_filter_node.md"

    assert node_file.exists()
    assert test_file.exists()
    assert docs_file.exists()

    node_source = node_file.read_text(encoding="utf-8")
    test_source = test_file.read_text(encoding="utf-8")
    docs_source = docs_file.read_text(encoding="utf-8")

    assert 'category = "preprocessing"' in node_source
    assert "from spectra_sherpa.sdk import" in node_source
    assert "nodes.preprocessing.median_filter_node import MedianFilterNode" in test_source
    assert "nodes.preprocessing.median_filter_node import MedianFilterNode" in docs_source
    compile(node_source, str(node_file), "exec")


def test_scaffold_generation_maps_regression_to_modeling_package(tmp_path: Path) -> None:
    scaffold = _load_scaffold_module()

    scaffold.generate_scaffold(
        class_name="RandomForestNode",
        node_type="estimator",
        category="regression",
        description="Random forest regression",
        repo_root=tmp_path,
    )

    node_file = (
        tmp_path
        / "src"
        / "spectra_sherpa"
        / "app"
        / "services"
        / "dag"
        / "nodes"
        / "modeling"
        / "random_forest_node.py"
    )
    test_file = tmp_path / "tests" / "nodes" / "test_random_forest_node.py"

    assert node_file.exists()
    assert test_file.exists()

    node_source = node_file.read_text(encoding="utf-8")
    test_source = test_file.read_text(encoding="utf-8")

    assert 'category="regression"' in node_source
    assert "nodes.modeling.random_forest_node import RandomForestNode" in test_source
    compile(node_source, str(node_file), "exec")
