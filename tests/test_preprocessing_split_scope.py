"""Scientific reference SR-001: sample-local transforms commute with a fixed split."""

from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset
from spectra_sherpa.app.services.dag.executor import DAGExecutor, WorkflowEdge, WorkflowNode
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.population_authority import analyze_populations

NORMALIZATION_MODES = [
    {"method": "snv", "std_ddof": 0},
    {"method": "snv", "std_ddof": 1},
    *({"method": "scale", "scale_method": method} for method in ("max", "area", "minmax")),
]


def test_preprocessing_contract_audit_covers_the_registered_category():
    expected = {
        "stateless_transform": {
            "baseline.rubberband",
            "baseline.penalized_ls",
            "preprocess.clip_floor",
            "preprocess.clip_range",
            "preprocess.cosmic_ray",
            "preprocess.derivative",
            "preprocess.normalize",
            "preprocess.smooth",
            "preprocess.wavenumber_align",
            "time_series.moving_window",
            "time_series.trend_removal",
        },
        "fitted_transform": {
            "preprocess.scale",
            "preprocess.shared_reference_scale",
            "preprocess.msc",
            "preprocess.emsc",
            "preprocess.osc",
            "transfer.ds",
            "transfer.pds",
            "transfer.sws",
        },
        "artifact_application": {
            "preprocess.apply_fitted_scale",
            "preprocess.apply_fitted_msc",
            "preprocess.apply_fitted_emsc",
            "preprocess.apply_fitted_osc",
            "transfer.apply_fitted",
        },
    }
    actual = {}
    for metadata in node_registry.list_by_category("preprocessing"):
        lifecycle = metadata.resolved_execution_contract().payload["lifecycle_kind"]
        actual.setdefault(lifecycle, set()).add(metadata.node_type)
    assert actual == expected  # New/changed operations require an explicit scope audit.


def test_scientific_reference_resolves_contract_and_source_checks():
    import re

    root = Path(__file__).parents[1]
    index = (root / "docs/scientific-references/index.md").read_text()
    topic = (root / "docs/scientific-references/preprocessing-validation.md").read_text()
    contract = (root / "docs/architecture/workflows.md").read_text()
    assert "10.1111/rssb.12537" in index
    assert all("PREPROCESS-SCOPE-1" in text for text in (index, topic, contract))
    for path in re.findall(r"`((?:app/|tests/)[^`]+\.py)`", topic):
        assert (root / ("src/spectra_sherpa" if path.startswith("app/") else "") / path).is_file(), path


def split_graph(node_type, params):
    executor = DAGExecutor(process_pool=None)
    for node in (
        WorkflowNode("source", "data.file_load", {"experiment_id": 1, "file_id": 1}),
        WorkflowNode("pre", node_type, params),
        WorkflowNode("split", "data.train_test_split", {"split_method": "sequential", "test_size": 0.25}),
    ):
        executor.add_node(node)
    executor.add_edge(WorkflowEdge("source", "pre"))
    executor.add_edge(WorkflowEdge("pre", "split", "default", "X"))
    return executor


@pytest.mark.parametrize("params", NORMALIZATION_MODES)
@pytest.mark.asyncio
async def test_normalization_before_fixed_split_preserves_values_and_sample_identity(params):
    executor = split_graph("preprocess.normalize", params)
    assert executor.validate_full().is_valid
    data = SherpaDataset(
        X=np.random.default_rng(31).normal(size=(12, 7)),
        sample_axis=SampleAxis(labels=[f"sample-{i}" for i in range(12)]),
    )

    async def source():
        return data

    executor.nodes["source"].execute = source
    actual = (await executor.execute())["split"]
    raw_split = await node_registry.create_node(
        "data.train_test_split", "raw_split", {"split_method": "sequential", "test_size": 0.25}
    ).execute(X=data)
    for port in ("X_train", "X_test"):
        expected = await node_registry.create_node("preprocess.normalize", "local", params).execute(raw_split[port])
        np.testing.assert_array_equal(actual[port].data, expected.outputs["default"].data)
        assert actual[port].sample_axis.labels == expected.outputs["default"].sample_axis.labels


@pytest.mark.parametrize(
    "method,center",
    [("mean_center", True), ("autoscale", True), ("autoscale", False), ("pareto", True), ("pareto", False)],
)
def test_fitted_scaling_stays_refused_before_split(method, center):
    result = split_graph("preprocess.scale", {"method": method, "center": center}).validate_full()
    assert not result.is_valid
    scope = [issue for issue in result.errors if issue.code == "preprocessing_fit_scope"]
    assert len(scope) == 1
    assert "fit after Train/Test Split" in scope[0].message
    assert "lifecycle_kind" not in scope[0].message


