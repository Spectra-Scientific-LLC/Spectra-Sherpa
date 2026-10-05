"""Executable scientist-facing consumers for the final uncovered node families."""

from __future__ import annotations

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
from spectra_sherpa.app.services.dag.node_base import node_registry


def _spectral_dataset(matrix: np.ndarray, *, target: np.ndarray | None = None) -> SherpaDataset:
    values = np.asarray(matrix, dtype=np.float64)
    return SherpaDataset(
        X=values,
        feature_axis=SpectralAxis(
            values=np.linspace(900.0, 1_800.0, values.shape[1]),
            units="cm-1",
            title="Wavenumber",
        ),
        sample_axis=SampleAxis(labels=[f"sample-{index}" for index in range(values.shape[0])]),
        target=target,
        target_context=(
            None
            if target is None
            else TargetContext(target_type="continuous", target_name="reference", target_units="%")
        ),
        units="absorbance",
        data_role="X_spectra",
    )


@pytest.mark.asyncio
async def test_custom_mixture_design_executes_curves_synthetic_source_and_common_grid() -> None:
    """The four uncovered generators/alignment steps form one inspectable mixture-design project."""

    synthetic = await node_registry.create_node("data.synthetic_curve", "source", {}).execute()
    catmull = await node_registry.create_node("custom.catmull_rom_curve", "catmull", {}).execute()
    concentration = await node_registry.create_node("custom.concentration_curve", "concentration", {}).execute()

    assert isinstance(synthetic, SherpaDataset)
    catmull_values = np.asarray(catmull.outputs["default"], dtype=np.float64).reshape(1, -1)
    concentration_values = np.asarray(concentration.outputs["default"], dtype=np.float64).reshape(1, -1)
    left = _spectral_dataset(catmull_values)
    right = _spectral_dataset(concentration_values)
    aligned = await node_registry.create_node(
        "custom.golden_grid_align",
        "align",
        {
            "coverage_policy": "common_overlap",
            "extrapolation": "reject",
            "max_upsampling_factor": 1.0,
            "merge_tolerance": 0.05,
            "method": "linear",
        },
    ).execute(default=[left, right])

    project = aligned.outputs["default"]
    assert project.shape == (2, 100)
    assert project.sample_axis.sample_table["golden_grid_source_index"] == [0, 1]
    assert np.isfinite(project.X).all()


@pytest.mark.asyncio
async def test_custom_calibration_and_selection_compares_linear_and_saturation_responses() -> None:
    """An explicit upstream mask chooses between calibrated linear and nonlinear responses."""

    features = 12
    concentrations = np.asarray([0.0, 5.0, 10.0, 20.0])
    sensitivity = SherpaDataset(
        X=np.linspace(0.005, 0.025, features).reshape(1, -1),
        feature_axis=SpectralAxis(values=np.linspace(900.0, 1_800.0, features), units="cm-1"),
        units="absorbance/ppm",
        title="Sensitivity",
        extra={
            "reference_applied": True,
            "calibration": {
                "concentration_unit": "ppm",
                "slope": np.linspace(0.005, 0.025, features).tolist(),
                "intercept": np.zeros(features).tolist(),
            },
        },
    )
    linear = await node_registry.create_node("custom.linear_calibration", "linear", {}).execute(
        spectrum=sensitivity,
        concentrations=concentrations,
    )
    saturated = await node_registry.create_node("custom.saturation_model", "saturation", {}).execute(
        sensitivity=sensitivity,
        saturation_levels=np.linspace(0.8, 1.2, features),
        shape_exponents=np.linspace(1.0, 1.8, features),
        concentrations=concentrations,
        calibration_minimum=0.0,
        calibration_maximum=20.0,
    )
    mask = np.arange(features) % 2
    selected = await node_registry.create_node("custom.hybrid_selector", "selector", {}).execute(
        linear_result=linear.outputs["default"],
        saturation_result=saturated.outputs["default"],
        model_mask=mask,
    )

    expected = np.where(
        mask[np.newaxis, :].astype(bool),
        saturated.outputs["default"].X,
        linear.outputs["default"].X,
    )
    np.testing.assert_array_equal(selected.outputs["default"].X, expected)
    assert selected.diagnostics["selection_authority"] == "upstream_explicit_mask"


