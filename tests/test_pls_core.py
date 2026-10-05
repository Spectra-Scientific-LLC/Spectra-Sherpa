"""Scientific and performance qualification for the shared SIMPLS core."""

from __future__ import annotations

import numpy as np
import pytest
from sklearn.cross_decomposition import PLSRegression

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.modeling.pls_core import (
    ALGORITHM_ID,
    CITATION,
    apply_pls_affine_state,
    fit_simpls,
    fit_simpls_exact,
)
from tests.performance_contract import PerformanceCeiling

_PLS_CORE_COMPONENT_ID = "spectra_sherpa.app.services.dag.nodes.modeling.pls_core"


@pytest.mark.parametrize("scale", [False, True])
def test_pls1_predictions_match_nipals_reference(scale: bool) -> None:
    rng = np.random.default_rng(20260814)
    X = rng.normal(size=(80, 70))
    y = X @ rng.normal(size=70) + rng.normal(scale=0.05, size=80)
    held_out = rng.normal(size=(20, 70))

    actual = fit_simpls(X, y, n_components=10, scale=scale)
    reference = PLSRegression(n_components=10, scale=scale).fit(X, y)

    assert actual.algorithm_id == ALGORITHM_ID
    np.testing.assert_allclose(
        actual.predict(held_out), reference.predict(held_out).reshape(-1, 1), rtol=2e-11, atol=2e-11
    )


def test_pls2_fit_is_deterministic_and_predicts_every_response() -> None:
    rng = np.random.default_rng(431)
    X = rng.normal(size=(96, 45))
    Y = X @ rng.normal(size=(45, 4)) + rng.normal(scale=0.1, size=(96, 4))

    first = fit_simpls(X, Y, n_components=8, scale=True)
    second = fit_simpls(X, Y, n_components=8, scale=True)

    assert first.predict(X).shape == Y.shape
    for name in (
        "x_scores",
        "x_weights",
        "x_loadings",
        "y_loadings",
        "coefficients",
        "coefficient_path",
        "x_explained_variance",
        "y_explained_variance",
    ):
        np.testing.assert_array_equal(getattr(first, name), getattr(second, name))
    assert np.all(np.diff(np.cumsum(first.x_explained_variance)) >= -1e-14)
    assert np.all(np.diff(np.cumsum(first.y_explained_variance)) >= -1e-14)
    np.testing.assert_allclose(first.x_scores.T @ first.x_scores, np.eye(8), atol=2e-13)
    np.testing.assert_allclose(
        first.x_orthonormal_loadings.T @ first.x_orthonormal_loadings,
        np.eye(8),
        atol=2e-13,
    )


def test_raw_affine_state_matches_scaled_coordinate_model_for_every_component() -> None:
    rng = np.random.default_rng(183)
    X = 1.0e8 + rng.normal(scale=5.0e3, size=(72, 30))
    Y = -2.0e7 + X @ rng.normal(scale=2.0e-4, size=(30, 3))
    held_out = 1.0e8 + rng.normal(scale=5.0e3, size=(12, 30))
    fit = fit_simpls(X, Y, n_components=5, scale=True)

    scaled_held_out = (held_out - fit.x_offset) / fit.x_scale
    for component in range(1, 6):
        scaled_coefficients = (fit.coefficient_path[component - 1] * fit.x_scale[:, None]) / fit.y_scale[None, :]
        expected = scaled_held_out @ scaled_coefficients * fit.y_scale + fit.y_offset
        np.testing.assert_allclose(fit.predict(held_out, n_components=component), expected, rtol=2e-13)


def test_shared_affine_application_preserves_large_baseline_precision() -> None:
    rng = np.random.default_rng(20260817)
    X = 1.0e8 + rng.normal(scale=2.0e3, size=(48, 18))
    Y = -3.0e6 + X @ rng.normal(scale=3.0e-4, size=(18, 3))
    held_out = 1.0e8 + rng.normal(scale=2.0e3, size=(9, 18))
    fit = fit_simpls(X, Y, n_components=5, scale=True)

    applied = apply_pls_affine_state(
        held_out,
        coefficients=fit.coefficients,
        feature_offset=fit.x_offset,
        prediction_offset=fit.y_offset,
    )

    np.testing.assert_array_equal(applied, fit.predict(held_out))


def test_response_magnitude_does_not_change_x_rank_decisions() -> None:
    rng = np.random.default_rng(99)
    X = rng.normal(size=(50, 12))
    y = 1.0e18 * (X[:, 0] - 0.5 * X[:, 1])

    fit = fit_simpls(X, y, n_components=2)

    assert np.isfinite(fit.predict(X)).all()


