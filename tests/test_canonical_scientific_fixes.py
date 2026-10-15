"""Regression oracles for the canonical-node scientific correctness audit."""

from __future__ import annotations

import asyncio
import copy

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import DomainContext, SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.nodes._chemometric_diagnostics import hotelling_t2_per_sample
from spectra_sherpa.app.services.dag.nodes.classification.application_nodes import ApplyKNNNode, ApplySIMCANode
from spectra_sherpa.app.services.dag.nodes.classification.knn_nodes import KNNNode, apply_knn_fitted_state
from spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes import PLSDANode, _plsda_scientific_core
from spectra_sherpa.app.services.dag.nodes.classification.simca_nodes import (
    SIMCANode,
    _predict_simca,
    _simca_scientific_core,
    apply_simca_fitted_state,
    simca_acceptance_membership,
)
from spectra_sherpa.app.services.dag.nodes.diagnostics import _outlier_dispatch
from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import FittedPLSV2Node
from spectra_sherpa.app.services.dag.nodes.modeling.library_compare_node import execute_library_comparison
from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import execute_pca_node, execute_pca_transform
from spectra_sherpa.app.services.dag.nodes.modeling.pls_core import fit_simpls
from spectra_sherpa.app.services.dag.nodes.selection._vip import calculate_vip


def dataset(x, *, units="absorbance"):
    x = np.asarray(x, dtype=float)
    return SherpaDataset(
        X=x,
        feature_axis=SpectralAxis(values=np.linspace(900, 1800, x.shape[1]), units="cm-1", title="Wavenumber"),
        sample_axis=SampleAxis(labels=[f"s{i}" for i in range(x.shape[0])]),
        units=units,
    )


def classification_data():
    rng = np.random.default_rng(812)
    x = np.r_[rng.normal(0, 1, (30, 5)), rng.normal(4, 1, (30, 5))]
    return dataset(x), np.repeat(["a", "b"], 30)


def classifier(kind):
    return {
        "knn": KNNNode("fit", {"n_neighbors": 3}),
        "simca": SIMCANode("fit", {"n_components": 2}),
        "plsda": PLSDANode("fit", {"n_components": 2}),
    }[kind]


@pytest.mark.parametrize("kind", ["knn", "simca", "plsda"])
def test_classifier_rejects_excluded_calibration_rows(kind):
    data, y = classification_data()
    data.sample_axis = SampleAxis(labels=data.sample_axis.labels, include_mask=np.r_[np.ones(59, dtype=bool), False])
    before = data.X.copy()
    with pytest.raises(ValueError, match="excluded samples.*active cohort"):
        asyncio.run(classifier(kind).execute(X=data, y=y))
    np.testing.assert_array_equal(data.X, before)


@pytest.mark.parametrize("kind", ["knn", "simca"])
@pytest.mark.parametrize("mutation", ["reverse", "axis_units", "signal_units", "quantity", "missing_axis"])
def test_classifier_application_binds_physical_input(kind, mutation):
    data, y = classification_data()
    state = classifier(kind).fit_fitted_state(data, y)
    application = {"knn": ApplyKNNNode, "simca": ApplySIMCANode}[kind]("apply", {})
    valid = asyncio.run(application.execute(default=data, fitted_state=state))
    assert len(valid.outputs["y_pred"]) == 60
    altered = data.copy()
    if mutation == "reverse":
        altered = dataset(data.X[:, ::-1])
        altered.feature_axis = SpectralAxis(values=data.feature_axis.values[::-1], units="cm-1", title="Wavenumber")
    elif mutation == "axis_units":
        altered.feature_axis = SpectralAxis(values=data.feature_axis.values, units="nm", title="Wavelength")
    elif mutation == "signal_units":
        altered.units = "%T"
    elif mutation == "quantity":
        altered.domain = DomainContext(data_quantity="Transmittance")
    else:
        altered = SherpaDataset(X=data.X, units=data.units)
    with pytest.raises(ValueError, match="fitted input authority"):
        asyncio.run(application.execute(default=altered, fitted_state=state))


