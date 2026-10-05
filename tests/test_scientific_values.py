"""Scientific output descriptions preserve typed chemometric dimensions."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.data.transforms import TrainTestSplitNode
from spectra_sherpa.app.services.dag.nodes.modeling.apply_fitted_pls_node import ApplyFittedPLSV2Node
from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import FittedPLSV2Node
from spectra_sherpa.app.services.dag.nodes.regression_evaluator_node import evaluate_regression_v2
from spectra_sherpa.app.services.dag.scientific_values import (
    build_scientific_output_semantics_census,
    describe_node_outputs,
)
from spectra_sherpa.app.types import ensure_type_registry_loaded, type_registry

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SEMANTICS_CENSUS_PATH = _REPOSITORY_ROOT / "docs/evidence/scientific-output-semantics-census.json"


def test_every_type_has_closed_scientific_semantics() -> None:
    ensure_type_registry_loaded()

    assert len(type_registry.list_types()) == 42
    for type_def in type_registry.list_types():
        assert type_def.scientific_kind
        assert type_def.view_kind
        assert type_def.content_categories
        assert len(type_def.content_categories) == len(set(type_def.content_categories))
        assert all(rank >= 0 for rank in type_def.ranks)


def test_every_builtin_output_port_resolves_to_scientific_semantics() -> None:
    """No catalog node can produce an output the workbench cannot describe."""

    ensure_type_registry_loaded()

    output_ports = [
        (metadata.node_type, port.name, port.type_ref)
        for metadata in node_registry.list_nodes()
        for port in metadata.output_ports
    ]
    assert output_ports
    for node_type, port_name, type_ref in output_ports:
        type_def = type_registry.resolve(type_ref)
        assert type_def.scientific_kind, f"{node_type}.{port_name} has no scientific kind"
        assert type_def.view_kind, f"{node_type}.{port_name} has no view kind"
        assert type_def.content_categories, f"{node_type}.{port_name} has no content category"


def test_live_scientific_output_census_matches_checked_authority() -> None:
    """The all-node audit is reproducible from the live registries."""

    live = build_scientific_output_semantics_census(node_registry.list_nodes())
    checked = json.loads(_SEMANTICS_CENSUS_PATH.read_text(encoding="utf-8"))

    assert live == checked
    assert checked["aggregates"]["registered_nodes"] == len(node_registry.list_nodes())
    assert checked["aggregates"]["registered_types"] == len(type_registry.list_types())
    assert all(row["output_ports"] for row in checked["nodes"])


@pytest.mark.asyncio
async def test_corn_shaped_pls_path_has_exact_port_dimensions() -> None:
    """The seven-node starter's scientific values remain separate and aligned."""

    rng = np.random.default_rng(20260816)
    X = rng.normal(size=(80, 700))
    y = 10.0 + X[:, :4] @ np.asarray([0.8, -0.4, 0.3, 0.2])
    source = SherpaDataset(X=X, target=y)

    split_node = TrainTestSplitNode(
        "partition_1",
        {"split_method": "sequential", "test_size": 0.25, "random_seed": 42, "n_components": 0},
    )
    split = await split_node.execute(X=source, y=y)
    split_values = describe_node_outputs(split_node.metadata, split)

    assert split_values["X_train"]["shape"] == [60, 700]
    assert split_values["y_train"]["shape"] == [60, 1]
    assert split_values["X_test"]["shape"] == [20, 700]
    assert split_values["y_test"]["shape"] == [20, 1]
    assert split_values["train_indices"]["shape"] == [60]
    assert split_values["test_indices"]["shape"] == [20]
    assert split_values["X_train"]["dimensions"] == [
        {"role": "sample", "size": 60},
        {"role": "spectral_variable", "size": 700},
    ]
    assert split_values["y_train"]["dimensions"] == [
        {"role": "sample", "size": 60},
        {"role": "target", "size": 1},
    ]

    fit_node = FittedPLSV2Node("model_1", {"n_components": 3, "scale": True})
    fit = await fit_node.execute(split["X_train"], split["y_train"])
    fit_values = describe_node_outputs(fit_node.metadata, fit.outputs)
    assert fit_values["default"]["shape"] == [60, 1]
    assert fit_values["fitted_state"]["shape"] is None
    assert fit_values["fitted_state"]["view_kind"] == "model"
    assert fit_values["vip_scores"]["shape"] == [700]

    apply_node = ApplyFittedPLSV2Node("predict_1", {})
    applied = await apply_node.execute(split["X_test"], fit.outputs["fitted_state"])
    apply_values = describe_node_outputs(apply_node.metadata, applied.outputs)
    assert apply_values["default"]["shape"] == [20, 1]

    evaluation = evaluate_regression_v2(applied.outputs["default"], split["y_test"], node_id="eval_1")
    from spectra_sherpa.app.services.dag.nodes.regression_evaluator_node import RegressionEvaluatorV2Node

    evaluation_values = describe_node_outputs(RegressionEvaluatorV2Node.metadata, evaluation.outputs)
    assert evaluation_values["default"]["shape"] is None
    assert evaluation_values["default"]["view_kind"] == "metric_record"
    assert evaluation_values["comparison"]["shape"] == [20, 6]
    assert evaluation_values["comparison"]["dimensions"] == [
        {"role": "observation", "size": 20},
        {
            "role": "comparison_field",
            "size": 6,
            "labels": ["Sample", "Target", "Reference", "Predicted", "Residual", "Role"],
        },
    ]
    assert evaluation_values["comparison"]["content_categories"] == [
        "reference_targets",
        "sample_level_results",
    ]


