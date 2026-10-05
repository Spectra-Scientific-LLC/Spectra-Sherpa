"""Input compatibility must precede fitted arithmetic in live and replay paths."""

import asyncio
import json

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import FittedPLSV2Node
from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode


def data(spectral=True):
    rng = np.random.default_rng(491)
    X = rng.normal(size=(20, 5))
    axis = SpectralAxis(values=np.arange(5.0) + 1000, units="nm") if spectral else FeatureAxis(labels=list("abcde"))
    return SherpaDataset(
        X=X, feature_axis=axis, units="absorbance" if spectral else "mg/L", target=X[:, 0] + 2 * X[:, 1]
    )


@pytest.mark.parametrize("spectral", [False, True])
@pytest.mark.parametrize("mode", ["reference", "state", "generated"])
def test_scale_refuses_permuted_features_before_arithmetic(spectral, mode):
    training = data(spectral)
    changed = training[:, ::-1]
    node = ScaleNode("scale", {"method": "autoscale"})
    state = json.loads(json.dumps(node.fit_fitted_state(training)))
    with pytest.raises(ValueError, match="fitted input authority: axis"):
        if mode == "state":
            node.apply_fitted_state(changed, state)
        elif mode == "reference":
            asyncio.run(node.run(default=changed, reference=training))
        else:
            namespace = {"training": training, "changed": changed, "results": {}}
            exec(
                "\n".join(node.generate_python({"default": "changed", "reference": "training"}, indent="")), namespace
            )  # noqa: S102


@pytest.mark.parametrize("operation", ["scale", "pls"])
@pytest.mark.parametrize(
    "field,value",
    [("units", "%T"), ("units", None), ("data_quantity", "transmittance"), ("measurement_mode", "transmission")],
)
def test_fitted_operations_refuse_changed_signal_authority(operation, field, value):
    training = data()
    node = ScaleNode("scale", {}) if operation == "scale" else FittedPLSV2Node("pls", {"n_components": 2})
    state = node.fit_fitted_state(training) if operation == "scale" else node.fit_fitted_state(training, None)
    application = training.copy()
    if field == "units":
        application.units = value
    else:
        setattr(application.domain, field, value)
    with pytest.raises(ValueError, match="fitted input authority"):
        node.apply_fitted_state(application, json.loads(json.dumps(state)))


def test_equivalent_spelling_is_not_a_physical_conversion():
    training = data()
    node = FittedPLSV2Node("pls", {"n_components": 2})
    state = node.fit_fitted_state(training, None)
    application = training.copy()
    application.units = "Abs"
    np.testing.assert_array_equal(node.apply_fitted_state(application, state), node.apply_fitted_state(training, state))
    application.units = "transmittance"
    with pytest.raises(ValueError, match="signal_units"):
        node.apply_fitted_state(application, state)


def test_unknown_authority_stays_positional_and_cannot_silently_be_qualified():
    anonymous = SherpaDataset(X=data().X)
    node = ScaleNode("scale", {})
    state = node.fit_fitted_state(anonymous)
    np.testing.assert_allclose(node.apply_fitted_state(anonymous, state).X, anonymous.X - anonymous.X.mean(axis=0))
    with pytest.raises(ValueError, match="fitted input authority"):
        node.apply_fitted_state(data(), state)


def test_saved_scale_replay_uses_source_authority_and_retains_missing_metadata_refusal():
    from spectra_sherpa.app.services.model_application import _prepare_X_for_artifact

    training = data()
    node = ScaleNode("scale", {"method": "autoscale"})
    state = node.fit_fitted_state(training)
    manifest = {"preprocessing_chain": [{"op_id": "preprocess.scale", "parameters": {"transform_state": state}}]}
    result, *_ = _prepare_X_for_artifact(training.X, None, manifest, scope="all", source_dataset=training)
    np.testing.assert_array_equal(result, node.apply_fitted_state(training, state).X)
    with pytest.raises(ValueError, match="fitted input authority"):
        _prepare_X_for_artifact(training.X, None, manifest, scope="all")
    with pytest.raises(ValueError, match="fitted input authority"):
        _prepare_X_for_artifact(training.X[:, ::-1], None, manifest, scope="all", source_dataset=training[:, ::-1])


@pytest.mark.parametrize("operation", ["msc", "derivative"])
def test_saved_preprocessing_chain_propagates_live_unit_effects(operation):
    from spectra_sherpa.app.services.dag.nodes.preprocessing.derivative_node import DerivativeNode
    from spectra_sherpa.app.services.dag.nodes.preprocessing.msc_node import MSCNode
    from spectra_sherpa.app.services.model_application import _prepare_X_for_artifact

    training = data()
    if operation == "msc":
        node = MSCNode("msc", {})
        transformed = node.apply_fitted_state(training, node.fit_fitted_state(training))
    else:
        node = DerivativeNode("derivative", {"method": "savitzky_golay", "size": 5, "order": 2, "deriv": "1"})
        transformed = asyncio.run(node.run(default=training)).outputs["default"]
    scale = ScaleNode("scale", {"method": "autoscale"})
    expected = scale.apply_fitted_state(transformed, scale.fit_fitted_state(transformed))
    # Provenance freezes nested state to mappings/tuples; replay must accept
    # that real persisted representation as well as JSON dictionaries.
    chain = [{"op_id": step.op_id, "parameters": dict(step.parameters)} for step in expected.provenance]
    actual, *_ = _prepare_X_for_artifact(
        training.X, None, {"preprocessing_chain": chain}, scope="all", source_dataset=training
    )
    np.testing.assert_allclose(actual, expected.X, rtol=1e-12, atol=1e-12)
    assert training.units == "absorbance"


def test_pareto_retains_square_root_units_through_chained_replay():
    from spectra_sherpa.app.services.model_application import _prepare_X_for_artifact

    training = data(spectral=False)
    pareto = ScaleNode("pareto", {"method": "pareto"})
    transformed = pareto.apply_fitted_state(training, pareto.fit_fitted_state(training))
    assert transformed.units == "sqrt(mg/L)"
    center = ScaleNode("center", {"method": "mean_center"})
    expected = center.apply_fitted_state(transformed, center.fit_fitted_state(transformed))
    chain = [{"op_id": step.op_id, "parameters": dict(step.parameters)} for step in expected.provenance]
    actual, *_ = _prepare_X_for_artifact(
        training.X, None, {"preprocessing_chain": chain}, scope="all", source_dataset=training
    )
    np.testing.assert_allclose(actual, expected.X, rtol=1e-12, atol=1e-12)
    assert training.units == "mg/L"