@pytest.mark.parametrize("kind", ["knn", "simca"])
def test_classifier_refuses_unbound_legacy_state(kind):
    data, y = classification_data()
    state = classifier(kind).fit_fitted_state(data, y)
    state.pop("input_identity")
    with pytest.raises(ValueError):
        {"knn": apply_knn_fitted_state, "simca": apply_simca_fitted_state}[kind](data, state)


def test_library_rejects_absorbance_against_transmittance_before_false_match():
    axis = np.linspace(900, 1800, 101)
    absorbance = 0.1 + 0.7 * np.exp(-(((axis - 1350) / 100) ** 2))
    query = dataset(absorbance[None, :])
    library = dataset([100 * 10 ** (-absorbance), 100 * absorbance], units="%T")
    params = {
        "baseline_gap_threshold": 0.25,
        "diagnostic_band_threshold": 0.2,
        "hqi_accept_threshold": 750,
        "hqi_mode": "whole_spectrum",
        "hqi_reject_threshold": 500,
        "library_filter": "",
        "min_overlap_coverage": 0.5,
        "min_overlap_points": 20,
        "top_n": 10,
    }
    with pytest.raises(ValueError, match="signal_units"):
        execute_library_comparison(query, library, parameters=params, node_id="audit")
    library = dataset(-np.log10(library.X / 100))
    library.sample_axis = SampleAxis(labels=["correct", "decoy"])
    result = execute_library_comparison(query, library, parameters=params, node_id="audit")
    assert result.diagnostics["best_match"] == "correct"


def vip_oracle(fit):
    w = fit.x_weights
    contributions = np.array(
        [
            np.dot(fit.x_scores[:, h], fit.x_scores[:, h]) * np.dot(fit.y_loadings[:, h], fit.y_loadings[:, h])
            for h in range(w.shape[1])
        ]
    )
    return np.array(
        [
            np.sqrt(
                w.shape[0]
                * sum(contributions[h] * w[j, h] ** 2 / np.dot(w[:, h], w[:, h]) for h in range(w.shape[1]))
                / sum(contributions)
            )
            for j in range(w.shape[0])
        ]
    )


def test_two_class_two_component_plsda_vip_matches_independent_oracle():
    rng = np.random.default_rng(45)
    x = rng.normal(size=(80, 8))
    y = np.where(x[:, 0] + 0.3 * x[:, 1] + 0.15 * rng.normal(size=80) > 0, "a", "b")
    core = _plsda_scientific_core(dataset(x), y, parameters={"n_components": 2, "scale": True})
    np.testing.assert_allclose(core["vip_scores"], vip_oracle(core["fit"]), rtol=1e-13)
    assert core["vip_scores"][2] < 1 and core["vip_scores"][7] < 1


@pytest.mark.parametrize("features", [2, 8])
def test_fitted_pls_vip_with_square_response_and_weight_matrices(features):
    rng = np.random.default_rng(11)
    x = rng.normal(size=(60, features))
    y = x @ rng.normal(size=(features, 2)) + rng.normal(size=(60, 2)) * 0.1
    fit = fit_simpls(x, y, n_components=2, scale=False)
    state = FittedPLSV2Node("fit", {"n_components": 2, "scale": False}).fit_fitted_state(dataset(x), y)
    np.testing.assert_allclose(state["vip_scores"], vip_oracle(fit), rtol=1e-12)
    np.testing.assert_allclose(
        calculate_vip(fit.x_scores, fit.x_weights, fit.y_loadings, features), vip_oracle(fit), rtol=1e-12
    )


def test_vip_rejects_transposed_rectangular_matrices():
    with pytest.raises(ValueError, match="weights must have shape"):
        calculate_vip(np.ones((10, 2)), np.ones((2, 5)), np.ones((1, 2)), 5)
    with pytest.raises(ValueError, match="loadings must have shape"):
        calculate_vip(np.ones((10, 2)), np.ones((5, 2)), np.ones((2, 1)), 5)


def simca_core(x, y):
    return _simca_scientific_core(
        dataset(x), y, parameters={"n_components": 2, "confidence_level": 0.95, "critical_limits_method": "ddmoments"}
    )