def test_normalization_does_not_hide_an_earlier_fitted_scaler():
    executor = split_graph("preprocess.normalize", {"method": "snv"})
    executor.add_node(WorkflowNode("scale", "preprocess.scale", {"method": "autoscale"}))
    executor.edges[0] = WorkflowEdge("scale", "pre")
    executor.add_edge(WorkflowEdge("source", "scale"))
    assert any(i.code == "preprocessing_fit_scope" for i in executor.validate_full().errors)


def held_out_graph_with_presplit_scaling():
    executor = split_graph("preprocess.scale", {"method": "autoscale"})
    for node in (
        WorkflowNode("fit", "model.fitted_pls", {"n_components": 2}),
        WorkflowNode("apply", "model.apply_fitted_pls", {}),
        WorkflowNode("eval", "diagnostics.regression_evaluator", {}),
    ):
        executor.add_node(node)
    for edge in (
        WorkflowEdge("source", "split", "target", "y"),
        WorkflowEdge("split", "fit", "X_train"),
        WorkflowEdge("fit", "apply", "fitted_state", "fitted_state"),
        WorkflowEdge("split", "apply", "X_test"),
        WorkflowEdge("apply", "eval"),
        WorkflowEdge("split", "eval", "y_test", "y_true"),
    ):
        executor.add_edge(edge)
    return executor


def test_root_refusal_does_not_repeat_as_downstream_evaluation_error():
    executor = held_out_graph_with_presplit_scaling()
    errors = executor.validate_full().errors
    assert len(errors) == 1, errors
    assert errors[0].code == "preprocessing_fit_scope"
    # Invalidating a known-refused boundary can never promote its descendants.
    _, receipts = analyze_populations(executor.nodes, executor.edges, invalid_boundaries=frozenset({"split"}))
    assert receipts["eval"]["role"] == "unqualified_evaluation"
    # Standalone authority still refuses when it has no prior refusal context.
    assert analyze_populations(executor.nodes, executor.edges)[0]
    # A model trained on split B and evaluated on refused split A still has
    # an independent population mismatch; causal dedup must not hide it.
    executor.add_node(WorkflowNode("split_b", "data.train_test_split", {"test_size": 0.25}))
    executor.add_edge(WorkflowEdge("source", "split_b", "default", "X"))
    training_edge = next(edge for edge in executor.edges if edge.to_node == "fit")
    training_edge.from_node = "split_b"
    cross_split_errors = executor.validate_full().errors
    assert any(i.code == "preprocessing_fit_scope" for i in cross_split_errors)
    assert any("same split's training branch" in i.message for i in cross_split_errors)
    training_edge.from_node = "split"
    # A separate error (fitting on test rows) must remain visible as well.
    training_edge.from_output = "X_test"
    assert any("fitting on an explicit test branch" in i.message for i in executor.validate_full().errors)


def test_dedup_distinguishes_independent_fits_on_the_same_source():
    executor = held_out_graph_with_presplit_scaling()
    training_edge = next(edge for edge in executor.edges if edge.to_node == "fit")
    training_edge.from_node = "source"
    training_edge.from_output = "default"
    executor.add_node(WorkflowNode("test_scale", "preprocess.scale", {"method": "autoscale"}))
    test_edge = next(edge for edge in executor.edges if edge.to_node == "apply" and edge.from_node == "split")
    test_edge.from_node = "test_scale"
    test_edge.from_output = "default"
    executor.add_edge(WorkflowEdge("split", "test_scale", "X_test", "default"))
    executor.add_edge(WorkflowEdge("split", "test_scale", "X_train", "reference"))
    errors = executor.validate_full().errors
    assert any(i.code == "preprocessing_fit_scope" for i in errors)
    assert any("same split's training branch" in i.message for i in errors)
    _, receipts = analyze_populations(executor.nodes, executor.edges, invalid_boundaries=frozenset({"split"}))
    assert receipts["eval"]["role"] == "unqualified_evaluation"


@pytest.mark.asyncio
async def test_training_scaler_ignores_test_statistics_and_applies_same_state():
    train = SherpaDataset(X=np.array([[1.0, 2.0], [3.0, 6.0], [5.0, 10.0]]))
    test = SherpaDataset(X=np.array([[100.0, 200.0]]))
    node = node_registry.create_node("preprocess.scale", "scale", {"method": "autoscale"})
    state = node.fit_fitted_state(train)
    expected = node.apply_fitted_state(test, state)
    actual = await node.execute(default=test, reference=train)
    np.testing.assert_array_equal(actual.outputs["default"].data, expected.data)
    full = SherpaDataset(X=np.vstack([train.data, test.data]))
    leaked = node.apply_fitted_state(test, node.fit_fitted_state(full))
    assert not np.allclose(actual.outputs["default"].data, leaked.data)
