"""Canonical contracts and numerical-path tests for spectral cleaning nodes."""

from __future__ import annotations

import asyncio
import json
import math
import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.executor_pool import WorkerExecutionContext, _run_node_in_worker
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.preprocessing.clip_floor_node import (
    ClipFloorNode,
    _clip_floor_dispatch,
)
from spectra_sherpa.app.services.dag.nodes.preprocessing.cosmic_ray_node import (
    _COSMIC_RAY_BYTES_PER_WINDOW_VALUE,
    _COSMIC_RAY_WORKING_SET_BYTES,
    CosmicRayRemovalNode,
    _cosmic_ray_block_shape,
    _cosmic_ray_dispatch,
)
from spectra_sherpa.core.execution_runtime import ExecutionRuntime
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)
from tests.performance_contract import PerformanceCeiling


def _spectra() -> SherpaDataset:
    return SherpaDataset(
        X=np.array(
            [
                [1.0, 2.0, 3.0, 20.0, 5.0, 6.0, 7.0],
                [-5.0, -1.0, 0.0, 1.0, 2.0, 3.0, 8.0],
            ]
        ),
        feature_axis=SpectralAxis(
            values=np.linspace(1_000.0, 1_600.0, 7),
            units="cm-1",
            title="Wavenumber",
        ),
        sample_axis=SampleAxis(
            values=np.array([10.0, 11.0]),
            labels=["sample-a", "sample-b"],
            title="Sample",
        ),
        units="absorbance",
        data_role="X_spectra",
        title="Cleaning fixture",
    )


def _scalar_cosmic_ray_reference(
    data: np.ndarray,
    *,
    window: int,
    zscore: float,
) -> tuple[np.ndarray, dict[str, object]]:
    """Literal pre-optimization Hampel implementation used as a parity oracle."""

    matrix = np.asarray(data, dtype=np.float64)
    was_vector = matrix.ndim == 1
    if was_vector:
        matrix = matrix.reshape(1, -1)
    half_window = window // 2
    corrected = matrix.copy()
    corrected_mask = np.zeros(matrix.shape, dtype=bool)
    replacement_values = np.zeros(matrix.shape, dtype=np.float64)
    zero_mad_windows = 0
    for sample_index, spectrum in enumerate(matrix):
        for feature_index in range(half_window, spectrum.size - half_window):
            neighborhood = spectrum[feature_index - half_window : feature_index + half_window + 1]
            median = float(np.median(neighborhood))
            deviations = np.abs(neighborhood - median)
            mad = float(np.median(deviations))
            zero_mad_windows += int(mad == 0.0)
            numerical_floor = float(
                np.finfo(np.float64).eps * max(1.0, abs(median), float(np.max(np.abs(neighborhood))))
            )
            robust_scale = 1.4826 * mad
            scale = robust_scale if robust_scale >= numerical_floor else numerical_floor
            if abs(float(spectrum[feature_index]) - median) > zscore * scale:
                corrected_mask[sample_index, feature_index] = True
                replacement_values[sample_index, feature_index] = median
    corrected[corrected_mask] = replacement_values[corrected_mask]
    corrections = np.abs(matrix[corrected_mask] - corrected[corrected_mask])
    corrected_count = int(corrected_mask.sum())
    maximum_correction = float(corrections.max()) if corrected_count else 0.0
    mean_correction = (
        float(maximum_correction * np.mean(corrections / maximum_correction)) if maximum_correction else 0.0
    )
    diagnostics: dict[str, object] = {
        "method": "hampel_local_median_mad",
        "window": window,
        "zscore": zscore,
        "mad_normal_consistency": 1.4826,
        "simultaneous_replacement": True,
        "edge_points_unassessed_per_spectrum": 2 * half_window,
        "zero_mad_windows": zero_mad_windows,
        "corrected_values": corrected_count,
        "corrected_fraction": float(corrected_count / matrix.size),
        "spectra_with_corrections": int(np.any(corrected_mask, axis=1).sum()),
        "maximum_absolute_correction": maximum_correction,
        "mean_absolute_correction": mean_correction,
    }
    return (corrected[0] if was_vector else corrected), diagnostics


def test_cleaning_nodes_have_representative_absolute_performance_ceilings() -> None:
    rng = np.random.default_rng(20260902)
    spectra = rng.normal(size=(200, 1_600))
    spectra[:, 731] += 25.0

    with PerformanceCeiling("preprocess.clip_floor", "200x1600", 5.0).measure():
        clipped, clip_diagnostics = _clip_floor_dispatch(spectra, floor=-2.5)

    with PerformanceCeiling("preprocess.cosmic_ray", "200x1600-window-seven", 5.0).measure():
        cleaned, cosmic_diagnostics = _cosmic_ray_dispatch(spectra, window=7, zscore=5.0)

    assert clipped.shape == cleaned.shape == spectra.shape
    assert clip_diagnostics["clipped_values"] > 0
    assert cosmic_diagnostics["corrected_values"] > 0


