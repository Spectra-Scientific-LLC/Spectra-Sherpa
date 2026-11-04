"""Real synthetic catalog data has labels and row custody, but no sample_id column."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.lib.collection_assembly import CollectionMember, assemble_collection
from spectra_sherpa.app.lib.collection_definition import scientific_collection_identity_from_digest
from spectra_sherpa.app.lib.sample_identity import sample_ids
from spectra_sherpa.app.lib.sherpa_dataset import TargetContext
from spectra_sherpa.app.lib.synthetic_references import load_synthetic_reference_as_sherpa
from spectra_sherpa.app.services import run_output_retention as retention
from spectra_sherpa.app.services.dag.nodes.data.split_planner import materialize_split_outputs, plan_train_test_split
from spectra_sherpa.app.services.dag.regression_comparison import (
    bind_regression_sample_axis,
    build_regression_comparison,
)
from spectra_sherpa.app.services.retained_regression_comparison import retained_regression_evidence

METHANE = 3


def _root():
    dataset = load_synthetic_reference_as_sherpa("Synthetic_atmospheric-6")
    member = CollectionMember(dataset, "Synthetic_atmospheric-6.npz", 10, "b" * 64)
    root = assemble_collection([member], title="Synthetic_atmospheric-6")
    collection = root.meta["source_collection"]
    collection.update(scientific_collection_identity_from_digest(collection, None))
    assert sample_ids(root) is None and root.meta["source_observations"]
    return root


def _run(root, *, offset=0.1, seed=42, mutate=None):
    x = np.asarray(root.X, dtype=float)
    y = np.asarray(root.target, dtype=float)[:, METHANE]
    context = TargetContext(target_names=["Methane"], target_units="ppm", target_type="continuous")
    plan = plan_train_test_split(x, y, method="random", random_seed=seed)
    split = materialize_split_outputs(root, x, y, plan, node_id="split", target_context=context)
    if mutate:
        mutate(split)
    comparison = build_regression_comparison(
        y[plan.test_indices], y[plan.test_indices] + offset, role="held_out_test", target_names=["Methane"]
    )
    bind_regression_sample_axis(comparison, split["X_test"])
    comparison["metadata"]["population_authority"] = {
        "qualification": "graph_verified",
        "population": ["split", "test"],
        "fitted_populations": [["split", "train"]],
    }
    calibration = build_regression_comparison(
        y[plan.train_indices], y[plan.train_indices] + offset, role="calibration", target_names=["Methane"]
    )
    bind_regression_sample_axis(calibration, split["X_train"])
    definition = {
        "schema_version": 1,
        "nodes": [
            {"node_id": "data", "node_type": "data.collection_load"},
            {"node_id": "split", "node_type": "data.train_test_split"},
            {"node_id": "model", "node_type": "model.fitted_pls"},
            {"node_id": "eval", "node_type": "diagnostics.regression_evaluator"},
        ],
        "edges": [
            {"from_node_id": "data", "from_output": "default", "to_node_id": "split", "to_input": "X"},
            {"from_node_id": "split", "from_output": "X_train", "to_node_id": "model", "to_input": "default"},
            {"from_node_id": "split", "from_output": "y_train", "to_node_id": "model", "to_input": "y"},
            {"from_node_id": "split", "from_output": "y_test", "to_node_id": "eval", "to_input": "y_true"},
        ],
    }
    outputs = {
        "data": {"default": root},
        "split": split,
        "model": {"calibration_comparison": calibration},
        "eval": {"comparison": comparison},
        "__workflow__": {"definition": definition},
    }
    run = SimpleNamespace(id="synthetic", user_id=1, evidence_completeness=retention.retain_run_outputs(1, outputs, {}))
    return retained_regression_evidence(run), plan


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    return _root()


def test_synthetic_runs_with_one_split_recover_the_same_paired_population(root):
    (first, population, complete), plan = _run(root, offset=0.1)
    (second, _, _), _ = _run(root, offset=0.2)
    assert complete and {item.role for item in first} == {"calibration", "held_out"}
    assert population.response == "Methane"
    assert population.development_count == len(plan.train_indices)
    assert population.held_out_count == len(plan.test_indices)
    assert [item.sample_ids for item in first] == [item.sample_ids for item in second]
    labels = list(root.sample_axis.labels)
    held_out = next(item for item in first if item.role == "held_out")
    assert held_out.units == "ppm"
    assert [item.rsplit(":", 1)[1] for item in held_out.sample_ids] == [labels[i] for i in plan.test_indices]


def test_recovery_does_not_rewrite_the_scientific_dataset(root):
    before = root.scientific_digest
    table = deepcopy(root.sample_axis.sample_table)
    _run(root)
    assert root.scientific_digest == before and root.sample_axis.sample_table == table


def test_different_splits_do_not_share_a_partition(root):
    (first, population, _), _ = _run(root, seed=1)
    (second, other, _), _ = _run(root, seed=2)
    assert first and second and population.partition_digest != other.partition_digest


@pytest.mark.parametrize("damage", ["missing", "reordered", "file_hash", "short"])
def test_damaged_receipt_stays_unqualified(root, damage):
    def mutate(split):
        for port in ("X_train", "X_test"):
            rows = deepcopy(split[port].meta["source_observations"])
            if damage == "missing":
                split[port].meta.pop("source_observations")
                continue
            if damage == "reordered":
                rows[0], rows[1] = rows[1], rows[0]
            elif damage == "file_hash":
                rows[0]["sha256"] = "f" * 64
            else:
                rows = rows[:-1]
            split[port].meta["source_observations"] = rows

    (records, population, _), _ = _run(root, mutate=mutate)
    assert records == ()
    assert any("not declared or recoverable" in reason for reason in population.limitations)


async def test_current_pls_starter_embedded_target_real_fit_keeps_methane_units(root):
    """Real named-unit control; the seven tests above cover retained identity recovery.

    Keep the current starter's embedded-target wiring, with two fixed components
    and a deterministic 38/12 split, not automatic component selection or a new
    optimization round. No database, provider, model publication or second fit.
    """
    from pathlib import Path

    from threadpoolctl import threadpool_limits

    from spectra_sherpa.app.core.template_loader import TemplateLoader
    from spectra_sherpa.app.services.dag.node_base import node_registry
    from spectra_sherpa.app.services.dag.nodes.data.split_planner import prepare_split_source
    from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import verify_fitted_pls_state_envelope
    from spectra_sherpa.app.types import type_registry
    from tests.performance_contract import PerformanceCeiling

    template = next(t for t in TemplateLoader().load_all() if t["slug"] == "pls_calibration")["template_data"]
    by_type = {node["node_type"]: node for node in template["nodes"]}
    model_spec = by_type["model.fitted_pls"]
    model_id = model_spec["node_id"]
    training_edges = [edge for edge in template["edges"] if edge["to_node_id"] == model_id]
    assert len(training_edges) == 1
    assert training_edges[0]["from_output"] == "X_train"
    assert training_edges[0]["to_input"] == "default"
    split_id = training_edges[0]["from_node_id"]
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src/spectra_sherpa/app/types")

    with PerformanceCeiling("model.fitted_pls", "synthetic-real-unit-control", 30).measure(), threadpool_limits(1):
        assert root.target_context.target_names[METHANE] == "Methane"
        assert root.target_context.target_units == "ppm"
        root.target_context = root.target_context.model_copy(update={"selected_target": "Methane"}, deep=True)
        before = root.scientific_digest
        dataset, x, y, context, source_indices = prepare_split_source(root, None)
        plan = plan_train_test_split(x, y, method="random", test_size=0.25, random_seed=42)
        assert (len(plan.train_indices), len(plan.test_indices)) == (38, 12)
        assert not set(plan.train_indices).intersection(plan.test_indices)
        assert len(set(plan.train_indices).union(plan.test_indices)) == root.n_samples == 50
        split = materialize_split_outputs(
            dataset, x, y, plan, node_id=split_id, target_context=context, source_indices=source_indices
        )
        model = node_registry.create_node(
            "model.fitted_pls",
            model_id,
            {
                **model_spec["parameters"],
                "n_components": 2,
                "component_fit_mode": "manual",
                "component_curve_max": 2,
                "component_cv_folds": 2,
            },
        )
        with PerformanceCeiling("model.fitted_pls", "38x5401-fixed-two-components", 5).measure():
            fit = await model.execute(input_data=split["X_train"])
        frozen = deepcopy(fit.outputs["fitted_state"])
        state = verify_fitted_pls_state_envelope(frozen)
        assert state["response_identity"] == {"names": ["Methane"], "units": ["ppm"]}
        assert fit.outputs["component_curve"]["selected_components"] == 2
        predictor_spec = by_type["model.predict_regression"]
        predictor = node_registry.create_node(predictor_spec["node_type"], predictor_spec["node_id"], {})
        prediction = await predictor.execute(input_data=split["X_test"], fitted_state=fit.outputs["fitted_state"])
        evaluator_spec = by_type["diagnostics.labeled_regression_evaluator"]
        evaluator = node_registry.create_node(evaluator_spec["node_type"], evaluator_spec["node_id"], {})
        evaluated = await evaluator.execute(
            input_data=prediction.outputs["default"], y_true=split["y_test"], sample_context=split["X_test"]
        )
        calibration = fit.outputs["calibration_comparison"]
        held_out = evaluated.outputs["comparison"]
        assert len(calibration["data"]) == 38 and len(held_out["data"]) == 12
        assert calibration["metadata"]["target_names"] == held_out["metadata"]["target_names"] == ["Methane"]
        assert evaluated.diagnostics["response_identity"] == {"names": ["Methane"], "units": ["ppm"]}
        np.testing.assert_allclose([row["reference"] for row in calibration["data"]], split["y_train"])
        np.testing.assert_allclose([row["reference"] for row in held_out["data"]], split["y_test"])
        np.testing.assert_allclose(
            [row["predicted"] for row in held_out["data"]], np.asarray(prediction.outputs["default"]).reshape(-1)
        )
        assert fit.outputs["fitted_state"] == frozen and root.scientific_digest == before