def test_simca_predictions_and_membership_are_invariant_to_signal_scale():
    data, y = classification_data()
    query = np.r_[data.X, np.full((1, 5), 15.0)]
    baseline = None
    for factor in [1.0, 1e-14, 1e8]:
        core = simca_core(data.X * factor, y)
        labels, _ = apply_simca_fitted_state(dataset(query * factor), core["fitted_state"])
        membership = simca_acceptance_membership(dataset(query * factor), core["fitted_state"])[1]
        live = _predict_simca(
            query * factor, core["classes"], core["class_models"], core["T2_limits"], core["Q_limits"]
        )
        np.testing.assert_array_equal(labels, live[0])
        np.testing.assert_array_equal(membership, live[4])
        assert labels[-1] == "unassigned"
        if baseline is None:
            baseline = (labels, membership)
        else:
            np.testing.assert_array_equal(labels, baseline[0])
            np.testing.assert_array_equal(membership, baseline[1])


def test_simca_preserves_small_positive_q_limits():
    rng = np.random.default_rng(123)
    y = np.repeat(["a", "b"], 30)
    x = np.r_[
        rng.normal(size=(30, 1)) @ np.array([[1.0, 2.0, 3.0, 4.0, 5.0]]),
        rng.normal(size=(30, 1)) @ np.array([[2.0, 1.0, 4.0, 3.0, 6.0]]) + 3,
    ]
    x += rng.normal(size=(60, 5)) * 1e-9
    core = _simca_scientific_core(
        dataset(x), y, parameters={"n_components": 1, "confidence_level": 0.95, "critical_limits_method": "ddmoments"}
    )
    query = dataset(x[:1] + np.array([[1, -1, 1, -1, 1]]) * 1e-7)
    assert max(core["Q_limits"].values()) < 1e-12
    assert apply_simca_fitted_state(query, core["fitted_state"])[0].tolist() == ["unassigned"]
    assert not simca_acceptance_membership(query, core["fitted_state"])[1].any()


def pca(data, k):
    return execute_pca_node(
        data, node_id="pca", parameters={"n_components": str(k), "standardized": False, "scaled": False}
    ).outputs


@pytest.mark.parametrize("change", ["units", "quantity", "mode"])
def test_pca_binds_signal_semantics(change):
    data, _ = classification_data()
    fit = pca(data, 2)
    altered = data.copy()
    if change == "units":
        altered.units = "%T"
    elif change == "quantity":
        altered.domain = DomainContext(data_quantity="Transmittance")
    else:
        altered.domain = DomainContext(measurement_mode="reflection")
    with pytest.raises(ValueError, match="fitted input authority"):
        execute_pca_transform(altered, fit["model"], node_id="apply")
    np.testing.assert_allclose(
        execute_pca_transform(data, fit["model"], node_id="apply").outputs["scores"].X, fit["scores"].X, atol=1e-12
    )


@pytest.mark.parametrize("factor", [1e-8, 1.0, 1e8])
def test_pca_t2_uses_same_scale_invariant_authority(factor):
    x = np.random.default_rng(812).normal(size=(40, 6))
    fit = pca(dataset(x * factor), 2)
    screen, _ = _outlier_dispatch(fit["diagnostic_state"])
    reference = pca(dataset(x), 2)["diagnostic_state"]["T2"]
    np.testing.assert_allclose(screen["T2"], reference, rtol=1e-12)
    np.testing.assert_allclose(screen["T2"], fit["diagnostic_state"]["T2"], rtol=0, atol=0)


@pytest.mark.parametrize("factor", [1e-8, 1.0, 1e8])
def test_pca_rejects_null_directions_at_any_scale(factor):
    x = np.arange(10.0)[:, None] * np.array([[1.0, 2.0, 3.0]]) * factor
    valid = pca(dataset(x), 1)
    with pytest.raises(ValueError, match="numerical-null"):
        pca(dataset(x), 2)
    with pytest.raises(ValueError, match="numerical-null"):
        hotelling_t2_per_sample(np.ones((10, 2)), eigenvalues=np.array([1.0, 1e-30]) * factor**2)
    forged = copy.deepcopy(valid["diagnostic_state"])
    forged["n_components"] = 2
    forged["scores"] = np.c_[valid["scores"].X, np.zeros(10)]
    forged["eigenvalues"] = [factor**2, 1e-30 * factor**2]
    with pytest.raises(ValueError, match="numerical-null"):
        _outlier_dispatch(forged)


