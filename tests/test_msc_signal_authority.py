"""MSC correction returns reference signal units, with explicit input authority."""

from __future__ import annotations

import asyncio
import copy
import json

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.nodes.preprocessing.msc_node import MSCNode, _apply_msc_state
from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode
from spectra_sherpa.app.services.model_application import _prepare_X_for_artifact


def data(units="absorbance"):
    return SherpaDataset(
        X=np.array([[1.0, 2.0, 4.0, 8.0], [1.2, 2.5, 4.7, 9.0], [2.1, 2.2, 5.9, 7.4], [0.5, 3.1, 3.5, 10.0]]),
        feature_axis=SpectralAxis(values=[900.0, 1000.0, 1100.0, 1200.0], units="nm", labels=["a", "b", "c", "d"]),
        units=units,
        domain=DomainContext(
            technique="NIR",
            data_quantity="absorbance" if units in ("absorbance", "ABS") else None,
            measurement_mode="transmission",
        ),
    )


@pytest.mark.parametrize("units", ["absorbance", "counts", None])
def test_reference_units_survive_live_json_and_generated_execution(units):
    source = data(units)
    node = MSCNode("msc", {"reference_method": "mean"})
    state = json.loads(json.dumps(node.fit_fitted_state(source), allow_nan=False))
    applied = node.apply_fitted_state(source, state)
    assert applied.units == units
    reference = np.mean(source.X, axis=0)
    design = np.column_stack([reference, np.ones(4)])
    slope, intercept = np.linalg.lstsq(design, source.X.T, rcond=None)[0]
    np.testing.assert_allclose(applied.X, ((source.X.T - intercept) / slope).T)
    scope = {"source": source, "results": {}}
    exec("\n".join(node.generate_python({"default": "source"}, indent="")), scope)
    assert scope["results"]["msc"].units == units
    np.testing.assert_allclose(scope["results"]["msc"].X, applied.X)
    live = asyncio.run(node.execute(default=source))
    assert live.outputs["default"].units == units


@pytest.mark.parametrize("change", ["units", "missing_units", "quantity", "mode", "features"])
def test_incompatible_application_refuses(change):
    reference = data()
    application = data()
    if change == "units":
        application.units = "%T"
    elif change == "missing_units":
        application.units = None
    elif change == "quantity":
        application.domain = application.domain.model_copy(update={"data_quantity": "transmittance"})
    elif change == "mode":
        application.domain = application.domain.model_copy(update={"measurement_mode": "reflectance"})
    else:
        axis = application.feature_axis
        axis.labels = ["d", "c", "b", "a"]
        application.feature_axis = axis
    node = MSCNode("msc", {})
    with pytest.raises(ValueError, match="authority"):
        node.apply_fitted_state(application, node.fit_fitted_state(reference))


def test_equivalent_spelling_and_unknown_authority():
    node = MSCNode("msc", {})
    state = node.fit_fitted_state(data("ABS"))
    assert node.apply_fitted_state(data("absorbance"), state).units == "absorbance"
    unknown = node.fit_fitted_state(data(None))
    with pytest.raises(ValueError, match="authority"):
        node.apply_fitted_state(data("absorbance"), unknown)


def test_old_state_duplicate_axis_and_raw_bypass_refuse():
    source = data()
    node = MSCNode("msc", {})
    state = node.fit_fitted_state(source)
    old = {key: value for key, value in state.items() if key != "input_identity"}
    old["serializer"] = "spectra.msc-reference-json.v1"
    with pytest.raises(ValueError, match="serializer"):
        node.apply_fitted_state(source, old)
    forged = copy.deepcopy(state)
    forged["feature_axis_values"][0] += 1
    with pytest.raises(ValueError, match="contradicts"):
        node.apply_fitted_state(source, forged)
    with pytest.raises(ValueError, match="authority"):
        _apply_msc_state(source.X, state, feature_axis_values=source.feature_axis.values, feature_axis_units="nm")


def test_saved_chain_uses_current_signal_authority_before_and_after_msc():
    source = data()
    # Autoscale before MSC ensures replay cannot pass original raw units.
    first = ScaleNode("scale", {"method": "autoscale", "center": True})
    preprocessed = first.apply_fitted_state(source, first.fit_fitted_state(source))
    msc = MSCNode("msc", {"reference_method": "first"})
    corrected = msc.apply_fitted_state(preprocessed, msc.fit_fitted_state(preprocessed))
    centered = ScaleNode("center", {"method": "mean_center", "center": True})
    final = centered.apply_fitted_state(corrected, centered.fit_fitted_state(corrected))
    chain = [{"op_id": step.op_id, "parameters": dict(step.parameters)} for step in final.provenance]
    replay, _, _, _ = _prepare_X_for_artifact(
        source.X, None, {"preprocessing_chain": chain}, scope="all", source_dataset=source
    )
    np.testing.assert_allclose(replay, final.X, atol=1e-12)
    assert source.units == "absorbance"


def test_msc_scale_pls_predictions_survive_json_and_saved_replay():
    from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import FittedPLSV2Node

    source = data()
    source.target = np.array([10.0, 13.0, 9.0, 15.0])
    msc = MSCNode("msc", {})
    corrected = msc.apply_fitted_state(source, json.loads(json.dumps(msc.fit_fitted_state(source))))
    scale = ScaleNode("scale", {"method": "autoscale"})
    transformed = scale.apply_fitted_state(corrected, json.loads(json.dumps(scale.fit_fitted_state(corrected))))
    pls = FittedPLSV2Node("pls", {"n_components": 2, "scale": False})
    state = json.loads(json.dumps(pls.fit_fitted_state(transformed, None)))
    expected = pls.apply_fitted_state(transformed, state)
    chain = [{"op_id": step.op_id, "parameters": dict(step.parameters)} for step in transformed.provenance]
    replay, _, _, _ = _prepare_X_for_artifact(
        source.X, None, {"preprocessing_chain": chain}, scope="all", source_dataset=source
    )
    carrier = transformed.copy()
    carrier._X = replay
    np.testing.assert_allclose(pls.apply_fitted_state(carrier, state), expected, rtol=1e-12, atol=1e-12)
