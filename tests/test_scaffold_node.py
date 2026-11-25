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


def test_contract_scaffold_is_the_default_and_runs_under_the_current_contract(tmp_path: Path, monkeypatch) -> None:
    import asyncio
    import sys

    import numpy as np

    from spectra_sherpa.app.services.dag import node_base

    scaffold = _load_scaffold_module()
    assert scaffold.VALID_NODE_TYPES[0] == "contract"
    scaffold.generate_scaffold(
        class_name="MovingMedianNode",
        node_type="contract",
        category="preprocessing",
        description="Replace each point with the median of an odd window",
        repo_root=tmp_path,
    )
    node_file = tmp_path / "src/spectra_sherpa/app/services/dag/nodes/preprocessing/moving_median_node.py"
    test_source = (tmp_path / "tests/nodes/test_moving_median_node.py").read_text(encoding="utf-8")
    assert "test_matches_an_independent_oracle" in test_source and "test_refuses_invalid_parameters" in test_source

    # Import the generated module as an in-tree node without adding it to the live catalog.
    monkeypatch.setattr(node_base, "register_node", lambda node_class: node_class)
    name = "spectra_sherpa.app.services.dag.nodes.preprocessing.moving_median_node"
    spec = importlib.util.spec_from_file_location(name, node_file)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    node_class = module.MovingMedianNode
    payload = node_class.get_metadata().resolved_execution_contract().payload
    assert payload["operation_id"] == "preprocess.moving_median" and payload["lifecycle_kind"] == "stateless_transform"
    node_base.NodeRegistry().register(node_class)  # passes the registry's policy and port validation

    import spectra_sherpa.sdk as ss

    values = np.vstack([np.sin(np.linspace(0, 3, 20)) + index for index in range(2)])
    output = asyncio.run(node_class("n1", {}).execute(ss.data.from_array(values, x=np.arange(20.0))))
    assert output.outputs["default"].shape == (2, 20)
    for bad in (4, True, 53):
        try:
            asyncio.run(node_class("n1", {"window": bad}).execute(ss.data.from_array(values, x=np.arange(20.0))))
        except ValueError:
            continue
        raise AssertionError(f"window={bad!r} was not refused")
