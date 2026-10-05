"""C2k canonical variable-selection rule proofs."""

from __future__ import annotations

import asyncio
import copy
import time

import numpy as np
import pytest
from sklearn.cross_decomposition import PLSRegression

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.modeling import pls_core
from spectra_sherpa.app.services.dag.nodes.selection._selectivity_ratio import (
    target_projection_selectivity_ratio,
)
from spectra_sherpa.app.services.dag.nodes.selection.variable_select_node import (
    VariableSelectNode,
    _canonical_variable_select_parameters,
    _variable_select_execute,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily


@pytest.fixture
def variable_data() -> SherpaDataset:
    rng = np.random.default_rng(760)
    axis = np.linspace(900.0, 1800.0, 30)
    matrix = rng.normal(scale=0.03, size=(24, 30))
    matrix[:, 8] += 1.2
    matrix[:, 21] -= 0.9
    return SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(values=axis, labels=[f"band-{i}" for i in range(30)], units="cm-1"),
        target=rng.normal(size=24),
    )


def test_variable_select_has_one_exact_local_target_free_contract() -> None:
    contract = node_registry.get_metadata("selection.variable_select").resolved_execution_contract()
    assert contract is not None
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
    assert contract.payload["managed_optimization_eligibility"] == (
        ManagedOptimizationEligibility.LOCAL.value,
        ManagedOptimizationEligibility.DEVELOPMENT.value,
        ManagedOptimizationEligibility.FULL_REFIT.value,
    )
    assert contract.payload["managed_optimization_profiles"] == ("first_party_pls",)
    assert contract.payload["target_access"] == "none"
    assert any("mda.tools/docs/pls--variable-selection" in citation for citation in contract.payload["citations"])
    assert any("10.1002/cem.1289" in citation for citation in contract.payload["citations"])
    assert any("10.1038/s41592-019-0686-2" in citation for citation in contract.payload["citations"])


def test_parameters_are_method_specific_and_prototype_ambiguity_fails_closed() -> None:
    assert _canonical_variable_select_parameters({"method": "coef_abs", "threshold": 0.4}) == {
        "method": "coef_abs",
        "invert": False,
        "threshold": 0.4,
    }
    for invalid in (
        {"method": "unknown"},
        {"method": "interval", "region_start": 1.0, "region_end": 1.0},
        {"method": "peak_window", "peak_prominence": 0.0},
        {"method": "coef_abs", "threshold": 1.1},
        {"method": "vip", "threshold": 0.0},
        {"method": "apply_mask", "threshold": 0.5},
        {"method": "vip", "peak_half_window": 11},
        {"method": "interval", "region_start": 1.0, "region_end": 2.0, "invert": 1},
    ):
        with pytest.raises(ValueError):
            _canonical_variable_select_parameters(invalid)


def test_interval_and_exact_boolean_mask_are_transparent(variable_data: SherpaDataset) -> None:
    interval_outputs, interval_diagnostics = _variable_select_execute(
        variable_data,
        node_id="interval",
        parameters={"method": "interval", "region_start": 1100.0, "region_end": 1400.0},
    )
    expected = (np.asarray(variable_data.feature_axis.values) >= 1100.0) & (
        np.asarray(variable_data.feature_axis.values) <= 1400.0
    )
    np.testing.assert_array_equal(interval_outputs["mask"], expected)
    assert interval_diagnostics["selection_scope"] == "target_free_feature_rule_not_predictive_validation"

    supplied = np.arange(variable_data.shape[1]) % 3 == 0
    masked_outputs, _ = _variable_select_execute(
        variable_data,
        mask=supplied,
        node_id="mask",
        parameters={"method": "apply_mask"},
    )
    np.testing.assert_array_equal(masked_outputs["mask"], supplied)
    with pytest.raises(ValueError, match="boolean vector"):
        _variable_select_execute(
            variable_data,
            mask=supplied.astype(int),
            node_id="mask",
            parameters={"method": "apply_mask"},
        )