def test_component_path_predictions_improve_the_calibration_fit() -> None:
    rng = np.random.default_rng(7)
    latent = rng.normal(size=(120, 6))
    X = latent @ rng.normal(size=(6, 90)) + rng.normal(scale=0.02, size=(120, 90))
    Y = latent @ rng.normal(size=(6, 3)) + rng.normal(scale=0.02, size=(120, 3))
    fit = fit_simpls(X, Y, n_components=6)

    errors = [float(np.sqrt(np.mean(np.square(Y - fit.predict(X, n_components=index))))) for index in range(1, 7)]

    assert all(next_error <= error + 1e-12 for error, next_error in zip(errors, errors[1:]))
    assert errors[-1] < errors[0] * 0.1


def test_explained_variance_matches_direct_component_reconstruction() -> None:
    rng = np.random.default_rng(33)
    X = rng.normal(size=(60, 25))
    Y = X @ rng.normal(size=(25, 3)) + rng.normal(scale=0.2, size=(60, 3))
    fit = fit_simpls(X, Y, n_components=5, scale=True)
    scaled_x = (X - fit.x_offset) / fit.x_scale
    scaled_y = (Y - fit.y_offset) / fit.y_scale

    expected_x = []
    expected_y = []
    previous_x = float(np.sum(np.square(scaled_x)))
    previous_y = float(np.sum(np.square(scaled_y)))
    x_total = previous_x
    y_total = previous_y
    for component in range(1, 6):
        x_residual = scaled_x - (fit.x_scores[:, :component] @ fit.x_loadings[:, :component].T)
        scaled_coefficients = (fit.coefficient_path[component - 1] * fit.x_scale[:, None]) / fit.y_scale[None, :]
        y_residual = scaled_y - scaled_x @ scaled_coefficients
        current_x = float(np.sum(np.square(x_residual)))
        current_y = float(np.sum(np.square(y_residual)))
        expected_x.append((previous_x - current_x) / x_total)
        expected_y.append((previous_y - current_y) / y_total)
        previous_x = current_x
        previous_y = current_y

    np.testing.assert_allclose(fit.x_explained_variance, expected_x, atol=2e-15)
    np.testing.assert_allclose(fit.y_explained_variance, expected_y, atol=2e-15)


@pytest.mark.parametrize(
    ("X", "Y", "message"),
    [
        ([[1.0, 2.0], [2.0, float("nan")]], [1.0, 2.0], "finite"),
        ([[1.0, 1.0], [1.0, 1.0]], [1.0, 2.0], "non-constant"),
        ([[1.0, 2.0], [2.0, 3.0]], [1.0, 1.0], "non-zero cross-covariance"),
    ],
)
def test_invalid_or_unidentifiable_fits_fail_closed(X: object, Y: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        fit_simpls(X, Y, n_components=1)


def test_rank_exhaustion_stops_at_the_last_identifiable_component() -> None:
    x = np.arange(1.0, 9.0)
    X = np.column_stack((x, 2.0 * x, -3.0 * x))

    fit = fit_simpls(X, x, n_components=2)
    assert fit.requested_n_components == 2
    assert fit.n_components == 1
    assert fit.x_scores.shape == (X.shape[0], 1)
    assert fit.coefficient_path.shape == (1, X.shape[1], 1)
    assert np.isfinite(fit.predict(X)).all()


def test_exact_rank_entry_point_rejects_an_unidentifiable_requested_component() -> None:
    x = np.arange(1.0, 9.0)
    X = np.column_stack((x, 2.0 * x, -3.0 * x))

    with pytest.raises(ValueError, match="identified 1 of 2 requested component"):
        fit_simpls_exact(X, x, n_components=2)

    assert "10.1016/0169-7439(93)85002-X" in CITATION


def test_every_registered_pls_core_consumer_binds_the_published_simpls_authority() -> None:
    consumers: list[str] = []
    for metadata in node_registry.list_nodes():
        contract = metadata.resolved_execution_contract()
        assert contract is not None
        component_ids = {component["component_id"] for component in contract.payload["implementation_components"]}
        if _PLS_CORE_COMPONENT_ID not in component_ids:
            continue
        consumers.append(metadata.node_type)
        assert any(
            "10.1016/0169-7439(93)85002-X" in citation for citation in contract.payload["citations"]
        ), f"{metadata.node_type} executes de Jong SIMPLS without binding its scientific reference"

    assert {"classification.plsda", "model.fitted_pls"} <= set(consumers)


def test_vip_authority_has_no_retired_spectrochempy_model_adapter() -> None:
    from spectra_sherpa.app.services.dag.nodes.selection import _vip

    assert not hasattr(_vip, "extract_vip_from_pls_model")


def test_representative_spectroscopy_fit_has_absolute_performance_ceiling() -> None:
    rng = np.random.default_rng(11)
    X = rng.normal(size=(200, 1600))
    Y = X @ rng.normal(size=(1600, 2)) + rng.normal(scale=0.05, size=(200, 2))

    with PerformanceCeiling("model.pls", "200x1600-two-responses", 5.0).measure():
        fit = fit_simpls(X, Y, n_components=8)

    assert fit.coefficients.shape == (1600, 2)