def test_full_feature_pca_has_no_roundoff_outliers():
    fit = pca(dataset(np.random.default_rng(812).normal(size=(40, 6))), 6)
    screening, _ = _outlier_dispatch(fit["diagnostic_state"])
    np.testing.assert_array_equal(screening["Q"], np.zeros(40))
    assert screening["outlier_indices"] == []


@pytest.mark.parametrize("kind", ["knn", "simca"])
def test_saved_classifier_roundtrip_binds_input_identity(kind, tmp_path):
    from spectra_sherpa.app.services.dag.nodes.modeling.load_apply_node import _apply_model_artifact
    from spectra_sherpa.app.services.execution_runtime import ApplicationModelArtifactReplay
    from spectra_sherpa.app.services.model_application import preflight_model_application
    from spectra_sherpa.app.services.model_store import ModelStore

    data, y = classification_data()
    fitted = asyncio.run(classifier(kind).execute(X=data, y=y))
    artifact = fitted.outputs["_model_artifact"]
    store = ModelStore(tmp_path)
    store.save("audit-roundtrip", artifact["metadata"], artifact["arrays"])
    manifest, arrays = store.load("audit-roundtrip")

    def apply(query):
        return _apply_model_artifact(
            manifest, arrays, query, model_id="audit-roundtrip", replay=ApplicationModelArtifactReplay()
        )

    apply(data)
    preflight_model_application(data, manifest, arrays)
    altered = data.copy()
    altered.units = "%T"
    for action in (apply, lambda query: preflight_model_application(query, manifest, arrays)):
        with pytest.raises(ValueError, match="fitted input authority"):
            action(altered)
    manifest.pop("input_identity")
    with pytest.raises(ValueError, match="rebuild the fitted state"):
        apply(data)


@pytest.mark.parametrize("operation", ["pca", "pls", "msc", "scale"])
@pytest.mark.parametrize("axis_name", ["sample", "feature"])
def test_core_numerical_paths_refuse_unmaterialized_exclusions(operation, axis_name):
    from spectra_sherpa.app.services.dag.nodes.preprocessing.msc_node import MSCNode
    from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode

    data, _ = classification_data()
    if axis_name == "sample":
        data.sample_axis = SampleAxis(include_mask=[True] * 59 + [False])
    else:
        data.feature_axis = SpectralAxis(
            values=data.feature_axis.values, units="cm-1", include_mask=[True] * 4 + [False]
        )
    with pytest.raises(ValueError, match="excluded.*materialize the active"):
        if operation == "pca":
            pca(data, 2)
        elif operation == "pls":
            FittedPLSV2Node("fit", {"n_components": 2}).fit_fitted_state(data, np.arange(60.0))
        elif operation == "msc":
            MSCNode("fit", {}).fit_fitted_state(data)
        else:
            ScaleNode("fit", {"method": "mean_center"}).fit_fitted_state(data)


def test_explicit_variable_filter_materializes_the_active_bands():
    from spectra_sherpa.app.services.dag.nodes.selection.variable_select_node import _variable_select_execute

    data, _ = classification_data()
    data.feature_axis = SpectralAxis(values=data.feature_axis.values, units="cm-1", include_mask=[True] * 4 + [False])
    outputs, _ = _variable_select_execute(
        data, mask=np.ones(5, dtype=bool), node_id="select", parameters={"method": "apply_mask"}
    )
    selected = outputs["default"]
    assert selected.shape == (60, 4)
    pca(selected, 2)