@pytest.mark.parametrize(
    ("node_type", "implementation_id"),
    [
        ("preprocess.cosmic_ray", "spectrasherpa.preprocess.cosmic_ray"),
        ("preprocess.clip_floor", "spectrasherpa.preprocess.clip_floor"),
    ],
)
def test_cleaning_node_has_one_closed_local_contract(
    node_type: str,
    implementation_id: str,
) -> None:
    metadata = node_registry.get_metadata(node_type)
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["operation_id"] == node_type
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
    assert contract.payload["implementation_id"] == implementation_id
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["required_worker_capabilities"] == (WorkerCapability.READ_DATASET.value,)
    assert metadata.input_types == ["SpectralDataset"]
    assert metadata.output_type == "SpectralDataset"
    assert metadata.input_ports[0].accepted_data_roles == ["X_spectra"]
    assert metadata.output_ports[0].accepted_data_roles == ["X_spectra"]


def test_cosmic_ray_admission_preserves_exact_explicit_parameters() -> None:
    node = node_registry.create_node(
        "preprocess.cosmic_ray",
        "cosmic",
        {"window": 9, "zscore": 4},
    )

    assert node.parameters == {"window": 9, "zscore": 4.0}


@pytest.mark.parametrize(
    "parameters",
    [
        {"window": 2, "zscore": 3.0},
        {"window": 4, "zscore": 3.0},
        {"window": 103, "zscore": 3.0},
        {"window": 5.0, "zscore": 3.0},
        {"window": True, "zscore": 3.0},
        {"window": 5, "zscore": 1.49},
        {"window": 5, "zscore": float("nan")},
        {"window": 5, "zscore": True},
        {"window": 5, "zscore": 3.0, "technique": "raman"},
    ],
)
def test_cosmic_ray_admission_rejects_coercion_hidden_and_out_of_bounds_parameters(
    parameters: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        node_registry.create_node("preprocess.cosmic_ray", "cosmic", parameters)


@pytest.mark.parametrize(
    "parameters",
    [
        {"floor": float("nan")},
        {"floor": float("inf")},
        {"floor": True},
        {"floor": "0"},
        {"floor": 0.0, "automatic_offset": True},
    ],
)
def test_clip_floor_admission_rejects_coercion_hidden_and_nonfinite_parameters(
    parameters: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        node_registry.create_node("preprocess.clip_floor", "floor", parameters)


def test_cosmic_ray_matches_frozen_hampel_reference_and_preserves_unassessed_edges() -> None:
    spectrum = np.array([10.0, 2.0, 3.0, 20.0, 5.0, 6.0, -10.0])

    corrected, diagnostics = _cosmic_ray_dispatch(spectrum, window=5, zscore=3.0)

    np.testing.assert_array_equal(
        corrected,
        np.array([10.0, 2.0, 3.0, 5.0, 5.0, 6.0, -10.0]),
    )
    assert diagnostics == {
        "method": "hampel_local_median_mad",
        "window": 5,
        "zscore": 3.0,
        "mad_normal_consistency": 1.4826,
        "simultaneous_replacement": True,
        "edge_points_unassessed_per_spectrum": 4,
        "zero_mad_windows": 0,
        "corrected_values": 1,
        "corrected_fraction": 1 / 7,
        "spectra_with_corrections": 1,
        "maximum_absolute_correction": 15.0,
        "mean_absolute_correction": 15.0,
    }

    metadata = node_registry.get_metadata("preprocess.cosmic_ray")
    window_parameter = next(parameter for parameter in metadata.parameters if parameter.name == "window")
    assert "preserved unassessed" in metadata.description
    assert window_parameter.description is not None
    assert "preserved unassessed" in window_parameter.description


@pytest.mark.parametrize("window", [3, 5, 11, 31])
def test_vectorized_cosmic_ray_is_bit_identical_to_the_scalar_rule(window: int) -> None:
    rng = np.random.default_rng(20260810 + window)
    spectra = rng.normal(size=(5, 67))
    spectra[0, 33] = 50.0
    spectra[1, 20:25] = 0.0
    spectra[2] = 1.0

    expected, expected_diagnostics = _scalar_cosmic_ray_reference(
        spectra,
        window=window,
        zscore=3.5,
    )
    actual, actual_diagnostics = _cosmic_ray_dispatch(
        spectra,
        window=window,
        zscore=3.5,
    )

    np.testing.assert_array_equal(actual, expected)
    assert actual_diagnostics == expected_diagnostics


def test_cosmic_ray_vectorization_uses_bounded_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    import spectra_sherpa.app.services.dag.nodes.preprocessing.cosmic_ray_node as cosmic_module

    samples = 96
    features = 1_600
    window = 101
    sample_block, window_block = _cosmic_ray_block_shape(samples=samples, features=features, window=window)
    assert 1 <= sample_block < samples
    assert window_block == features - window + 1
    assert sample_block * window_block * window * _COSMIC_RAY_BYTES_PER_WINDOW_VALUE <= _COSMIC_RAY_WORKING_SET_BYTES

    original_median = np.median
    calls = 0

    def counted_median(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_median(*args, **kwargs)

    monkeypatch.setattr(cosmic_module.np, "median", counted_median)
    _cosmic_ray_dispatch(np.ones((samples, features)), window=window, zscore=3.0)

    assert calls == 2 * math.ceil(samples / sample_block)


def test_cosmic_ray_block_planner_bounds_one_exceptionally_wide_spectrum() -> None:
    samples = 1
    features = 10_000_000
    window = 101

    sample_block, window_block = _cosmic_ray_block_shape(
        samples=samples,
        features=features,
        window=window,
    )

    assert sample_block == 1
    assert window_block < features - window + 1
    assert window_block * window * _COSMIC_RAY_BYTES_PER_WINDOW_VALUE <= _COSMIC_RAY_WORKING_SET_BYTES


def test_cosmic_ray_feature_block_boundaries_preserve_the_scalar_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import spectra_sherpa.app.services.dag.nodes.preprocessing.cosmic_ray_node as cosmic_module

    window = 11
    rng = np.random.default_rng(20260811)
    spectra = rng.normal(size=(5, 67))
    spectra[1, 8] = 75.0
    spectra[3, 55] = -60.0
    expected, expected_diagnostics = _scalar_cosmic_ray_reference(
        spectra,
        window=window,
        zscore=3.5,
    )
    monkeypatch.setattr(
        cosmic_module,
        "_COSMIC_RAY_WORKING_SET_BYTES",
        window * _COSMIC_RAY_BYTES_PER_WINDOW_VALUE * 8,
    )

    sample_block, window_block = _cosmic_ray_block_shape(
        samples=spectra.shape[0],
        features=spectra.shape[1],
        window=window,
    )
    actual, actual_diagnostics = _cosmic_ray_dispatch(
        spectra,
        window=window,
        zscore=3.5,
    )

    assert sample_block == 1
    assert window_block == 8
    assert math.ceil((spectra.shape[1] - window + 1) / window_block) > 1
    np.testing.assert_array_equal(actual, expected)
    assert actual_diagnostics == expected_diagnostics


def test_cosmic_ray_detection_is_order_independent() -> None:
    spectrum = np.array([0.0, 1.0, 2.0, 30.0, 4.0, 5.0, 6.0, 7.0, 8.0])

    forward, _ = _cosmic_ray_dispatch(spectrum, window=5, zscore=3.0)
    reverse, _ = _cosmic_ray_dispatch(spectrum[::-1], window=5, zscore=3.0)

    np.testing.assert_array_equal(forward, reverse[::-1])
    np.testing.assert_array_equal(forward, np.array([0.0, 1.0, 2.0, 4.0, 4.0, 5.0, 6.0, 7.0, 8.0]))


def test_cosmic_ray_rule_preserves_a_resolved_broad_peak() -> None:
    broad_peak = np.array([0.0, 1.0, 3.0, 5.0, 3.0, 1.0, 0.0])

    corrected, diagnostics = _cosmic_ray_dispatch(broad_peak, window=5, zscore=3.0)

    np.testing.assert_array_equal(corrected, broad_peak)
    assert diagnostics["corrected_values"] == 0


def test_zero_mad_windows_are_explicit_and_flat_values_remain_unchanged() -> None:
    spectrum = np.ones(7)

    corrected, diagnostics = _cosmic_ray_dispatch(spectrum, window=3, zscore=3.0)

    np.testing.assert_array_equal(corrected, spectrum)
    assert diagnostics["zero_mad_windows"] == 5
    assert diagnostics["corrected_values"] == 0


@pytest.mark.parametrize(
    "data",
    [
        np.array([[1.0, 2.0]]),
        np.array([[1.0, float("nan"), 3.0]]),
        np.empty((0, 7)),
        np.empty((1, 2, 3)),
    ],
)
def test_cosmic_ray_rejects_unusable_or_nonfinite_spectra(data: np.ndarray) -> None:
    with pytest.raises(ValueError):
        _cosmic_ray_dispatch(data, window=3, zscore=3.0)


def test_clip_floor_matches_literal_reference_and_quantifies_changes() -> None:
    source = np.array([[-2.0, 0.0, 1.0], [-0.5, 2.0, 3.0]])

    clipped, diagnostics = _clip_floor_dispatch(source, floor=0.25)

    np.testing.assert_array_equal(clipped, np.array([[0.25, 0.25, 1.0], [0.25, 2.0, 3.0]]))
    assert diagnostics == {
        "floor": 0.25,
        "clipped_values": 3,
        "clipped_fraction": 0.5,
        "samples_with_clipping": 2,
        "maximum_upward_adjustment": 2.25,
        "mean_upward_adjustment": 13 / 12,
        "input_minimum": -2.0,
        "output_minimum": 0.25,
    }


def test_clip_floor_zero_change_is_reported_without_inventing_an_effect() -> None:
    source = np.array([[1.0, 2.0, 3.0]])

    clipped, diagnostics = _clip_floor_dispatch(source, floor=0.0)

    np.testing.assert_array_equal(clipped, source)
    assert diagnostics["clipped_values"] == 0
    assert diagnostics["samples_with_clipping"] == 0
    assert diagnostics["maximum_upward_adjustment"] == 0.0
    assert diagnostics["mean_upward_adjustment"] == 0.0


@pytest.mark.parametrize(
    "data",
    [
        np.array([[1.0, float("inf")]]),
        np.empty((0, 2)),
        np.empty((1, 0)),
        np.empty((1, 2, 3)),
    ],
)
def test_clip_floor_rejects_empty_nonfinite_or_nonspectral_matrices(data: np.ndarray) -> None:
    with pytest.raises(ValueError):
        _clip_floor_dispatch(data, floor=0.0)


def test_extreme_finite_inputs_fail_before_nonfinite_diagnostics_escape() -> None:
    with pytest.raises(ValueError, match="not finitely representable"):
        _clip_floor_dispatch(np.array([[-1e308, 0.0]]), floor=1e308)

    with pytest.raises(ValueError, match="not finitely representable"):
        _cosmic_ray_dispatch(
            np.array([[-1e308, 1e308, -1e308]]),
            window=3,
            zscore=3.0,
        )


def test_extreme_representable_impacts_have_overflow_safe_means() -> None:
    _, floor_diagnostics = _clip_floor_dispatch(
        np.array([[-1e307, -1e307]]),
        floor=1e308,
    )
    assert np.isfinite(floor_diagnostics["mean_upward_adjustment"])
    assert floor_diagnostics["mean_upward_adjustment"] == pytest.approx(1.1e308)

    _, cosmic_diagnostics = _cosmic_ray_dispatch(
        np.array(
            [
                [1e308, 1e308, -1e307, 1e308, 1e308],
                [1e308, 1e308, -1e307, 1e308, 1e308],
            ]
        ),
        window=5,
        zscore=3.0,
    )
    assert cosmic_diagnostics["corrected_values"] == 2
    assert np.isfinite(cosmic_diagnostics["mean_absolute_correction"])
    assert cosmic_diagnostics["mean_absolute_correction"] == pytest.approx(1.1e308)


@pytest.mark.parametrize(
    ("node_class", "parameters", "expected_dispatch", "diagnostic_key", "impact_schema"),
    [
        (
            CosmicRayRemovalNode,
            {"window": 5, "zscore": 3.0},
            _cosmic_ray_dispatch,
            "cosmic_ray_diagnostics",
            "spectrasherpa-preprocess-cosmic-ray-impact/1",
        ),
        (
            ClipFloorNode,
            {"floor": 0.5},
            _clip_floor_dispatch,
            "clip_floor_diagnostics",
            "spectrasherpa-preprocess-clip-floor-impact/1",
        ),
    ],
)
def test_dag_and_generated_python_share_numeric_provenance_and_diagnostics(
    node_class,
    parameters: dict[str, object],
    expected_dispatch,
    diagnostic_key: str,
    impact_schema: str,
) -> None:
    source = _spectra()
    node = node_class("clean", parameters)
    expected, expected_diagnostics = expected_dispatch(source.X, **parameters)

    node_result = asyncio.run(node.execute(input_data=source))
    generated_source = "\n".join(node.generate_python({"default": "source"}, indent="", use_scp=False))
    namespace = {"np": np, "results": {}, "source": source}
    exec(compile(generated_source, "<canonical cleaning export>", "exec"), namespace)
    generated = namespace["results"]["clean"]

    np.testing.assert_array_equal(node_result.outputs["default"].X, expected)
    np.testing.assert_array_equal(generated.X, expected)
    expected_result_diagnostics = {**expected_diagnostics, "value_units": "absorbance"}
    assert node_result.diagnostics == expected_result_diagnostics
    assert generated.meta[diagnostic_key] == expected_result_diagnostics
    assert dict(node_result.outputs["default"].provenance[-1].parameters) == parameters
    assert dict(generated.provenance[-1].parameters) == parameters
    expected_impact = {
        "schema_version": impact_schema,
        **expected_result_diagnostics,
    }
    assert dict(node_result.outputs["default"].provenance[-1].impact or {}) == expected_impact
    assert dict(generated.provenance[-1].impact or {}) == expected_impact
    with pytest.raises(TypeError):
        generated.provenance[-1].impact["schema_version"] = "changed"  # type: ignore[index]
    json.dumps(node_result.outputs["default"].provenance.to_list(), allow_nan=False)
    json.dumps(node_result.diagnostics, allow_nan=False)
    assert generated.provenance[-1].node_id == "clean"
    np.testing.assert_array_equal(generated.feature_axis.values, source.feature_axis.values)
    assert generated.feature_axis.units == source.feature_axis.units
    assert generated.feature_axis.title == source.feature_axis.title
    np.testing.assert_array_equal(generated.sample_axis.values, source.sample_axis.values)
    assert generated.sample_axis.labels == source.sample_axis.labels
    assert generated.sample_axis.title == source.sample_axis.title
    assert generated.units == "absorbance"
    assert generated.data_role == "X_spectra"


def test_cleaning_nodes_execute_in_a_real_spawned_worker() -> None:
    source = _spectra()
    context = WorkerExecutionContext(
        execution_id="canonical-cleaning",
        runtime=ExecutionRuntime(),
        capabilities=(WorkerCapability.READ_DATASET.value,),
        origin_pid=os.getpid(),
    )
    try:
        pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    except (NotImplementedError, PermissionError, OSError) as exc:
        pytest.skip(f"spawn worker unavailable: {exc}")
    try:
        cosmic = pool.submit(
            _run_node_in_worker,
            "preprocess.cosmic_ray",
            "cosmic",
            {"window": 5, "zscore": 3.0},
            (source,),
            {},
            context,
        ).result(timeout=30)
        floor = pool.submit(
            _run_node_in_worker,
            "preprocess.clip_floor",
            "floor",
            {"floor": 0.0},
            (source,),
            {},
            context,
        ).result(timeout=30)
    finally:
        pool.shutdown(wait=True)

    np.testing.assert_array_equal(
        cosmic.outputs["default"].X,
        _cosmic_ray_dispatch(source.X, window=5, zscore=3.0)[0],
    )
    np.testing.assert_array_equal(
        floor.outputs["default"].X,
        _clip_floor_dispatch(source.X, floor=0.0)[0],
    )
    for result in (cosmic, floor):
        worker = result.diagnostics["worker_execution"]
        assert worker["mode"] == "spawned_worker"
        assert worker["origin_pid"] == os.getpid()
        assert worker["worker_pid"] != os.getpid()


@pytest.mark.parametrize(
    ("node_type", "parameters"),
    [
        ("preprocess.cosmic_ray", {"window": 5, "zscore": 3.0}),
        ("preprocess.clip_floor", {"floor": 0.0}),
    ],
)
def test_cleaning_nodes_require_their_declared_dataset_capability(
    node_type: str,
    parameters: dict[str, object],
) -> None:
    context = WorkerExecutionContext(
        execution_id="canonical-cleaning-denied", runtime=ExecutionRuntime(), origin_pid=os.getpid()
    )

    with pytest.raises(PermissionError, match="worker capabilities are missing"):
        _run_node_in_worker(
            node_type,
            "clean",
            parameters,
            (_spectra(),),
            {},
            context,
        )


def test_parallel_cleaning_implementation_and_generated_math_are_absent() -> None:
    package_root = Path(__file__).resolve().parents[1]
    preprocessing_root = package_root / "src/spectra_sherpa/app/services/dag/nodes/preprocessing"
    legacy_transform = preprocessing_root / "_transforms.py"
    retired_builder_preprocessing = package_root / "src/spectra_sherpa/app/lib/preprocessing.py"

    assert not legacy_transform.exists()
    assert not retired_builder_preprocessing.exists()
