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