def test_pca_q_spectrum_limit_is_not_an_outlier_count_quota():
    from scipy.stats import f, norm

    rng = np.random.default_rng(731)
    x = rng.normal(0, 0.03, (40, 12))
    x[:, 0] = np.linspace(-20, 20, 40)
    for i in range(6):
        x[34 + i, 1 + i] = 3
    fitted = pca(dataset(x), 1)
    result, _ = _outlier_dispatch(fitted["diagnostic_state"])
    u, s, v = np.linalg.svd(x - x.mean(0), full_matrices=False)
    eigen = s[1:] ** 2 / 39
    a, b, c = [sum(eigen**power) for power in (1, 2, 3)]
    h = 1 - 2 * a * c / (3 * b * b)
    oracle = a * (1 + norm.ppf(0.95) * np.sqrt(2 * b) * h / a + b * h * (h - 1) / (a * a)) ** (1 / h)
    assert result["Q_limit"] == pytest.approx(oracle, rel=1e-12)
    assert result["T2_limit"] == pytest.approx(39 / 39 * f.ppf(0.95, 1, 39))
    assert set(range(34, 40)) <= set(result["outlier_indices"])
    assert np.count_nonzero(np.asarray(result["Q"]) > np.quantile(result["Q"], 0.95)) == 2


def test_pls_uses_fitted_theoretical_limits_and_keeps_legacy_screening_readable():
    from scipy.stats import f

    from spectra_sherpa.app.lib.pca_numerics import residual_eigenvalues, residual_q_limit
    from spectra_sherpa.app.services.dag.nodes.modeling import pls_applicability

    rng = np.random.default_rng(78)
    x = rng.normal(size=(50, 8))
    y = x[:, 0] + 0.1 * rng.normal(size=50)
    fit = fit_simpls(x, y, n_components=2, scale=False)
    state = pls_applicability.fit_screening(x, fit)
    assert state["t2_limit"] == pytest.approx(2 * 49 * 51 / (50 * 48) * f.ppf(0.95, 2, 48))
    z = (x - fit.x_offset) / fit.x_scale
    residual = z - (z @ fit.x_weights) @ fit.x_loadings.T
    assert state["q_limit"] == pytest.approx(residual_q_limit(residual_eigenvalues(residual), 0.95)[0])
    before = copy.deepcopy(state)
    report = pls_applicability.apply_screening(x * 100, fit.x_offset, state)
    assert any(row["outside_q"] for row in report["rows"])
    assert state == before
    legacy = copy.deepcopy(state)
    legacy.pop("q_residual_eigenvalues")
    legacy.pop("q_limit_method")
    legacy["schema_version"] = pls_applicability.LEGACY_SCHEMA
    legacy["method"] = pls_applicability.LEGACY_METHOD
    legacy["q_limit"] = max(legacy["q_calibration_quantile"], legacy["q_numerical_tolerance"])
    pls_applicability.validate_screening(legacy, features=8, components=2, samples=50)


def test_plsda_reports_extrapolation_even_for_confident_class_responses():
    from spectra_sherpa.app.services.dag.nodes.classification.application_nodes import ApplyPLSDANode

    data, y = classification_data()
    state = classifier("plsda").fit_fitted_state(data, y)
    # Add an orthogonal direction that contributes almost nothing to either response.
    from spectra_sherpa.app.services.dag.nodes.classification.plsda_state import SherpaPLSDAArtifact

    artifact = SherpaPLSDAArtifact.from_fitted_state(state)
    _, _, v = np.linalg.svd(artifact.coefficients.T, full_matrices=True)
    query = dataset(data.X[:1] + 100 * v[-1])
    result = asyncio.run(ApplyPLSDANode("apply", {}).execute(default=query, fitted_state=state))
    report = result.diagnostics["applicability"]
    assert report["rows"][0]["outside_q"] is True
    assert report["warning"] and report["n_out_of_domain"] == 1
    np.testing.assert_allclose(result.outputs["class_scores"], artifact.predict(dataset(data.X[:1]))[1], atol=1e-12)
    altered = data.copy()
    altered.units = "%T"
    with pytest.raises(ValueError, match="fitted input authority"):
        artifact.predict(altered)


