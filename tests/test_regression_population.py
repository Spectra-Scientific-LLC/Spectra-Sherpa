"""Missing reference admission preserves the scientific population, including export."""

from __future__ import annotations

import json

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis, TargetContext
from spectra_sherpa.app.services.dag.io_contracts import clean_regression_target_with_population
from spectra_sherpa.app.services.dag.nodes.modeling.regression_nodes import (
    PCRNode,
    _linear_regression_execute,
    _svr_execute,
)
from spectra_sherpa.app.services.model_store import ModelStore


def fixture(*, missing=True, spectral=True):
    rng = np.random.default_rng(1655)
    x = rng.normal(size=(12, 4))
    y = 2 * x[:, 0] - x[:, 1]
    if missing:
        y[[1, 8]] = np.nan
    return SherpaDataset(
        X=x,
        sample_axis=SampleAxis(labels=[f"specimen-{i}" for i in range(12)]),
        feature_axis=SpectralAxis(values=[800, 900, 1000, 1100], units="nm") if spectral else None,
        target=y,
        target_context=TargetContext(target_type="continuous", target_names=["CN"], selected_target="CN"),
    )


def execute(kind, ds):
    if kind == "pcr":
        return PCRNode("pcr", {"n_components": 2, "scale": True})._execute_sync(ds).outputs
    if kind == "ols":
        return _linear_regression_execute(ds, None, node_id="ols", parameters={"fit_intercept": True})
    node_params = {
        "kernel": "linear",
        "C": 1.0,
        "epsilon": 0.1,
        "gamma": "scale",
        "degree": 3,
        "coef0": 0.0,
        "scale": True,
        "target_index": 1,
    }
    return _svr_execute(ds, None, node_id="svr", parameters=node_params)


@pytest.mark.parametrize("kind", ["pcr", "ols", "svr"])
@pytest.mark.parametrize("missing,spectral", [(True, True), (False, True), (True, False)])
def test_population_binds_actual_predictions_and_survives_model_store(kind, missing, spectral, tmp_path):
    ds = fixture(missing=missing, spectral=spectral)
    outputs = execute(kind, ds)
    receipt = outputs["population"]
    assert receipt["source_scientific_digest"] == ds.scientific_digest
    assert receipt["response_names"] == ["CN"]
    kept = [i for i in range(12) if not missing or i not in (1, 8)]
    assert receipt["input_count"] == 12
    assert receipt["admitted_count"] == len(kept) == len(outputs["y_pred"])
    assert receipt["excluded_count"] == 12 - len(kept)
    assert receipt["admitted_rows"] == kept
    assert receipt["sample_labels"] == ds.sample_axis.labels
    assert receipt["selected_target"] == "CN"
    assert receipt["excluded_rows"] == (
        [{"row": i, "reason": "missing_reference", "target_columns": [0]} for i in (1, 8)] if missing else []
    )
    assert ds.n_samples == 12  # no in-place cohort mutation
    artifact = outputs["_model_artifact"]
    assert artifact["metadata"]["population"] == receipt
    store = ModelStore(tmp_path)
    store.save("population-test", artifact["metadata"], artifact["arrays"])
    manifest, _ = store.load("population-test")
    assert json.loads(json.dumps(manifest["population"], allow_nan=False)) == receipt


def test_pcr_scores_export_and_fitted_reference_count():
    ds = fixture()
    node = PCRNode("pcr", {"n_components": 2, "scale": True})
    live = node._execute_sync(ds)
    expected = [f"specimen-{i}" for i in range(12) if i not in (1, 8)]
    assert live.outputs["scores"].sample_axis.labels == expected
    assert live.diagnostics["population"] == live.outputs["population"]
    assert node.fit_fitted_state(ds, None)["reference_samples"] == 10
    scope = {"dataset": ds, "results": {}}
    exec("\n".join(node.generate_python({"X": "dataset"}, indent="")), scope)
    assert scope["results"]["pcr"]["population"] == live.outputs["population"]
    assert node.metadata.resolved_execution_contract().payload["sample_effect"] == "filters_samples"


@pytest.mark.parametrize(
    "case,match",
    [
        ("all_missing", "No complete target"),
        ("infinite_y", "infinity"),
        ("bad_x", "predictors contain non-finite"),
        ("masked", "materialize the active cohort"),
    ],
)
def test_invalid_population_refuses_explicitly(case, match):
    ds = fixture()
    if case == "all_missing":
        ds.target[:] = np.nan
    elif case == "infinite_y":
        ds.target[0] = np.inf
    elif case == "bad_x":
        ds.X[1, 0] = np.nan  # invalid even in a row with no reference
    else:
        axis = ds.sample_axis
        axis.include_mask = np.array([False] + [True] * 11)
        ds.sample_axis = axis
    with pytest.raises(ValueError, match=match):
        execute("pcr", ds)


