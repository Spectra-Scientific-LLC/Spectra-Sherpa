"""Canonical nonlinear saturation and explicit composition proofs."""

from __future__ import annotations

import copy

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.saturation_response import apply_saturation_transition
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.custom import HybridSelectorNode, SaturationModelNode
from spectra_sherpa.app.services.dag.nodes.custom_contracts import (
    build_hybrid_selector_result,
    build_saturation_model_result,
    canonical_hybrid_selector_parameters,
    canonical_saturation_model_parameters,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


def _sensitivity(*, features: int = 4) -> SherpaDataset:
    return SherpaDataset(
        X=np.linspace(0.0, 0.04, features, dtype=np.float64).reshape(1, -1),
        feature_axis=SpectralAxis(values=np.linspace(900.0, 1800.0, features), units="cm-1"),
        units="absorbance/ppm",
        title="Sensitivity",
    )


def _modeled_pair(*, samples: int = 3, features: int = 4) -> tuple[SherpaDataset, SherpaDataset]:
    axis = SpectralAxis(values=np.linspace(900.0, 1800.0, features), units="cm-1")
    sample_axis = SampleAxis(values=np.arange(samples), title="Concentration observation")
    base = np.arange(samples * features, dtype=np.float64).reshape(samples, features) / 10.0
    linear = SherpaDataset(
        X=base,
        feature_axis=axis,
        sample_axis=sample_axis,
        units="absorbance",
        title="Linear",
    )
    saturation = SherpaDataset(
        X=base + 10.0,
        feature_axis=axis.copy(),
        sample_axis=sample_axis.copy(),
        units="absorbance",
        title="Saturation",
    )
    return linear, saturation


def test_saturation_and_selector_publish_exact_local_contracts() -> None:
    saturation = node_registry.get_metadata("custom.saturation_model").resolved_execution_contract()
    selector = node_registry.get_metadata("custom.hybrid_selector").resolved_execution_contract()

    assert saturation is not None
    assert saturation.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert saturation.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
    assert saturation.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert saturation.payload["sample_effect"] == "generates_samples"
    assert any("10.1039/C5AY02393A" in citation for citation in saturation.payload["citations"])

    assert selector is not None
    assert selector.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert selector.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert selector.payload["sample_effect"] == "preserves_samples"


def test_saturation_and_selector_parameter_grammars_are_closed() -> None:
    assert canonical_saturation_model_parameters({"concentration_unit": "ppm"}) == {"concentration_unit": "ppm"}
    assert canonical_hybrid_selector_parameters({}) == {}
    with pytest.raises(ValueError):
        canonical_saturation_model_parameters({})
    with pytest.raises(ValueError):
        canonical_saturation_model_parameters({"concentration_unit": "unknown"})
    with pytest.raises(ValueError):
        canonical_saturation_model_parameters({"concentration_unit": "ppm", "warn": True})
    with pytest.raises(ValueError):
        canonical_hybrid_selector_parameters({"saturation_threshold": 0.5})


@pytest.mark.asyncio
async def test_saturation_live_generated_and_transitional_paths_share_equation_13() -> None:
    sensitivity = _sensitivity()
    levels = np.array([1.5, 1.6, 1.7, 1.8])
    exponents = np.array([1.0, 1.25, 1.5, 2.0])
    concentrations = np.array([0.0, 10.0, 25.0])
    node = SaturationModelNode("saturation", {"concentration_unit": "ppm"})

    live = await node.execute(
        sensitivity=sensitivity,
        saturation_levels=levels,
        shape_exponents=exponents,
        concentrations=concentrations,
        calibration_minimum=0.0,
        calibration_maximum=25.0,
    )
    namespace = {
        "sensitivity": sensitivity,
        "levels": levels,
        "exponents": exponents,
        "concentrations": concentrations,
        "minimum": 0.0,
        "maximum": 25.0,
        "results": {},
    }
    exec(
        "\n".join(
            node.generate_python(
                {
                    "sensitivity": "sensitivity",
                    "saturation_levels": "levels",
                    "shape_exponents": "exponents",
                    "concentrations": "concentrations",
                    "calibration_minimum": "minimum",
                    "calibration_maximum": "maximum",
                },
                indent="",
            )
        ),
        namespace,
    )  # noqa: S102
    generated = namespace["results"]["saturation"]
    ideal = concentrations[:, np.newaxis] * sensitivity.X[0][np.newaxis, :]
    expected = levels[np.newaxis, :] * np.tanh((ideal / levels[np.newaxis, :]) ** exponents[np.newaxis, :]) ** (
        1.0 / exponents[np.newaxis, :]
    )

    np.testing.assert_allclose(live.outputs["default"].X, expected, rtol=1e-14, atol=1e-14)
    np.testing.assert_array_equal(generated.X, live.outputs["default"].X)
    assert live.diagnostics["calibration_state_digest"] == generated.meta["calibration_state_digest"]
    assert live.diagnostics["sensitivity_unit"] == "absorbance/ppm"

    saturated_limit = apply_saturation_transition(np.array([[1.0e308]]), 1.0, 2.0)
    np.testing.assert_array_equal(saturated_limit, np.ones((1, 1)))


def test_saturation_fails_closed_on_incomplete_science_and_extrapolation() -> None:
    sensitivity = _sensitivity()
    valid = (
        sensitivity,
        np.ones(4),
        np.ones(4),
        np.array([1.0, 2.0]),
        0.0,
        5.0,
        {"concentration_unit": "ppm"},
    )
    build_saturation_model_result(*valid, node_id="saturation")
    cases = [
        (sensitivity, np.ones(3), np.ones(4), np.array([1.0]), 0.0, 5.0),
        (sensitivity, np.ones(4), np.array([1.0, 0.0, 1.0, 1.0]), np.array([1.0]), 0.0, 5.0),
        (sensitivity, np.ones(4), np.ones(4), np.array([-1.0]), 0.0, 5.0),
        (sensitivity, np.ones(4), np.ones(4), np.array([6.0]), 0.0, 5.0),
        (sensitivity, np.ones(4), np.ones(4), np.array([1.0]), 5.0, 5.0),
    ]
    for inputs in cases:
        with pytest.raises(ValueError):
            build_saturation_model_result(*inputs, {"concentration_unit": "ppm"}, node_id="saturation")

    negative_sensitivity = copy.deepcopy(sensitivity)
    negative_sensitivity.X[0, 1] = -0.1
    with pytest.raises(ValueError, match="non-negative"):
        build_saturation_model_result(
            negative_sensitivity,
            np.ones(4),
            np.ones(4),
            np.array([1.0]),
            0.0,
            5.0,
            {"concentration_unit": "ppm"},
            node_id="saturation",
        )
    wrong_units = copy.deepcopy(sensitivity)
    wrong_units.units = "absorbance/mg/L"
    with pytest.raises(ValueError, match="units must exactly match"):
        build_saturation_model_result(
            wrong_units,
            np.ones(4),
            np.ones(4),
            np.array([1.0]),
            0.0,
            5.0,
            {"concentration_unit": "ppm"},
            node_id="saturation",
        )
    with pytest.raises(ValueError, match="non-negative"):
        apply_saturation_transition(np.array([[-1.0]]), 1.0, 1.0)


@pytest.mark.asyncio
async def test_hybrid_selector_live_and_generated_paths_apply_only_the_explicit_mask() -> None:
    linear, saturation = _modeled_pair()
    mask = np.array([0, 1, 0, 1])
    node = HybridSelectorNode("selector", {})

    live = await node.execute(linear_result=linear, saturation_result=saturation, model_mask=mask)
    namespace = {"linear": linear, "saturation": saturation, "mask": mask, "results": {}}
    exec(
        "\n".join(
            node.generate_python(
                {"linear_result": "linear", "saturation_result": "saturation", "model_mask": "mask"},
                indent="",
            )
        ),
        namespace,
    )  # noqa: S102
    expected = np.where(mask[np.newaxis, :].astype(bool), saturation.X, linear.X)
    np.testing.assert_array_equal(live.outputs["default"].X, expected)
    np.testing.assert_array_equal(namespace["results"]["selector"].X, expected)
    assert live.diagnostics["selection_authority"] == "upstream_explicit_mask"
    assert live.diagnostics["linear_feature_count"] == 2
    assert live.diagnostics["saturation_feature_count"] == 2


def test_hybrid_selector_rejects_shape_axis_unit_and_mask_drift() -> None:
    linear, saturation = _modeled_pair()
    valid_mask = np.array([0, 1, 0, 1])
    build_hybrid_selector_result(linear, saturation, valid_mask, {}, node_id="selector")

    wrong_shape = SherpaDataset(
        X=saturation.X[:, :3],
        feature_axis=SpectralAxis(values=np.array([900.0, 1200.0, 1500.0]), units="cm-1"),
        sample_axis=saturation.sample_axis.copy(),
        units="absorbance",
    )
    wrong_axis = SherpaDataset(
        X=saturation.X,
        feature_axis=SpectralAxis(values=np.array([900.0, 1200.5, 1500.0, 1800.0]), units="cm-1"),
        sample_axis=saturation.sample_axis.copy(),
        units="absorbance",
    )
    wrong_units = SherpaDataset(
        X=saturation.X,
        feature_axis=saturation.feature_axis.copy(),
        sample_axis=saturation.sample_axis.copy(),
        units="transmittance",
    )
    for candidate in (wrong_shape, wrong_axis, wrong_units):
        with pytest.raises(ValueError):
            build_hybrid_selector_result(linear, candidate, valid_mask, {}, node_id="selector")
    for invalid_mask in (np.array([0, 1, 0]), np.array([0, 0.5, 0, 1]), np.array([0, np.nan, 0, 1])):
        with pytest.raises(ValueError):
            build_hybrid_selector_result(linear, saturation, invalid_mask, {}, node_id="selector")


def test_saturation_and_selector_fixed_workloads_stay_inside_reviewed_ceilings() -> None:
    features = 1600
    samples = 200
    sensitivity = _sensitivity(features=features)
    levels = np.linspace(1.5, 2.5, features)
    exponents = np.linspace(1.0, 2.0, features)
    concentrations = np.linspace(0.0, 100.0, samples)
    parameters = {"concentration_unit": "ppm"}
    linear, saturation = _modeled_pair(samples=samples, features=features)
    mask = np.arange(features) % 2

    build_saturation_model_result(
        sensitivity, levels, exponents, concentrations, 0.0, 100.0, parameters, node_id="saturation"
    )
    build_hybrid_selector_result(linear, saturation, mask, {}, node_id="selector")
    with PerformanceCeiling("custom.saturation_model", "200x1600-equation-13", 5.0).measure():
        build_saturation_model_result(
            sensitivity, levels, exponents, concentrations, 0.0, 100.0, parameters, node_id="saturation"
        )
    with PerformanceCeiling("custom.hybrid_selector", "200x1600-explicit-mask", 5.0).measure():
        build_hybrid_selector_result(linear, saturation, mask, {}, node_id="selector")
