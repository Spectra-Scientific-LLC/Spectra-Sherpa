"""Canonical custom calibration and Gaussian-noise contract proofs."""

from __future__ import annotations

import copy

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.axes import SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.custom import LinearCalibrationNode, NoiseInjectionNode
from spectra_sherpa.app.services.dag.nodes.custom_contracts import (
    build_linear_calibration_result,
    build_noise_injection_result,
    canonical_linear_calibration_parameters,
    canonical_noise_injection_parameters,
    inject_gaussian_noise,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


def _calibrated_spectrum(*, features: int = 4) -> SherpaDataset:
    return SherpaDataset(
        X=np.linspace(0.1, 0.4, features, dtype=np.float64).reshape(1, -1),
        feature_axis=SpectralAxis(values=np.linspace(900.0, 1800.0, features), units="cm-1"),
        units="absorbance",
        title="Reference analyte",
        extra={
            "reference_applied": True,
            "calibration": {
                "concentration_unit": "ppm",
                "slope": np.linspace(0.01, 0.04, features).tolist(),
                "intercept": np.linspace(0.001, 0.004, features).tolist(),
            },
        },
    )


def _noise_dataset(*, samples: int = 8, features: int = 12) -> SherpaDataset:
    matrix = np.linspace(0.2, 1.4, samples * features, dtype=np.float64).reshape(samples, features)
    return SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(values=np.linspace(900.0, 1800.0, features), units="cm-1"),
        units="absorbance",
        title="Noise fixture",
    )


def test_custom_calibration_and_noise_publish_exact_local_contracts() -> None:
    calibration = node_registry.get_metadata("custom.linear_calibration").resolved_execution_contract()
    noise = node_registry.get_metadata("custom.noise_injection").resolved_execution_contract()

    assert calibration is not None
    assert calibration.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert calibration.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
    assert calibration.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert calibration.payload["sample_effect"] == "generates_samples"
    assert any("10.1351/goldbook.B00626" in citation for citation in calibration.payload["citations"])

    assert noise is not None
    assert noise.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert noise.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
    assert noise.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert noise.payload["deterministic"] is False
    assert noise.payload["seed_parameter"] == "seed"
    assert any("tdaunif::add_noise" in citation for citation in noise.payload["citations"])


def test_custom_parameter_grammars_are_closed_and_remove_ambiguous_legacy_modes() -> None:
    assert canonical_linear_calibration_parameters({"concentration_unit": "ppm"}) == {"concentration_unit": "ppm"}
    assert canonical_noise_injection_parameters({"noise_level": 0.02, "noise_type": "relative_rms", "seed": 42}) == {
        "noise_level": 0.02,
        "noise_type": "relative_rms",
        "seed": 42,
    }

    for invalid in (
        {},
        {"concentration_unit": "ppm", "s_max": 1.0},
        {"concentration_unit": "unknown"},
    ):
        with pytest.raises(ValueError):
            canonical_linear_calibration_parameters(invalid)
    for invalid in (
        {},
        {"noise_level": 0.01, "noise_type": "relative", "seed": 42},
        {"noise_level": -0.01, "noise_type": "absolute", "seed": 42},
        {"noise_level": 0.01, "noise_type": "absolute", "seed": 1.5},
        {"noise_level": 0.01, "noise_type": "absolute", "seed": True},
        {"noise_level": 0.01, "noise_type": "absolute", "seed": 42, "clip": True},
    ):
        with pytest.raises(ValueError):
            canonical_noise_injection_parameters(invalid)


@pytest.mark.asyncio
async def test_linear_calibration_live_and_generated_paths_share_the_affine_authority() -> None:
    spectrum = _calibrated_spectrum()
    concentrations = np.array([0.0, 2.0, 5.0])
    node = LinearCalibrationNode("linear", {"concentration_unit": "ppm"})

    live = await node.execute(spectrum=spectrum, concentrations=concentrations)
    namespace = {"spectrum": spectrum, "concentrations": concentrations, "results": {}}
    exec(
        "\n".join(node.generate_python({"spectrum": "spectrum", "concentrations": "concentrations"}, indent="")),
        namespace,
    )  # noqa: S102
    generated = namespace["results"]["linear"]

    slope = np.asarray(spectrum.meta["calibration"]["slope"])
    intercept = np.asarray(spectrum.meta["calibration"]["intercept"])
    expected = concentrations[:, np.newaxis] * slope[np.newaxis, :] + intercept[np.newaxis, :]
    np.testing.assert_array_equal(live.outputs["default"].X, expected)
    np.testing.assert_array_equal(generated.X, expected)
    assert generated.meta["calibration_digest"] == live.outputs["default"].meta["calibration_digest"]
    assert live.diagnostics["reference_applied"] is True


