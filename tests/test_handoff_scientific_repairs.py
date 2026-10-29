"""Counterexamples from the data-portfolio handoff audit, using generated data."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services import run_output_retention as retention
from spectra_sherpa.app.services.dag.nodes.data.split_planner import materialize_split_outputs, plan_train_test_split
from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import FittedPLSV2Node
from spectra_sherpa.app.services.dag.nodes.modeling.mcr_nodes import _compare_mcr_spectra_to_truth
from spectra_sherpa.app.services.dag.nodes.regression_evaluator_node import evaluate_regression_v2
from spectra_sherpa.app.services.dag.population_authority import qualify_evaluation_result
from spectra_sherpa.app.services.dag.regression_comparison import build_regression_comparison
from spectra_sherpa.app.services.scientific_comparison import compare_evidence, resolve_run_evidence


def retained_run(prefix, *, label_prefix="display", collection="a", typed=True, comparison_ids=None):
    x = np.arange(36, dtype=float).reshape(12, 3)
    y = np.arange(12, dtype=float)
    plan = plan_train_test_split(x, y, method="random")
    source = SherpaDataset(
        X=x,
        target=y,
        sample_axis=SampleAxis(
            labels=[f"{label_prefix}-{i}" for i in range(12)],
            sample_table={"sample_id": [f"{prefix}-{i}" for i in range(12)]} if typed else None,
        ),
        extra={
            "source_collection": {
                "source_manifest_sha256": "a" * 64,
                "collection_definition_sha256": collection * 64,
                "scientific_collection_sha256": collection * 64,
            }
        },
    )
    outputs = materialize_split_outputs(source, x, y, plan, node_id="split")
    target = y[plan.test_indices]
    comparison = build_regression_comparison(target, target + 0.1, role="held_out_test")
    comparison["metadata"]["population_authority"] = {
        "schema_version": "spectrasherpa-population-authority/1",
        "qualification": "graph_verified",
        "population": ["split", "test"],
        "fitted_populations": [["split", "train"]],
    }
    if comparison_ids is not None:
        comparison["metadata"]["sample_ids"] = comparison_ids
    return SimpleNamespace(
        id=prefix,
        user_id=1,
        name=prefix,
        diagnostics={},
        source_metadata={},
        evidence_completeness=retention.retain_run_outputs(
            1,
            {
                "split": outputs,
                "eval": {"comparison": comparison},
                "__workflow__": {
                    "definition": {
                        "schema_version": 1,
                        "nodes": [{"node_id": "split", "node_type": "data.train_test_split"}],
                        "edges": [],
                    }
                },
            },
            {},
        ),
    )


@pytest.mark.parametrize("change", ["ids", "collection", "labels"])
def test_real_retention_preserves_identity_and_distinguishes_labels(tmp_path, monkeypatch, change):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    left = resolve_run_evidence(retained_run("A"))
    right = resolve_run_evidence(
        retained_run(
            "B" if change == "ids" else "A",
            collection="b" if change == "collection" else "a",
            label_prefix="renamed" if change == "labels" else "display",
        )
    )
    assert len(left.evaluations) == len(right.evaluations) == 1
    result = compare_evidence([left, right])
    section = next(s for s in result.pairs[0].sections if s.role == "held_out")
    assert (section.state == "comparable") == (change == "labels")
    if change == "ids":
        assert left.evaluations[0].sample_ids != right.evaluations[0].sample_ids


@pytest.mark.parametrize("kwargs", [{"typed": False}, {"comparison_ids": ["A-6", "A-3"]}])
def test_missing_or_misaligned_identity_cannot_qualify_retained_comparison(tmp_path, monkeypatch, kwargs):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    assert not resolve_run_evidence(retained_run("A", **kwargs)).evaluations


@pytest.mark.parametrize("mutation", ["shifted", "reversed", "wrong_units", "missing", "quantity", "nan", "exact"])
def test_mcr_ground_truth_requires_exact_physical_grid(mutation):
    axis = np.arange(600.0, 611.0)
    signal = np.exp(-((axis - 605) ** 2) / 3)[None, :]
    truth = axis.copy()
    if mutation == "shifted":
        truth += 10
    if mutation == "reversed":
        truth = truth[::-1]
    if mutation == "nan":
        truth[0] = np.nan
    dataset = SherpaDataset(
        X=np.zeros((3, len(axis))),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        extra={
            "ground_truth.spectra": signal.tolist(),
            "ground_truth.spectra_x": None if mutation == "missing" else truth.tolist(),
            "ground_truth.spectra_x_title": "Raman shift" if mutation == "quantity" else "Wavenumber",
            "ground_truth.spectra_x_units": "nm" if mutation == "wrong_units" else "cm^-1",
        },
    )
    result = _compare_mcr_spectra_to_truth(signal, dataset)
    assert (result is not None) == (mutation == "exact")
    if result is not None:
        assert result["selected_match"]["r2"] == pytest.approx(1.0)


@pytest.mark.parametrize("n_targets", [1, 2])
def test_graph_verified_regression_uses_exact_branch_labels_and_ids(n_targets):
    target = np.arange(6 * n_targets, dtype=float).reshape(6, n_targets)
    source = SherpaDataset(
        X=np.ones((6, 3)),
        target=target,
        sample_axis=SampleAxis(
            labels=[f"original-{i}" for i in [135, 142, 149, 151, 155, 157]],
            sample_table={"sample_id": [f"id-{i}" for i in range(6)]},
        ),
    )
    result = evaluate_regression_v2(target + 0.1, target)
    receipt = {
        "role": "held_out_test",
        "qualification": "graph_verified",
        "population": ["split", "test"],
        "fitted_populations": [["split", "train"]],
    }
    qualify_evaluation_result(result, receipt, source_results={"split": {"X_test": source}})
    comparison = result.outputs["comparison"]
    assert [row["sample"] for row in comparison["data"]] == [
        label for label in source.sample_axis.labels for _ in range(n_targets)
    ]
    assert comparison["metadata"]["sample_ids"] == source.sample_axis.sample_table["sample_id"]
    assert comparison["data"][0]["predicted"] == 0.1


@pytest.mark.asyncio
async def test_fitted_pls_preserves_curated_sample_labels():
    rng = np.random.default_rng(2026)
    x = rng.normal(size=(20, 5))
    y = x[:, 0] * 2 + x[:, 1]
    labels = [f"vial-{i+135}" for i in range(20)]
    source = SherpaDataset(
        X=x, target=y, sample_axis=SampleAxis(labels=labels, sample_table={"sample_id": [f"id-{i}" for i in range(20)]})
    )
    result = await FittedPLSV2Node("fit", {"n_components": 2}).run(source)
    comparison = result.outputs["calibration_comparison"]
    assert [row["sample"] for row in comparison["data"]] == labels
    assert comparison["metadata"]["sample_ids"] == source.sample_axis.sample_table["sample_id"]


def test_qualification_cannot_overwrite_contradictory_producer_identity():
    from copy import deepcopy

    source = SherpaDataset(
        X=np.ones((3, 2)),
        sample_axis=SampleAxis(labels=["a", "b", "c"], sample_table={"sample_id": ["id-a", "id-b", "id-c"]}),
    )
    result = evaluate_regression_v2(np.arange(3.0) + 0.1, np.arange(3.0))
    result.outputs["comparison"]["metadata"]["sample_ids"] = ["id-b", "id-a", "id-c"]
    before = deepcopy(result.outputs["comparison"]["data"])
    receipt = {
        "role": "held_out_test",
        "qualification": "graph_verified",
        "population": ["split", "test"],
        "fitted_populations": [["split", "train"]],
    }
    with pytest.raises(ValueError, match="identities disagree"):
        qualify_evaluation_result(result, receipt, source_results={"split": {"X_test": source}})
    assert result.outputs["comparison"]["metadata"]["sample_ids"] == ["id-b", "id-a", "id-c"]
    assert result.outputs["comparison"]["data"] == [{**row, "role": "held_out_test"} for row in before]


def test_typed_target_evaluator_preserves_ids_and_refuses_misaligned_predictions():
    target = SherpaDataset(
        X=np.arange(4.0).reshape(-1, 1),
        sample_axis=SampleAxis(
            labels=["vial135", "", "vial142", "vial155"], sample_table={"sample_id": ["a", "b", "c", "d"]}
        ),
    )
    result = evaluate_regression_v2(target.X + 0.1, target)
    assert [row["sample"] for row in result.outputs["comparison"]["data"]] == ["vial135", "b", "vial142", "vial155"]
    assert result.outputs["comparison"]["metadata"]["sample_ids"] == ["a", "b", "c", "d"]
    predicted = SherpaDataset(
        X=target.X + 0.1, sample_axis=SampleAxis(sample_table={"sample_id": ["b", "a", "c", "d"]})
    )
    with pytest.raises(ValueError, match="sample IDs"):
        evaluate_regression_v2(predicted, target)


@pytest.mark.asyncio
async def test_pls_blank_display_label_does_not_invalidate_typed_identity():
    rng = np.random.default_rng(21)
    x = rng.normal(size=(15, 3))
    dataset = SherpaDataset(
        X=x,
        target=x[:, 0],
        sample_axis=SampleAxis(
            labels=[""] + [f"vial-{i}" for i in range(1, 15)],
            sample_table={"sample_id": [f"id-{i}" for i in range(15)]},
        ),
    )
    result = await FittedPLSV2Node("fit", {"n_components": 2}).run(dataset)
    assert result.outputs["calibration_comparison"]["data"][0]["sample"] == "id-0"


def test_unsplit_calibration_identity_does_not_depend_on_display_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))

    def make_run(labels, offset=0, units="absorbance"):
        x = np.arange(36.0, dtype=float).reshape(12, 3) + offset
        y = np.arange(12.0, dtype=float)
        source = SherpaDataset(
            X=x,
            target=y,
            units=units,
            sample_axis=SampleAxis(labels=labels, sample_table={"sample_id": [f"id-{i}" for i in range(12)]}),
            extra={"source_collection": {"source_manifest_sha256": "a" * 64}},
        )
        comparison = build_regression_comparison(y, y + 0.1, role="calibration", sample_dataset=source)
        return SimpleNamespace(
            id="run",
            user_id=1,
            name="run",
            diagnostics={},
            source_metadata={},
            evidence_completeness=retention.retain_run_outputs(
                1,
                {
                    "load": {"default": source},
                    "pls": {"calibration_comparison": comparison},
                    "__workflow__": {
                        "definition": {
                            "schema_version": 1,
                            "nodes": [{"node_id": "pls", "node_type": "model.fitted_pls"}],
                            "edges": [{"from_node_id": "load", "to_node_id": "pls", "to_input": "default"}],
                        }
                    },
                },
                {},
            ),
        )

    first = resolve_run_evidence(make_run([f"a-{i}" for i in range(12)]))
    renamed = resolve_run_evidence(make_run([f"b-{i}" for i in range(12)]))
    changed = resolve_run_evidence(make_run([f"a-{i}" for i in range(12)], 1))
    assert len(first.evaluations) == len(renamed.evaluations) == len(changed.evaluations) == 1
    assert first.evaluations[0].sample_ids == renamed.evaluations[0].sample_ids
    assert first.evaluations[0].feature_receipt != changed.evaluations[0].feature_receipt
    unit_change = resolve_run_evidence(make_run([f"a-{i}" for i in range(12)], units="transmittance"))
    assert first.evaluations[0].feature_receipt != unit_change.evaluations[0].feature_receipt


def test_typed_label_only_evaluator_refuses_contradictory_order():
    target = SherpaDataset(X=np.arange(3.0).reshape(-1, 1), sample_axis=SampleAxis(labels=["A", "B", "C"]))
    prediction = SherpaDataset(X=target.X, sample_axis=SampleAxis(labels=["B", "A", "C"]))
    with pytest.raises(ValueError, match="sample labels"):
        evaluate_regression_v2(prediction, target)


def test_closed_retained_budget_refusal_is_not_reported_as_missing_cv(monkeypatch):
    from spectra_sherpa.app.services import retained_regression_comparison as adapter

    def unavailable(run):
        raise adapter.RetainedComparisonUnavailable(
            "Retained comparison exceeds the bounded read budget; inspect individual run outputs."
        )

    monkeypatch.setattr(adapter, "retained_regression_evidence", unavailable)
    run = SimpleNamespace(id=1, user_id=1, name="limited", diagnostics={}, source_metadata={}, evidence_completeness={})
    result = resolve_run_evidence(run)
    assert "bounded read budget" in result.unavailable_reason
    assert "out-of-fold" not in result.unavailable_reason


def test_run_metric_projection_preserves_equal_distinct_producers():
    from spectra_sherpa.app.services.run_metrics import comparable_results_for_run

    assert comparable_results_for_run(
        {"held_out": {"rmse": 1}, "training_cv": {"rmse": 1}}, qualify_producers=True
    ) == {
        "held_out.rmse": 1,
        "training_cv.rmse": 1,
    }
    assert comparable_results_for_run({"renamed": {"rmse": 1}}, qualify_producers=True) == {"renamed.rmse": 1}


def test_missing_held_out_identity_reason_survives_valid_calibration(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    x = np.arange(36.0).reshape(12, 3)
    y = np.arange(12.0)
    source = SherpaDataset(
        X=x,
        target=y,
        sample_axis=SampleAxis(sample_table={"sample_id": [f"id-{i}" for i in range(12)]}),
        extra={"source_collection": {"source_manifest_sha256": "a" * 64}},
    )
    plan = plan_train_test_split(x, y, method="random")
    outputs = materialize_split_outputs(source, x, y, plan, node_id="split")
    axis = outputs["X_test"].sample_axis
    axis.sample_table = None
    outputs["X_test"].sample_axis = axis
    retained = {
        "split": outputs,
        "__workflow__": {
            "definition": {
                "schema_version": 1,
                "nodes": [{"node_id": "split", "node_type": "data.train_test_split"}],
                "edges": [],
            }
        },
    }
    for branch, role, indices in [
        ("train", "calibration", plan.train_indices),
        ("test", "held_out_test", plan.test_indices),
    ]:
        comparison = build_regression_comparison(y[indices], y[indices] + 0.1, role=role)
        comparison["metadata"]["population_authority"] = {
            "qualification": "graph_verified",
            "population": ["split", branch],
            "fitted_populations": [["split", "train"]],
        }
        retained[branch] = {"comparison": comparison}
    run = SimpleNamespace(
        id=1,
        user_id=1,
        name="mixed",
        diagnostics={},
        source_metadata={},
        evidence_completeness=retention.retain_run_outputs(1, retained, {}),
    )
    resolved = resolve_run_evidence(run)
    assert [item.role for item in resolved.evaluations] == ["calibration"]
    assert "Typed sample identities were not retained" in resolved.unavailable_reason


def test_evaluation_storage_error_does_not_expose_paths(monkeypatch):
    from spectra_sherpa.app.schemas.scientific_comparison import PopulationSummary
    from spectra_sherpa.app.services import retained_regression_comparison as adapter
    from spectra_sherpa.app.services import scientific_comparison as module

    monkeypatch.setattr(adapter, "retained_regression_evidence", lambda run: ((), PopulationSummary()))

    def fail(*args):
        raise OSError("PRIVATE_PATH_SENTINEL")

    monkeypatch.setattr(module, "_evaluation", fail)
    run = SimpleNamespace(
        id=1, user_id=1, name="unreadable", diagnostics={}, source_metadata={}, evidence_completeness={}
    )
    result = resolve_run_evidence(run)
    assert result.unavailable_reason == "Retained evaluation evidence could not be read."