def test_model_and_record_values_never_become_fake_empty_datasets() -> None:
    model_descriptor = describe_node_outputs(
        FittedPLSV2Node.metadata,
        {
            "default": np.ones((3, 1)),
            "fitted_state": {"serializer": "example"},
            "vip_scores": np.ones(5),
        },
    )

    assert model_descriptor["fitted_state"]["shape"] is None
    assert model_descriptor["fitted_state"]["view_modes"] == ["model_summary"]
    assert model_descriptor["fitted_state"]["content_categories"] == ["model_artifacts"]


def test_generic_visualization_remains_unclassified_for_future_egress() -> None:
    from spectra_sherpa.app.services.dag.nodes.output.plot_node import PlotNode

    descriptor = describe_node_outputs(
        PlotNode.metadata,
        {"visualization": {"data": [{"x": [1, 2], "y": [3, 4]}], "layout": {}}},
    )["visualization"]

    assert descriptor["shape"] == [2, 2]
    assert descriptor["content_categories"] == ["visualizations", "unclassified"]


def test_regression_comparison_plot_describes_points_and_sensitive_contents() -> None:
    """A reference line must not hide plot-point dimensions or target content."""

    from spectra_sherpa.app.services.dag.nodes.output.plot_node import PlotNode, build_plot_result

    result = build_plot_result(
        {
            "schema_version": "spectrasherpa-regression-comparison/1",
            "shape": [2, 6],
            "data": [
                {
                    "sample": "Corn 1",
                    "target": "Moisture",
                    "reference": 10.0,
                    "predicted": 9.8,
                    "residual": 0.2,
                    "role": "held_out_test",
                },
                {
                    "sample": "Corn 2",
                    "target": "Moisture",
                    "reference": 11.0,
                    "predicted": 11.1,
                    "residual": -0.1,
                    "role": "held_out_test",
                },
            ],
            "metadata": {
                "column_names": ["sample", "target", "reference", "predicted", "residual", "role"],
                "n_samples": 2,
                "n_targets": 1,
                "target_names": ["Moisture"],
                "role": "held_out_test",
                "residual_definition": "reference_minus_predicted",
            },
        }
    )
    descriptor = describe_node_outputs(PlotNode.metadata, result)["visualization"]

    assert descriptor["shape"] == [2, 2]
    assert descriptor["dimensions"] == [
        {"role": "held_out_sample", "size": 2},
        {"role": "actual_predicted_value", "size": 2, "labels": ["Actual", "Predicted"]},
    ]
    assert descriptor["content_categories"] == [
        "reference_targets",
        "sample_level_results",
        "visualizations",
    ]