def test_peak_window_matches_scipy_and_never_substitutes_an_unrequested_rule(
    variable_data: SherpaDataset,
) -> None:
    outputs, _ = _variable_select_execute(
        variable_data,
        node_id="peaks",
        parameters={
            "method": "peak_window",
            "peak_prominence": 0.2,
            "peak_half_window": 2,
            "include_negative_extrema": True,
        },
    )
    assert outputs["selection_report"]["detected_extrema_indices"] == [8, 21]
    expected = np.zeros(30, dtype=bool)
    expected[6:11] = True
    expected[19:24] = True
    np.testing.assert_array_equal(outputs["mask"], expected)

    flat = SherpaDataset(X=np.ones((10, 8)), feature_axis=SpectralAxis(values=np.arange(8)))
    with pytest.raises(ValueError, match="found no extrema"):
        _variable_select_execute(
            flat,
            node_id="peaks",
            parameters={"method": "peak_window", "peak_prominence": 0.1, "peak_half_window": 1},
        )


def test_coefficient_and_selectivity_ratio_match_independent_oracles(variable_data: SherpaDataset) -> None:
    matrix = np.asarray(variable_data.X)
    target = 1.5 * matrix[:, 4] - 0.8 * matrix[:, 17]
    model = PLSRegression(n_components=2, scale=False).fit(matrix, target)
    coefficients = np.asarray(model.coef_).reshape(-1)

    coefficient_outputs, _ = _variable_select_execute(
        variable_data,
        model=model,
        node_id="coefficient",
        parameters={"method": "coef_abs", "threshold": 0.2},
    )
    coefficient_oracle = np.abs(coefficients) / np.max(np.abs(coefficients))
    np.testing.assert_allclose(coefficient_outputs["scores"], coefficient_oracle, rtol=0.0, atol=0.0)
    np.testing.assert_array_equal(coefficient_outputs["mask"], coefficient_oracle >= 0.2)

    sr_outputs, _ = _variable_select_execute(
        variable_data,
        model=model,
        node_id="sr",
        parameters={"method": "selectivity_ratio", "threshold": 0.01},
    )
    centered = matrix - np.mean(matrix, axis=0)
    target_scores = centered @ coefficients
    # Independent least-squares oracle. Reusing the regression vector as the
    # reconstruction loading would repeat the implementation defect.
    target_loadings = np.linalg.lstsq(target_scores[:, None], centered, rcond=None)[0].reshape(-1)
    projection = np.outer(target_scores, target_loadings)
    residual_matrix = centered - projection
    explained = np.var(projection, axis=0)
    residual = np.var(residual_matrix, axis=0)
    floor = np.finfo(np.float64).eps * max(float(np.max(explained)), 1.0)
    oracle = explained / np.maximum(residual, floor)
    np.testing.assert_allclose(target_scores @ residual_matrix, np.zeros(matrix.shape[1]), atol=1e-12)
    np.testing.assert_allclose(sr_outputs["scores"], oracle, rtol=1e-13, atol=1e-13)


def test_vip_consumes_explicit_producer_scores_and_fails_closed(variable_data: SherpaDataset) -> None:
    vip = np.linspace(0.5, 1.5, variable_data.shape[1])

    outputs, _ = _variable_select_execute(
        variable_data,
        importance_scores=vip,
        node_id="vip",
        parameters={"method": "vip", "threshold": 1.0},
    )

    np.testing.assert_array_equal(outputs["scores"], vip)
    np.testing.assert_array_equal(outputs["mask"], vip >= 1.0)
    with pytest.raises(ValueError, match="producer-owned"):
        _variable_select_execute(
            variable_data,
            node_id="vip",
            parameters={"method": "vip", "threshold": 1.0},
        )
    with pytest.raises(ValueError, match="match the feature count"):
        _variable_select_execute(
            variable_data,
            importance_scores=vip[:-1],
            node_id="vip",
            parameters={"method": "vip", "threshold": 1.0},
        )


def test_stability_and_variable_rule_share_one_selectivity_ratio_authority(variable_data: SherpaDataset) -> None:
    from spectra_sherpa.app.services.dag.nodes.selection.stability_node import _base_scores

    matrix = np.asarray(variable_data.X)
    target = 1.5 * matrix[:, 4] - 0.8 * matrix[:, 17]
    model = pls_core.fit_simpls_exact(matrix, target, n_components=2, scale=False)
    expected = _base_scores(model, matrix, "selectivity_ratio")

    outputs, _ = _variable_select_execute(
        variable_data,
        model=model,
        node_id="sr",
        parameters={"method": "selectivity_ratio", "threshold": 0.01},
    )

    np.testing.assert_allclose(outputs["scores"], expected, rtol=0.0, atol=0.0)