def test_plsda_legacy_screen_warning_survives_application_summary():
    from dataclasses import replace

    from spectra_sherpa.app.services.dag.nodes.classification.plsda_state import SherpaPLSDAArtifact
    from spectra_sherpa.app.services.dag.nodes.modeling import pls_applicability
    from spectra_sherpa.app.services.model_application import _present_plsda_applicability

    data, y = classification_data()
    artifact = SherpaPLSDAArtifact.from_fitted_state(classifier("plsda").fit_fitted_state(data, y))
    legacy = copy.deepcopy(artifact.screening)
    legacy.pop("q_residual_eigenvalues")
    legacy.pop("q_limit_method")
    legacy["schema_version"] = pls_applicability.LEGACY_SCHEMA
    legacy["method"] = pls_applicability.LEGACY_METHOD
    legacy["q_limit"] = max(legacy["q_calibration_quantile"], legacy["q_numerical_tolerance"])
    report = replace(artifact, screening=legacy).applicability(data.X[:1])
    assert report["schema_version"] == pls_applicability.LEGACY_SCHEMA
    presented = _present_plsda_applicability(report)
    assert "Legacy empirical screening limits" in presented["warning"]
    assert "Legacy empirical screening limits" not in (report["warning"] or "")


@pytest.mark.parametrize("kind", ["mcr", "ica"])
@pytest.mark.parametrize("mutation", ["units", "quantity", "axis"])
def test_decomposition_application_binds_physical_input(kind, mutation):
    from spectra_sherpa.app.lib.fitted_state import FastICAExtract, MCRExtract
    from spectra_sherpa.app.services.dag.nodes.modeling.ica_node import (
        _ica_fitted_state_from_extract,
        apply_ica_fitted_state,
    )
    from spectra_sherpa.app.services.dag.nodes.modeling.mcr_nodes import (
        _mcr_fitted_state_from_extract,
        apply_mcr_fitted_state,
    )

    data = dataset(np.abs(np.random.default_rng(78).normal(size=(20, 3))))
    if kind == "mcr":
        extract = MCRExtract(C=data.X[:, :2], St=np.array([[1, 0, 0], [0, 1, 0]]), n_components=2)
        state = _mcr_fitted_state_from_extract(extract, data)
        apply = apply_mcr_fitted_state
    else:
        extract = FastICAExtract(
            components=np.eye(3)[:2],
            mixing=np.eye(3)[:, :2],
            mean=np.zeros(3),
            n_components=2,
            n_features=3,
            algorithm="parallel",
            fun="logcosh",
            whiten="unit-variance",
            random_seed=42,
        )
        state = _ica_fitted_state_from_extract(extract, data)
        apply = apply_ica_fitted_state
    assert apply(data, state).shape == (20, 2)
    altered = data.copy()
    if mutation == "units":
        altered.units = "%T"
    elif mutation == "quantity":
        altered.domain = DomainContext(data_quantity="Transmittance")
    else:
        altered.feature_axis = SpectralAxis(values=data.feature_axis.values[::-1], units="cm-1")
    with pytest.raises(ValueError, match="fitted input authority"):
        apply(altered, state)


@pytest.mark.parametrize("gap,segment", [(1, 1), (2, 3), (5, 5)])
def test_norris_second_derivative_never_consumes_zero_filled_edges(gap, segment):
    from spectra_sherpa.app.services.dag.nodes.preprocessing.norris_williams import norris_williams

    x = np.arange(101.0) * 0.25
    derivative = norris_williams(0.5 * x * x, gap=gap, segment=segment, deriv=2, delta=0.25)
    margin = 2 * (gap + segment - 1)
    np.testing.assert_allclose(derivative[margin:-margin], 1, atol=1e-11)
    np.testing.assert_array_equal(derivative[:margin], 0)
    np.testing.assert_array_equal(derivative[-margin:], 0)


@pytest.mark.parametrize("factor", [1e-8, 1, 1e8])
def test_autoscale_does_not_promote_roundoff_but_preserves_small_real_variation(factor):
    from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode

    rng = np.random.default_rng(52)
    x = np.c_[1 + rng.normal(size=40) * 1e-15, rng.normal(size=40), rng.normal(size=40) * 1e-15] * factor
    data = dataset(x)
    node = ScaleNode("scale", {"method": "autoscale"})
    state = node.fit_fitted_state(data)
    scaled = node.apply_fitted_state(data, state).X
    assert np.std(scaled[:, 0]) < 1e-5
    np.testing.assert_allclose(np.std(scaled[:, 1:], axis=0), 1, rtol=1e-13)
