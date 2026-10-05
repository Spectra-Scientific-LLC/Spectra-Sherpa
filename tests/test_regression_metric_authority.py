"""Metrics preserve units and distinguish represented variation from constants."""

from __future__ import annotations

import json

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
from spectra_sherpa.app.services.dag.nodes.modeling.regression_nodes import PCRNode, _linear_regression_execute
from spectra_sherpa.sdk.validate import RegressionMetricAccumulator, metrics


@pytest.mark.parametrize("scale,offset", [(1.0, 0.0), (1e-12, 0.0), (1e6, 0.0), (1.0, 1e9)])
def test_batch_and_pooled_metrics_preserve_resolvable_variation(scale, offset):
    observed = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]) * scale + offset
    predicted = np.array([1.25, 1.75, 3.5, 3.5, 4.75, 6.25]) * scale + offset
    baseline = metrics([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], [1.25, 1.75, 3.5, 3.5, 4.75, 6.25])
    batch = metrics(observed, predicted)
    accumulator = RegressionMetricAccumulator()
    accumulator.add(observed[:2], predicted[:2])
    accumulator.add(observed[2:5], predicted[2:5])
    accumulator.add(observed[5:], predicted[5:])
    pooled = accumulator.metrics()
    for result in (batch, pooled):
        assert result.r2 == pytest.approx(baseline.r2, rel=1e-8)
        assert result.slope == pytest.approx(baseline.slope, rel=1e-8)
        assert result.rmse == pytest.approx(baseline.rmse * abs(scale), rel=1e-8, abs=0.0)


@pytest.mark.parametrize("observed", [[3.0], [3.0, 3.0, 3.0], [1e-12, 1e-12]])
def test_true_constant_and_singleton_remain_undefined(observed):
    batch = metrics(observed, observed)
    accumulator = RegressionMetricAccumulator()
    for value in observed:
        accumulator.add([value], [value])
    for result in (batch, accumulator.metrics()):
        assert result.r2 is None and result.slope is None and result.intercept is None
        assert result.rmse == 0.0


def run(kind, dataset):
    if kind == "pcr":
        result = PCRNode("pcr", {"n_components": 2, "scale": True})._execute_sync(dataset)
        return result.outputs, result.diagnostics
    outputs = _linear_regression_execute(dataset, None, node_id="ols", parameters={"fit_intercept": True})
    return outputs, {}


@pytest.mark.parametrize("kind", ["pcr", "ols"])
def test_no_cross_response_scalar_error_in_any_summary_or_saved_artifact(kind, tmp_path):
    from spectra_sherpa.app.services.model_store import ModelStore

    rng = np.random.default_rng(1655)
    x = rng.normal(size=(32, 5))
    y = np.column_stack([50 + x[:, 0] + 0.2 * rng.normal(size=32), 0.8 + 0.02 * x[:, 1] + 0.001 * rng.normal(size=32)])
    ds = SherpaDataset(X=x, target=y, target_context=TargetContext(target_names=["CN", "Density"]))
    first, diagnostics = run(kind, ds)
    converted = ds.copy()
    converted.target = y * np.array([1.0, 1000.0])
    second, _ = run(kind, converted)
    a = first["_model_artifact"]["metadata"]["metrics"]["per_target"]
    b = second["_model_artifact"]["metadata"]["metrics"]["per_target"]
    assert a[0]["rmse_cal"] == pytest.approx(b[0]["rmse_cal"], rel=1e-10)
    assert b[1]["rmse_cal"] == pytest.approx(1000 * a[1]["rmse_cal"], rel=1e-10)
    assert a[0]["r2_cal"] == pytest.approx(b[0]["r2_cal"], rel=1e-10)
    metadata = first["scores"].meta if kind == "pcr" else first["metadata"]
    for record in (
        first,
        diagnostics,
        metadata,
        metadata["quality_summary"],
        first["_model_artifact"]["metadata"]["metrics"],
    ):
        assert not {"rmse", "rmse_cal", "r2", "r2_cal", "score"}.intersection(record)
    store = ModelStore(tmp_path)
    store.save("metrics", first["_model_artifact"]["metadata"], first["_model_artifact"]["arrays"])
    manifest, _ = store.load("metrics")
    assert "rmse_cal" not in manifest["metrics"]
    assert json.loads(json.dumps(manifest["metrics"]["per_target"], allow_nan=False)) == a


@pytest.mark.parametrize("kind", ["pcr", "ols"])
def test_producers_do_not_report_perfect_r2_for_constant_response(kind):
    x = np.random.default_rng(3).normal(size=(12, 4))
    ds = SherpaDataset(X=x, target=np.ones(12), target_context=TargetContext(target_names=["constant"]))
    outputs, _ = run(kind, ds)
    assert outputs["_model_artifact"]["metadata"]["metrics"]["r2_cal"] is None