@pytest.mark.asyncio
async def test_instrument_response_simulation_retains_noise_and_both_saturation_authorities() -> None:
    """Seeded measurement noise and explicit detector responses stay separate and inspectable."""

    source = _spectral_dataset(np.full((24, 32), 0.5, dtype=np.float64))
    noisy = await node_registry.create_node(
        "custom.noise_injection",
        "noise",
        {"noise_level": 0.002, "noise_type": "absolute", "seed": 20260902},
    ).execute(input_data=source)
    system = await node_registry.create_node(
        "custom.system_saturation",
        "system",
        {"s_system": 1.0, "p_system": 1.5},
    ).execute(input_data=noisy.outputs["default"])

    sensitivity = SherpaDataset(
        X=np.linspace(0.005, 0.02, 32).reshape(1, -1),
        feature_axis=source.feature_axis.copy(),
        units="absorbance/ppm",
    )
    calibrated = await node_registry.create_node("custom.saturation_model", "calibrated", {}).execute(
        sensitivity=sensitivity,
        saturation_levels=np.linspace(0.8, 1.2, 32),
        shape_exponents=np.linspace(1.0, 2.0, 32),
        concentrations=np.asarray([0.0, 10.0, 20.0]),
        calibration_minimum=0.0,
        calibration_maximum=20.0,
    )

    assert system.outputs["default"].shape == source.shape
    assert calibrated.outputs["default"].shape == (3, 32)
    assert np.isfinite(system.outputs["default"].X).all()
    assert np.isfinite(calibrated.outputs["default"].X).all()


@pytest.mark.asyncio
async def test_regression_model_comparison_uses_one_dataset_target_and_prediction_scope() -> None:
    """Linear regression, PCR, PLS, and SVR see one exact calibration problem."""

    rng = np.random.default_rng(20260902)
    matrix = rng.normal(size=(72, 24))
    target = 1.5 * matrix[:, 3] - 0.7 * matrix[:, 9] + 0.2 * matrix[:, 14]
    target += rng.normal(scale=0.03, size=matrix.shape[0])
    dataset = _spectral_dataset(matrix, target=target)
    operations = {
        "linear": node_registry.create_node("model.linear_regression", "linear", {}),
        "pcr": node_registry.create_node("model.pcr", "pcr", {"n_components": 6, "scale": True}),
        "pls": node_registry.create_node("model.fitted_pls", "pls", {"n_components": 4, "scale": True}),
        "svr": node_registry.create_node(
            "model.svr",
            "svr",
            {
                "kernel": "linear",
                "C": 10.0,
                "epsilon": 0.01,
                "gamma": "scale",
                "degree": 3,
                "coef0": 0.0,
                "target_index": 1,
                "scale": True,
            },
        ),
    }
    results = {
        "linear": await operations["linear"].execute(X=dataset, y=target),
        "pcr": await operations["pcr"].execute(X=dataset, y=target),
        "pls": await operations["pls"].execute(input_data=dataset, y=target),
        "svr": await operations["svr"].execute(X=dataset, y=target),
    }

    projected = {name: (result if isinstance(result, dict) else result.outputs) for name, result in results.items()}
    prediction_keys = {"linear": "predictions", "pcr": "y_pred", "pls": "default", "svr": "predictions"}
    for name, output in projected.items():
        predictions = np.asarray(output[prediction_keys[name]], dtype=np.float64).reshape(-1)
        assert predictions.shape == target.shape, name
        assert np.isfinite(predictions).all(), name
    assert {projected[name]["_model_artifact"]["metadata"]["model_type"] for name in ("linear", "pcr", "svr")} == {
        "linear_regression",
        "pcr",
        "svr",
    }
    assert projected["pls"]["fitted_state"]["serializer"] == "spectra.sherpa-simpls-regression-json/9"


