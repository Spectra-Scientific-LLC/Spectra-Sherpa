"""Five dissimilar saved-run cases, including exact retention and truthful gaps."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services import run_output_retention as retention
from spectra_sherpa.app.services.dag.nodes.data.split_planner import materialize_split_outputs, plan_train_test_split
from spectra_sherpa.app.services.dag.regression_comparison import build_regression_comparison
from spectra_sherpa.app.services.run_validation_summary import validation_summary


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))


def text(summary):
    return "\n".join(row["label"] + ": " + row["value"] for row in summary["rows"])


def split_run(*, supervised=True, grouped=False, columns=5, row_order=None):
    x = np.arange(12 * columns, dtype=float).reshape(12, columns)
    y = np.arange(12, dtype=float) if supervised else None
    groups = np.repeat(["A", "B", "C"], 4) if grouped else None
    if row_order is not None:
        x = x[row_order]
        y = y[row_order] if y is not None else None
    plan = plan_train_test_split(
        x, y, method="group_holdout" if grouped else "random", groups=groups, held_out_groups=["C"] if grouped else None
    )
    output = materialize_split_outputs(SherpaDataset(X=x), x, y, plan, node_id="split", groups=groups)
    definition = {
        "schema_version": 1,
        "nodes": [{"node_id": "split", "node_type": "data.train_test_split"}],
        "edges": [],
    }
    run = SimpleNamespace(
        id=7,
        user_id=1,
        status="completed",
        diagnostics={},
        source_metadata={},
        params_snapshot={"split": {"random_seed": 42}},
        evidence_completeness=retention.retain_run_outputs(1, {"split": output}, {}),
    )
    return run, definition


def test_unsupervised_spectral_split_has_no_invented_target_or_group_claim():
    run, definition = split_run(supervised=False, columns=100)
    report = text(validation_summary(run, definition))
    assert "No whole-group holdout recorded" in report
    assert "Dataset, target and group selection: Not retained" in report
    assert "Development population" in report and "Test population" in report


def test_supervised_group_holdout_preserves_counts_seed_and_reopens_identically():
    run, definition = split_run(grouped=True)
    first = validation_summary(run, definition)
    report = text(first)
    assert "2 development groups; 1 test groups" in report
    assert "Test groups: C" in report
    assert "Development population (split): 8 rows" in report
    assert "Test population (split): 4 rows" in report
    assert "Split seed (split): 42" in report
    assert validation_summary(run, definition) == first


def test_non_spectral_tabular_split_does_not_invent_axis_units():
    run, definition = split_run(columns=2)
    report = text(validation_summary(run, definition))
    assert "Split method (split): random" in report
    assert "wavelength" not in report and "cm-1" not in report


def test_missing_retained_output_refuses_partition_claim():
    run, definition = split_run(grouped=True)
    for item in run.evidence_completeness["outputs"]["split"].values():
        item["state"] = "missing"
    report = text(validation_summary(run, definition))
    assert "Recorded whole-group split" not in report
    assert "Missing evidence is not a count of zero" in report


def test_changed_split_bytes_are_not_presented_as_verified():
    run, definition = split_run(grouped=True)
    for item in run.evidence_completeness["outputs"]["split"].values():
        if item.get("sha256"):
            item["sha256"] = "0" * 64
    report = text(validation_summary(run, definition))
    assert "Recorded whole-group split" not in report
    assert "could not be verified" in report


def test_split_positions_are_not_original_file_row_identity():
    # Model input could have been filtered/reordered from original rows [9, 4, 2, ...].
    # Split records bind input positions; the summary must not label them source rows.
    run, definition = split_run(columns=2, row_order=[9, 4, 2, 1, 8, 3])
    run.params_snapshot = []  # malformed legacy JSON must not substitute current defaults
    report = text(validation_summary(run, definition))
    assert "split-input row positions (1-based):" in report
    assert "source row numbers" not in report
    assert "defaults were not reconstructed" in report


@pytest.mark.parametrize("repeats", [1, 2])
def test_exact_nested_evidence_report_retains_metrics_figures_and_repeat_denominators(repeats):
    from spectra_sherpa.app.services.dag.nodes.selection.nested_cv_node import _nested_cv_dispatch

    rng = np.random.default_rng(9)
    x = rng.normal(size=(24, 5))
    y = x[:, 0] + rng.normal(size=24) * 0.1
    outputs, _ = _nested_cv_dispatch(
        x,
        y,
        producer_node_id="cv",
        selection_method="none",
        n_components=2,
        cv_folds=3,
        vip_threshold=1.0,
        coef_threshold=0.0,
        random_seed=42,
        n_repeats=repeats,
    )
    run = SimpleNamespace(
        id=19,
        user_id=1,
        status="completed",
        diagnostics={},
        source_metadata={},
        params_snapshot={"cv": {"n_repeats": repeats}},
        evidence_completeness=retention.retain_run_outputs(1, {"cv": outputs}, {}),
    )
    definition = {"nodes": [{"node_id": "cv", "node_type": "selection.nested_cv"}], "edges": []}
    default = validation_summary(run, definition)
    assert default["figures"] == []
    assert "Excluded by default" in text(default)
    summary = validation_summary(run, definition, include_row_level_plots=True)
    assert len(summary["figures"]) == repeats
    assert len(summary["regression_results"]) == repeats
    assert all(result["metrics"]["n_samples"] == 24 for result in summary["regression_results"])
    assert all(result["role"] == "cross_validation" for result in summary["regression_results"])
    for figure in summary["figures"]:
        assert figure["visible_rows"] == figure["total_rows"] == 24
        assert len(figure["residual"]) == 24
        np.testing.assert_allclose(figure["residual"], np.asarray(figure["predicted"]) - figure["observed"])
    rendered = text(summary)
    assert "not independent specimens" in rendered
    if repeats > 1:
        assert "24 original rows" in rendered and "not pooled" in rendered
    assert validation_summary(run, definition, include_row_level_plots=True) == summary


def test_plot_units_follow_only_saved_upstream_target_selection():
    from spectra_sherpa.app.services.run_validation_summary import _retained_target_units

    run = SimpleNamespace(
        source_metadata={
            "data_selection_revisions": [
                {
                    "source_node_id": "loader",
                    "revision_number": 2,
                    "selection": {"target_authority": {"units": "mg/L"}},
                },
                {
                    "source_node_id": "unrelated",
                    "revision_number": 9,
                    "selection": {"target_authority": {"units": "g/L"}},
                },
            ]
        }
    )
    definition = {"edges": [{"from_node": "loader", "to_node": "cv"}]}
    assert _retained_target_units(run, definition, "cv") == "mg/L"
    assert "unavailable" in _retained_target_units(run, {"edges": []}, "cv")


def test_calibration_statistics_use_complete_retained_comparison_not_preview(monkeypatch):
    observed = np.column_stack((np.arange(120), np.arange(120) * 10.0))
    predicted = observed + [0.5, -2.0]
    comparison = build_regression_comparison(
        observed, predicted, role="calibration", target_names=["Glucose (wt %)", "Water (wt %)"]
    )
    run = SimpleNamespace(
        id=22,
        user_id=1,
        status="completed",
        diagnostics={},
        source_metadata={},
        params_snapshot={},
        results_summary={"fit": {"comparison": {"data": comparison["data"][:4]}}},
        evidence_completeness=retention.retain_run_outputs(1, {"fit": {"calibration_comparison": comparison}}, {}),
    )
    definition = {"nodes": [{"node_id": "fit", "node_type": "model.pls_fit"}], "edges": []}

    def forbidden(*args, **kwargs):
        raise AssertionError("Reports must not compute regression statistics")

    monkeypatch.setattr("spectra_sherpa.app.services.dag.regression_comparison.metrics", forbidden)
    monkeypatch.setattr("spectra_sherpa.sdk.validate.metrics", forbidden)
    summary = validation_summary(run, definition)
    records = summary["regression_results"]
    assert len(records) == 2
    assert [r["target"] for r in records] == ["Glucose (wt %)", "Water (wt %)"]
    assert records[0]["metrics"]["n_samples"] == 120
    assert records[0]["metrics"]["rmse"] == pytest.approx(0.5)
    assert records[1]["metrics"]["bias"] == pytest.approx(-2)
    assert records[0]["reference_min"] == 0
    assert records[0]["reference_max"] == 119
    assert records[0]["reference_mean"] == pytest.approx(59.5)
    assert "observations" not in records[0]
    assert records[0]["role"] == "calibration"
    assert "sec" not in records[0]["metrics"]
    assert "Regression population calibration" in text(summary)
    assert "data" not in records[0]
    for item in run.evidence_completeness["outputs"]["fit"].values():
        item["sha256"] = "0" * 64
    assert validation_summary(run, definition)["regression_results"] == []


def test_legacy_comparison_requires_workflow_rerun():
    comparison = build_regression_comparison([1.0, 2.0, 3.0], [1.1, 2.1, 3.1], role="held_out_test")
    del comparison["statistics"]
    run = SimpleNamespace(
        id=23,
        user_id=1,
        status="completed",
        diagnostics={},
        source_metadata={},
        params_snapshot={},
        evidence_completeness=retention.retain_run_outputs(1, {"evaluate": {"comparison": comparison}}, {}),
    )
    summary = validation_summary(run, {"nodes": [], "edges": []})
    assert summary["regression_results"] == []
    assert "Rerun the workflow" in text(summary)


def test_source_units_are_grouped_from_retained_spectral_metadata():
    spectrum = {
        "type": "SherpaDataset",
        "data": [[1.0, 2.0]],
        "x_axis": {"title": "Wavelength", "units": "nm"},
        "metadata": {"is_spectra": True, "value_units_label": "Absorbance"},
    }
    run = SimpleNamespace(
        id=25,
        user_id=1,
        status="completed",
        diagnostics={},
        source_metadata={},
        params_snapshot={},
        evidence_completeness=retention.retain_run_outputs(
            1, {"source1": {"default": spectrum}, "source2": {"default": spectrum}}, {}
        ),
    )
    definition = {
        "nodes": [{"node_id": node, "node_type": "data.file_load"} for node in ("source1", "source2")],
        "edges": [],
    }
    summary = validation_summary(run, definition)
    axis_rows = [row for row in summary["rows"] if row["label"].startswith("Spectral axis")]
    assert len(axis_rows) == 1
    assert axis_rows[0]["value"] == "Wavelength; units: nm"
    assert "source1, source2" in axis_rows[0]["label"]
    assert "Absorbance" in text(summary)


def test_generic_axes_do_not_become_spectral_units():
    from spectra_sherpa.app.services.run_validation_summary import _source_unit_signature

    assert (
        _source_unit_signature({"type": "SherpaDataset", "x_axis": {"units": "s"}, "metadata": {"is_spectra": False}})
        is None
    )


def test_complete_training_and_test_target_lists_are_opt_in_and_not_preview_limited():
    outputs = {}
    for node, count, role in [("fit", 174, "calibration"), ("test", 57, "held_out_test")]:
        values = np.arange(count, dtype=float)
        outputs[node] = {"comparison": build_regression_comparison(values, values + 0.1, role=role)}
    run = SimpleNamespace(
        id=24,
        user_id=1,
        status="completed",
        diagnostics={},
        source_metadata={},
        params_snapshot={},
        evidence_completeness=retention.retain_run_outputs(1, outputs, {}),
    )
    definition = {"nodes": [], "edges": []}
    summary = validation_summary(run, definition)
    assert all("observations" not in record for record in summary["regression_results"])
    full = validation_summary(run, definition, include_row_level_plots=True)
    assert [len(record["observations"]) for record in full["regression_results"]] == [174, 57]
    assert [record["reference_mean"] for record in full["regression_results"]] == [86.5, 28.0]
    assert full["regression_results"][0]["observations"][-1]["reference"] == 173