@pytest.mark.parametrize("scale", [1e-200, 1e200])
def test_extreme_representable_units_keep_error_and_r2(scale):
    observed = np.array([1.0, 2.0, 3.0, 4.0]) * scale
    predicted = np.array([1.1, 2.1, 3.1, 4.1]) * scale
    accumulator = RegressionMetricAccumulator()
    accumulator.add(observed[:2], predicted[:2])
    accumulator.add(observed[2:], predicted[2:])
    for result in (metrics(observed, predicted), accumulator.metrics()):
        assert result.r2 == pytest.approx(0.992)
        assert result.rmse == pytest.approx(0.1 * scale, rel=1e-12, abs=0.0)
        assert result.slope == pytest.approx(1.0)
        assert result.intercept == pytest.approx(0.1 * scale, rel=1e-12, abs=0.0)
        assert np.isfinite(result.sep)


def test_sep_retains_variation_around_large_prediction_bias():
    observed = np.array([1.0, 2.0, 3.0, 4.0])
    predicted = observed + 1e8 + np.array([1.0, -1.0, 1.0, -1.0])
    accumulator = RegressionMetricAccumulator()
    for y, pred in zip(observed, predicted, strict=True):
        accumulator.add([y], [pred])
    expected = np.std(predicted - observed, ddof=1)
    for result in (metrics(observed, predicted), accumulator.metrics()):
        assert result.sep == pytest.approx(expected, rel=1e-8)


@pytest.mark.parametrize("offset", [1e12, 1e16])
def test_prediction_and_residual_origins_preserve_small_variation(offset):
    observed = np.array([0.0, 2.0, 4.0, 6.0])
    predicted = observed + offset + np.array([2.0, -2.0, 2.0, -2.0])
    residual = predicted - observed
    centered_residual = residual - residual[0]
    expected_sep = np.std(centered_residual, ddof=1)
    centered_prediction = predicted - predicted[0]
    centered_prediction -= centered_prediction.mean()
    centered_observed = observed - observed.mean()
    expected_slope = np.dot(centered_observed, centered_prediction) / np.dot(centered_observed, centered_observed)
    accumulator = RegressionMetricAccumulator()
    for y, pred in zip(observed, predicted, strict=True):
        accumulator.add([y], [pred])
    for result in (metrics(observed, predicted), accumulator.metrics()):
        assert result.sep == pytest.approx(expected_sep, rel=1e-12)
        assert result.slope == pytest.approx(expected_slope, rel=1e-12)


@pytest.mark.parametrize("legacy", [True, False])
def test_historical_model_presentation_does_not_rewrite_original_export(tmp_path, legacy):
    import io
    import zipfile

    from spectra_sherpa.app.api.v1.routes.models import _decode_metrics
    from spectra_sherpa.app.services.model_store import ModelStore, _zip_artifact_dir
    from spectra_sherpa.app.services.regression_metric_presentation import regression_metric_presentation

    metric_record = {
        "per_target": [{"target_name": "CN", "rmse_cal": 2.0}, {"target_name": "Density", "rmse_cal": 0.01}]
    }
    if legacy:
        metric_record["rmse_cal"] = 1.4
        metric_record["quality_summary"] = {"latest_rmse": 1.4, "latest_r2": 0.9}
    else:
        metric_record["metric_summary_scope"] = "per_response_only"
    store = ModelStore(tmp_path)
    store.save(
        "historical", {"model_type": "pcr", "n_targets": 2, "metrics": metric_record}, {"coef": np.zeros((2, 3))}
    )
    directory = store.models_dir / "historical"
    original = (directory / "manifest.json").read_bytes()
    manifest, _ = store.load("historical")
    projection = regression_metric_presentation(manifest)
    assert "rmse_cal" not in projection["metrics"]
    assert projection["metrics"]["per_target"] == metric_record["per_target"]
    assert _decode_metrics(json.dumps(metric_record))["metric_summary_scope"] == (
        "legacy_multiresponse_aggregate_unqualified" if legacy else "per_response_only"
    )
    if legacy:
        assert projection["metrics"]["legacy_aggregate_evidence"]["rmse_cal"] == 1.4
        assert "latest_rmse" not in projection["metrics"]["quality_summary"]
        assert "latest_r2" not in projection["metrics"]["quality_summary"]
    with zipfile.ZipFile(io.BytesIO(_zip_artifact_dir(directory))) as archive:
        assert archive.read("manifest.json") == original
    assert (directory / "manifest.json").read_bytes() == original