def test_other_missing_properties_do_not_drop_measured_selected_target():
    ds = fixture(missing=False)
    axis = ds.sample_axis
    axis.sample_table = {"unselected_property": [None] * 12}
    ds.sample_axis = axis
    _, _, population = clean_regression_target_with_population(ds, ds.target, model_label="PCR")
    assert population["admitted_count"] == 12
    assert population["excluded_count"] == 0


def test_separate_response_values_change_receipt_but_not_original_source():
    ds = fixture(missing=False)
    node = PCRNode("pcr", {"n_components": 2, "scale": True})
    first = node._execute_sync(ds, ds.target.copy()).outputs["population"]
    second = node._execute_sync(ds, ds.target + 1).outputs["population"]
    assert first["source_scientific_digest"] == second["source_scientific_digest"] == ds.scientific_digest
    assert first["response_sha256"] != second["response_sha256"]
    assert first["response_names"] == ["Target 1"]  # anonymous explicit y cannot inherit CN


def test_native_mat_join_normalizes_missing_properties_without_relaxing_infinity(monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace

    from spectra_sherpa.app.lib.eigenvector import load_eigenvector_mat_pair_as_sherpa

    spectra = fixture(missing=False)
    properties = SherpaDataset(X=np.ones((12, 7)), sample_axis=spectra.sample_axis)
    properties.X[0, 2] = np.nan
    monkeypatch.setattr(
        "spectra_sherpa.io.ingest",
        lambda path: SimpleNamespace(
            assets=[
                SimpleNamespace(asset_id="spec", dataset=spectra),
                SimpleNamespace(asset_id="prop", dataset=properties),
            ]
        ),
    )
    params = dict(
        spec_key="spec",
        prop_key="prop",
        prop_names=["a", "b", "c", "d", "e", "f", "g"],
        x_title="Wavelength",
        x_units="nm",
        technique="NIR",
    )
    joined = load_eigenvector_mat_pair_as_sherpa(Path("synthetic.mat"), **params)
    assert joined.sample_axis.sample_table["c"][0] is None
    assert np.isnan(joined.target[0, 2])
    assert len(joined.scientific_digest) == 64
    properties.X[0, 2] = np.inf
    with pytest.raises(ValueError, match="infinite"):
        load_eigenvector_mat_pair_as_sherpa(Path("synthetic.mat"), **params)


@pytest.mark.parametrize("kind", ["pcr", "ols", "svr"])
def test_embedded_selection_retains_original_response_column(kind):
    ds = fixture()
    ds.target = np.column_stack([np.ones(12), ds.target])
    ds.target_context = TargetContext(target_names=["A", "B"], selected_target="B", target_type="continuous")
    receipt = execute(kind, ds)["population"]
    assert receipt["response_names"] == ["B"]
    assert receipt["response_input_columns"] == [1]
    assert receipt["excluded_rows"][0]["target_columns"] == [0]  # projected bound matrix


@pytest.mark.parametrize("kind", ["pcr", "ols", "svr"])
def test_external_response_uses_data_identity_not_its_own_embedded_target(kind):
    ds = fixture(missing=False)
    response = SherpaDataset(
        X=ds.target.reshape(-1, 1),
        sample_axis=ds.sample_axis,
        feature_axis=SpectralAxis(labels=["Density"]),
        units="g/mL",
        target=ds.target + 10,
        target_context=TargetContext(target_names=["CN"], target_units="cetane"),
    )
    if kind == "pcr":
        outputs = PCRNode("pcr", {"n_components": 2, "scale": True})._execute_sync(ds, response).outputs
    elif kind == "ols":
        outputs = _linear_regression_execute(ds, response, node_id="ols", parameters={"fit_intercept": True})
    else:
        from spectra_sherpa.app.services.dag.nodes.modeling.regression_nodes import SVRNode

        outputs = _svr_execute(ds, response, node_id="svr", parameters=SVRNode("svr", {})._resolve_params())
    assert outputs["population"]["response_names"] == ["Density"]
    assert outputs["population"]["response_units"] == "g/mL"
    assert outputs["_model_artifact"]["metadata"]["target_names"] == ["Density"]