def test_linear_calibration_fails_closed_without_complete_declared_science() -> None:
    concentrations = np.array([1.0, 2.0])
    parameters = {"concentration_unit": "ppm"}
    spectrum = _calibrated_spectrum()

    missing_reference = copy.deepcopy(spectrum)
    missing_reference.meta.pop("reference_applied")
    missing_calibration = copy.deepcopy(spectrum)
    missing_calibration.meta.pop("calibration")
    wrong_unit = copy.deepcopy(spectrum)
    wrong_unit.meta["calibration"]["concentration_unit"] = "mg/L"
    wrong_shape = copy.deepcopy(spectrum)
    wrong_shape.meta["calibration"]["slope"] = [0.1]
    negative_slope = copy.deepcopy(spectrum)
    negative_slope.meta["calibration"]["slope"][0] = -0.1
    multiple_references = SherpaDataset(
        X=np.vstack([spectrum.X, spectrum.X]),
        feature_axis=spectrum.feature_axis,
        units=spectrum.units,
        extra=copy.deepcopy(spectrum.meta),
    )

    for invalid in (
        missing_reference,
        missing_calibration,
        wrong_unit,
        wrong_shape,
        negative_slope,
        multiple_references,
    ):
        with pytest.raises(ValueError):
            build_linear_calibration_result(invalid, concentrations, parameters, node_id="linear")
    with pytest.raises(ValueError, match="non-negative"):
        build_linear_calibration_result(spectrum, np.array([-1.0]), parameters, node_id="linear")


@pytest.mark.asyncio
async def test_noise_live_generated_and_core_paths_are_seed_reproducible() -> None:
    dataset = _noise_dataset()
    parameters = {"noise_level": 0.02, "noise_type": "relative_rms", "seed": 20260812}
    node = NoiseInjectionNode("noise", parameters)

    live = await node.execute(input_data=dataset)
    repeated = await node.execute(input_data=dataset)
    namespace = {"dataset": dataset, "results": {}}
    exec("\n".join(node.generate_python({"default": "dataset"}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["noise"]
    core, diagnostics = inject_gaussian_noise(np.asarray(dataset.X), parameters)

    np.testing.assert_array_equal(live.outputs["default"].X, repeated.outputs["default"].X)
    np.testing.assert_array_equal(live.outputs["default"].X, generated.X)
    np.testing.assert_array_equal(live.outputs["default"].X, core)
    assert live.diagnostics == diagnostics
    assert live.diagnostics["standard_deviation"] == pytest.approx(0.02 * np.sqrt(np.mean(np.square(dataset.X))))


def test_noise_uses_invocation_local_rng_and_rejects_invalid_data() -> None:
    dataset = _noise_dataset()
    parameters = {"noise_level": 0.01, "noise_type": "absolute", "seed": 42}

    np.random.seed(12345)
    first = np.random.random()
    inject_gaussian_noise(np.asarray(dataset.X), parameters)
    second = np.random.random()
    np.random.seed(12345)
    assert first == np.random.random()
    assert second == np.random.random()

    changed, _ = inject_gaussian_noise(np.asarray(dataset.X), {**parameters, "seed": 43})
    baseline, _ = inject_gaussian_noise(np.asarray(dataset.X), parameters)
    assert not np.array_equal(changed, baseline)
    with pytest.raises(ValueError, match="finite"):
        inject_gaussian_noise(np.array([[np.nan]]), parameters)
    with pytest.raises(ValueError, match="two-dimensional"):
        inject_gaussian_noise(np.empty((0, 3)), parameters)


def test_custom_calibration_and_noise_fixed_workloads_stay_inside_reviewed_ceilings() -> None:
    features = 1600
    spectrum = _calibrated_spectrum(features=features)
    concentrations = np.linspace(0.0, 100.0, 200)
    noise_dataset = _noise_dataset(samples=200, features=features)
    calibration_parameters = {"concentration_unit": "ppm"}
    noise_parameters = {"noise_level": 0.01, "noise_type": "relative_rms", "seed": 42}

    build_linear_calibration_result(spectrum, concentrations, calibration_parameters, node_id="linear")
    build_noise_injection_result(noise_dataset, noise_parameters, node_id="noise")
    with PerformanceCeiling("custom.linear_calibration", "200x1600-affine", 5.0).measure():
        build_linear_calibration_result(spectrum, concentrations, calibration_parameters, node_id="linear")
    with PerformanceCeiling("custom.noise_injection", "200x1600-gaussian", 5.0).measure():
        build_noise_injection_result(noise_dataset, noise_parameters, node_id="noise")