def test_selectivity_ratio_is_scale_invariant_and_fails_closed() -> None:
    rng = np.random.default_rng(112)
    matrix = rng.normal(size=(18, 7))
    coefficients = rng.normal(size=7)
    expected = target_projection_selectivity_ratio(matrix, coefficients)

    np.testing.assert_allclose(
        target_projection_selectivity_ratio(matrix, -3.7 * coefficients),
        expected,
        rtol=1e-13,
        atol=1e-13,
    )
    np.testing.assert_allclose(
        target_projection_selectivity_ratio(matrix * 1e-12, coefficients),
        expected,
        rtol=1e-13,
        atol=1e-13,
    )
    for invalid_matrix, invalid_coefficients in (
        (matrix[:, 0], coefficients),
        (matrix, coefficients[:-1]),
        (matrix, np.zeros_like(coefficients)),
        (np.full_like(matrix, np.nan), coefficients),
    ):
        with pytest.raises(ValueError):
            target_projection_selectivity_ratio(invalid_matrix, invalid_coefficients)


def test_generated_selectivity_ratio_calls_the_same_authority(variable_data: SherpaDataset) -> None:
    matrix = np.asarray(variable_data.X)
    target = 1.5 * matrix[:, 4] - 0.8 * matrix[:, 17]
    model = PLSRegression(n_components=2, scale=False).fit(matrix, target)
    node = VariableSelectNode("sr", {"method": "selectivity_ratio", "threshold": 0.01})
    live = asyncio.run(node.execute(X=variable_data, model=model))
    namespace = {"input_data": variable_data, "fitted_model": model, "results": {}}

    exec(
        "\n".join(node.generate_python({"X": "input_data", "model": "fitted_model"}, indent="")),
        namespace,
    )

    generated = namespace["results"]["sr"]
    np.testing.assert_allclose(generated["scores"], live.outputs["scores"], rtol=0.0, atol=0.0)
    np.testing.assert_array_equal(generated["mask"], live.outputs["mask"])


def test_execution_preserves_inputs_targets_and_emits_closed_non_predictive_evidence(
    variable_data: SherpaDataset,
) -> None:
    original = copy.deepcopy(variable_data)
    outputs, _ = _variable_select_execute(
        variable_data,
        node_id="interval",
        parameters={"method": "interval", "region_start": 1000.0, "region_end": 1300.0},
    )
    np.testing.assert_array_equal(variable_data.X, original.X)
    np.testing.assert_array_equal(variable_data.target, original.target)
    np.testing.assert_array_equal(outputs["X_selected"].target, original.target)
    report = outputs["selection_report"]
    assert set(report) == {
        "schema",
        "method",
        "parameters",
        "selection_scope",
        "predictive_performance_claimed",
        "reference_samples",
        "reference_features",
        "selected_features",
        "feature_axis_values_sha256",
        "feature_mask_sha256",
        "score_sha256",
        "detected_extrema_indices",
    }
    assert report["predictive_performance_claimed"] is False
    assert "target" not in report


def test_generated_python_calls_the_live_implementation_and_matches_it(variable_data: SherpaDataset) -> None:
    node = VariableSelectNode(
        "interval",
        {"method": "interval", "region_start": 1000.0, "region_end": 1300.0},
    )
    live = asyncio.run(node.execute(X=variable_data))
    namespace = {"input_data": variable_data, "results": {}}
    exec("\n".join(node.generate_python({"X": "input_data"}, indent="")), namespace)
    generated = namespace["results"]["interval"]
    np.testing.assert_array_equal(generated["mask"], live.outputs["mask"])
    np.testing.assert_array_equal(generated["X_selected"].X, live.outputs["X_selected"].X)
    assert generated["selection_report"] == live.outputs["selection_report"]


def test_fixed_workload_is_bounded(variable_data: SherpaDataset) -> None:
    started = time.monotonic()
    for _ in range(50):
        _variable_select_execute(
            variable_data,
            node_id="interval",
            parameters={"method": "interval", "region_start": 1000.0, "region_end": 1300.0},
        )
    assert time.monotonic() - started < 5.0