@pytest.mark.asyncio
async def test_variable_selection_comparison_adds_ipls_and_audits_its_training_owned_result() -> None:
    """iPLS participates in the common selection question and emits a bounded audit record."""

    rng = np.random.default_rng(20260903)
    matrix = rng.normal(size=(60, 48))
    target = 1.8 * matrix[:, 17] - 0.9 * matrix[:, 18] + rng.normal(scale=0.04, size=60)
    dataset = _spectral_dataset(matrix, target=target)
    selected = await node_registry.create_node(
        "selection.ipls",
        "ipls",
        {
            "n_intervals": 6,
            "max_components": 3,
            "cv_folds": 4,
            "cv_order": "sorted_target",
            "random_seed": 42,
        },
    ).execute(X=dataset, y=target)
    audited = await node_registry.create_node(
        "selection.audit",
        "audit",
        {"include_scores": False},
    ).execute(X=selected.outputs["X_selected"])

    report = audited.outputs["audit"]
    assert report["methods_applied"] == ["selection.ipls"]
    assert report["n_selection_steps"] == 1
    assert report["feature_axis"]["selection_scores"] is None
    assert len(report["feature_axis"]["selection_scores_sha256"]) == 64


@pytest.mark.asyncio
async def test_spectral_response_map_executes_the_contour_consumer() -> None:
    """A measured response matrix produces an axis-faithful scientist-facing map."""

    sample_positions = np.linspace(0.0, 1.0, 18)
    axis = np.linspace(900.0, 1_800.0, 64)
    response = np.vstack(
        [
            np.exp(-0.5 * ((axis - (1_150.0 + 180.0 * position)) / 45.0) ** 2)
            + 0.35 * np.exp(-0.5 * ((axis - 1_550.0) / 70.0) ** 2)
            for position in sample_positions
        ]
    )
    dataset = SherpaDataset(
        X=response,
        feature_axis=SpectralAxis(values=axis, units="cm-1", title="Wavenumber"),
        sample_axis=SampleAxis(
            values=sample_positions,
            labels=[f"response-{index:02d}" for index in range(response.shape[0])],
            units="fraction",
            title="Mixture fraction",
        ),
        units="absorbance",
        data_role="X_spectra",
    )

    result = await node_registry.create_node(
        "output.contour",
        "response_map",
        {"plot_type": "heatmap", "colorscale": "Viridis", "reverse_x": False},
    ).execute(input_data=dataset)

    trace = result["visualization"]["data"][0]
    np.testing.assert_allclose(trace["x"], axis)
    np.testing.assert_allclose(trace["y"], sample_positions)
    np.testing.assert_allclose(trace["z"], response)
    assert result["visualization"]["layout"]["xaxis"]["title"] == "Wavenumber (cm-1)"


@pytest.mark.asyncio
async def test_process_monitoring_executes_trend_removal_then_moving_windows() -> None:
    """A time-ordered process project retains explicit windows after detrending."""

    time = np.arange(40, dtype=np.float64)
    axis = np.linspace(200.0, 800.0, 24)
    stationary_signal = np.sin(axis / 75.0)[np.newaxis, :]
    drift = time[:, np.newaxis] * np.linspace(0.001, 0.004, axis.size)[np.newaxis, :]
    excursion = (time[:, np.newaxis] >= 24.0) * np.exp(-0.5 * ((axis - 510.0) / 35.0) ** 2)
    source = SherpaDataset(
        X=stationary_signal + drift + 0.08 * excursion,
        feature_axis=SpectralAxis(values=axis, units="nm", title="Emission wavelength"),
        sample_axis=SampleAxis(
            values=time,
            labels=[f"batch-{index:02d}" for index in range(time.size)],
            units="cycle",
            title="Process cycle",
        ),
        units="intensity",
        data_role="X_spectra",
    )

    detrended = await node_registry.create_node(
        "time_series.trend_removal",
        "detrend",
        {"method": "linear"},
    ).execute(input_data=source)
    windowed = await node_registry.create_node(
        "time_series.moving_window",
        "window",
        {"window_size": 8, "step_size": 4, "aggregation": "mean"},
    ).execute(input_data=detrended)

    result = windowed
    assert result.shape == (9, 24)
    assert result.sample_axis.labels[0] == "window-0000:source-000000-000008"
    assert result.sample_axis.labels[-1] == "window-0008:source-000032-000040"
    assert result.meta["time_series_windows"]["window_intervals"] == [[start, start + 8] for start in range(0, 33, 4)]
    assert np.isfinite(result.X).all()
    assert [entry.op_id for entry in result.provenance[-2:]] == [
        "time_series.trend_removal",
        "time_series.moving_window",
    ]
