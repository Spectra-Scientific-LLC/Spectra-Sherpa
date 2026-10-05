"""Independent numerical checks for qualified claims about global screening."""

import asyncio
import json

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.nodes.modeling.apply_fitted_pls_node import ApplyFittedPLSV2Node
from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import (
    FittedPLSV2Node,
    make_fitted_pls_state_envelope,
)
from spectra_sherpa.app.services.dag.nodes.modeling.pls_applicability import (
    apply_screening,
    fit_screening,
    validate_screening,
)
from spectra_sherpa.app.services.dag.nodes.modeling.pls_core import fit_simpls


def fit(scale=False):
    rng = np.random.default_rng(31)
    X = rng.normal(size=(40, 6))
    y = X @ np.array([1.0, 2.0, 0.0, 0.0, 0.0, 0.0]) + rng.normal(0, 0.03, 40)
    model = fit_simpls(X, y[:, None], n_components=2, scale=scale)
    return X, y, model, fit_screening(X, model)


def test_independent_projection_covariance_residual_and_quantiles():
    X, _, model, state = fit()
    Z = (X - X.mean(axis=0)) / model.x_scale
    T = Z @ model.x_weights
    E = Z - T @ model.x_loadings.T
    inverse = np.linalg.inv(np.cov(T, rowvar=False, ddof=1))
    T2 = np.array([row @ inverse @ row for row in T - T.mean(0)])
    Q = np.array([row @ row for row in E])
    result = apply_screening(X, model.x_offset, state)
    np.testing.assert_allclose([row["t2"] for row in result["rows"]], T2)
    np.testing.assert_allclose([row["q"] for row in result["rows"]], Q)
    assert state["t2_limit"] == pytest.approx(np.quantile(T2, 0.95, method="linear"))
    assert state["q_limit"] == pytest.approx(np.quantile(Q, 0.95, method="linear"))
    assert all(row["applicability_status"] == "unqualified" for row in result["rows"])


def test_high_leverage_and_orthogonal_unfamiliar_input():
    X, _, model, state = fit()
    # Projection-null direction changes spectral residual without moving scores.
    _, _, vh = np.linalg.svd(model.x_weights.T, full_matrices=True)
    new = np.stack([model.x_offset + 100 * model.x_weights[:, 0], model.x_offset + 100 * vh[-1]])
    result = apply_screening(new, model.x_offset, state)
    assert result["rows"][0]["outside_t2"]
    assert result["rows"][1]["outside_q"]
    assert result["rows"][1]["t2"] < 1e-20


def test_cluster_gap_is_never_claimed_in_domain():
    x = np.r_[np.linspace(-11, -9, 20), np.linspace(9, 11, 20)]
    X = np.column_stack([x, x**2])
    model = fit_simpls(X, x[:, None], n_components=1, scale=False)
    result = apply_screening(X.mean(0)[None, :], model.x_offset, fit_screening(X, model))
    assert result["rows"][0]["screening_status"] == "within_global_screen"
    assert result["rows"][0]["applicability_status"] == "unqualified"
    assert result["neighborhood_support"] == "unavailable_aggregate_state"


def test_minimal_and_full_feature_rank_have_unavailable_diagnostics():
    X = np.array([[0.0], [1.0]])
    model = fit_simpls(X, X, n_components=1, scale=False)
    state = fit_screening(X, model)
    assert state["t2_unavailable_reason"] == "insufficient_reference_degrees_of_freedom"
    assert state["q_unavailable_reason"] == "no_residual_feature_dimensions"
    assert apply_screening(X, model.x_offset, state)["rows"][0]["screening_status"] == "unavailable"


def test_fixed_zero_q_tolerance_detects_orthogonal_change():
    x = np.linspace(-2, 2, 30)
    X = np.column_stack([x, 2 * x, 3 * x])
    model = fit_simpls(X, x[:, None], n_components=1, scale=False)
    state = fit_screening(X, model)
    assert state["q_limit"] == state["q_numerical_tolerance"]
    shifted = X[:1] + np.array([0.0, 1.0, 0.0])
    result = apply_screening(shifted, model.x_offset, state)
    assert result["q_limit"] == state["q_limit"]
    assert result["rows"][0]["outside_q"]


@pytest.mark.parametrize("scale", [False, True])
def test_units_rescale_statistics_correctly(scale):
    X, y, model, state = fit(scale)
    changed = fit_simpls(X * 1000, y[:, None], n_components=2, scale=scale)
    result = fit_screening(X * 1000, changed)
    assert result["t2_limit"] == pytest.approx(state["t2_limit"])
    assert result["q_limit"] == pytest.approx(state["q_limit"] * (1 if scale else 1e6))


def test_live_json_generated_and_prediction_identity():
    X, y, _, _ = fit()
    dataset = SherpaDataset(X=X, target=y, units="absorbance")
    node = FittedPLSV2Node("fit", {"n_components": 2, "scale": False})
    state = node.fit_fitted_state(dataset, None)
    envelope = json.loads(json.dumps(make_fitted_pls_state_envelope(state), allow_nan=False))
    apply = ApplyFittedPLSV2Node("apply", {})
    result = asyncio.run(apply.run(default=dataset, fitted_state=envelope))
    screening = result.outputs["applicability"]
    assert screening["prediction_identity"] == result.outputs["prediction_identity"]
    assert screening["q_units"] == "(absorbance)^2"
    scope = {"source": dataset, "state": envelope, "results": {}}
    exec("\n".join(apply.generate_python({"default": "source", "fitted_state": "state"}, indent="")), scope)
    assert scope["results"]["apply"]["applicability"] == screening


def test_malformed_state_refuses():
    _, _, _, state = fit()
    state["q_limit"] *= 2
    with pytest.raises(ValueError, match="Q authority"):
        validate_screening(state, features=6, components=2, samples=40)


def test_singular_score_covariance_is_explicitly_unavailable():
    from dataclasses import replace

    X, _, model, _ = fit()
    weights = np.repeat(model.x_weights[:, :1], 2, axis=1)
    singular = replace(model, x_weights=weights)
    state = fit_screening(X, singular)
    assert state["t2_unavailable_reason"] == "rank_deficient_score_covariance"
    assert state["score_covariance_inverse"] is None
    assert state["q_unavailable_reason"] == "rank_deficient_score_covariance"
    assert all(row["outside_t2"] is None for row in apply_screening(X, model.x_offset, state)["rows"])


def test_old_point_only_state_cannot_invent_reference_diagnostics():
    X, y, _, _ = fit()
    node = FittedPLSV2Node("fit", {"n_components": 2})
    state = node.fit_fitted_state(SherpaDataset(X=X, target=y), None)
    state.pop("diagnostic_state")
    state["serializer"] = "spectra.sherpa-simpls-regression-json/8"
    with pytest.raises(ValueError, match="closed serializer"):
        node.validate_fitted_state(state)


def test_minimal_reference_cannot_set_q_limit_with_extra_features():
    X = np.array([[1.0, 2.0, 3.0], [2.0, 4.0, 5.0]])
    model = fit_simpls(X, np.array([[1.0], [2.0]]), n_components=1, scale=False)
    state = fit_screening(X, model)
    assert state["q_limit"] is None
    assert state["q_unavailable_reason"] == "insufficient_reference_degrees_of_freedom"
    assert all(row["outside_q"] is None for row in apply_screening(X, model.x_offset, state)["rows"])
