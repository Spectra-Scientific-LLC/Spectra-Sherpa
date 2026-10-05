"""Canonical contract and numerical-path tests for wavenumber alignment."""

from __future__ import annotations

import asyncio
import json
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
from spectra_sherpa.app.services.dag.nodes.preprocessing.wavenumber_align_node import (
    WavenumberAlignNode,
    _wavenumber_align_dispatch,
)
from spectra_sherpa.core.execution_runtime import ExecutionRuntime
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)
from tests.performance_contract import PerformanceCeiling


def _spectra(*, descending: bool = False, units: str = "cm-1") -> SherpaDataset:
    coordinates = np.array([1000.0, 1001.0, 1002.0, 1003.0])
    X = np.array([[0.0, 1.0, 4.0, 9.0], [2.0, 3.0, 6.0, 11.0]])
    if descending:
        coordinates = coordinates[::-1]
        X = X[:, ::-1]
    return SherpaDataset(
        X=X,
        target=np.array([1.0, 2.0]),
        feature_axis=SpectralAxis(values=coordinates, units=units, title="Source wavenumber"),
        sample_axis=SampleAxis(
            values=np.array([10.0, 11.0]),
            labels=["sample-a", "sample-b"],
            sample_table={"batch": ["A", "B"]},
        ),
        units="absorbance",
        data_role="X_spectra",
        title="Alignment source",
        is_time_series=True,
    )


def _reference(
    coordinates: np.ndarray | None = None,
    *,
    units: str = "cm^-1",
) -> SherpaDataset:
    axis = np.array([1000.5, 1001.5, 1002.5]) if coordinates is None else np.asarray(coordinates, dtype=float)
    return SherpaDataset(
        X=np.full((1, axis.size), 12345.0),
        feature_axis=SpectralAxis(
            values=axis,
            units=units,
            title="Instrument transfer grid",
            quantity="wavenumber",
        ),
        sample_axis=SampleAxis(labels=["reference"]),
        units="absorbance",
        data_role="X_spectra",
        title="Reference instrument",
    )


def _scalar_sinc_reference(
    source_axis: np.ndarray,
    matrix: np.ndarray,
    target_axis: np.ndarray,
    *,
    spacing: float,
) -> np.ndarray:
    """Literal pre-optimization sinc loop used as a parity oracle."""

    output = np.empty((matrix.shape[0], target_axis.size), dtype=np.float64)
    for sample_index, spectrum in enumerate(matrix):
        for target_index, coordinate in enumerate(target_axis):
            distance = coordinate - source_axis
            mask = np.abs(distance) <= 8 * spacing
            weights = np.sinc(distance[mask] / spacing)
            output[sample_index, target_index] = np.dot(weights, spectrum[mask]) / weights.sum()
    return output


def test_wavenumber_alignment_has_a_representative_absolute_performance_ceiling() -> None:
    rng = np.random.default_rng(20260902)
    source_axis = np.linspace(400.0, 4_000.0, 1_600)
    reference_axis = np.linspace(450.0, 3_950.0, 1_400)
    spectra = rng.normal(size=(200, source_axis.size))

    with PerformanceCeiling("preprocess.wavenumber_align", "linear-200x1600-to-1400", 5.0).measure():
        aligned, diagnostics = _wavenumber_align_dispatch(
            spectra,
            source_axis,
            reference_axis,
            method="linear",
            extrapolation="reject",
        )

    assert aligned.shape == (200, 1_400)
    assert diagnostics["source_features"] == 1_600
    assert diagnostics["reference_features"] == 1_400


def test_wavenumber_align_has_one_closed_local_contract() -> None:
    metadata = node_registry.get_metadata("preprocess.wavenumber_align")
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["operation_id"] == "preprocess.wavenumber_align"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
    assert contract.payload["implementation_id"] == "spectrasherpa.preprocess.wavenumber_align"
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["required_worker_capabilities"] == (WorkerCapability.READ_DATASET.value,)
    assert contract.payload["feature_effect"] == "transforms_features"
    assert contract.payload["axis_effect"] == "changes_axis"
    assert [port.name for port in metadata.input_ports] == ["spectra", "reference"]
    assert [port.accepted_data_roles for port in metadata.input_ports] == [["X_spectra"], ["X_spectra"]]
    assert metadata.output_ports[0].accepted_data_roles == ["X_spectra"]
    assert metadata.input_types == ["SpectralDataset"]
    assert metadata.output_type == "SpectralDataset"


def test_wavenumber_align_admission_preserves_exact_parameters_and_defaults() -> None:
    explicit = node_registry.create_node(
        "preprocess.wavenumber_align",
        "align",
        {"method": "linear", "extrapolation": "reject"},
    )
    defaulted = node_registry.create_node("preprocess.wavenumber_align", "align-default", {})

    assert explicit.parameters == {"method": "linear", "extrapolation": "reject"}
    assert defaulted.parameters == {"method": "pchip", "extrapolation": "reject"}


@pytest.mark.parametrize(
    "parameters",
    [
        {"method": "cubic", "extrapolation": "reject"},
        {"method": "linear", "extrapolation": "linear"},
        {"method": "linear", "extrapolation": False},
        {"method": "linear", "extrapolation": "reject", "merge_tolerance": 0.5},
    ],
)
def test_wavenumber_align_rejects_incomplete_retired_or_unadmitted_parameters(
    parameters: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        node_registry.create_node("preprocess.wavenumber_align", "align", parameters)


@pytest.mark.parametrize(
    ("method", "expected"),
    [
        ("linear", np.array([[0.5, 2.5, 6.5], [2.5, 4.5, 8.5]])),
        ("pchip", np.array([[0.3125, 2.21875, 6.21875], [2.3125, 4.21875, 8.21875]])),
    ],
)
def test_wavenumber_align_has_frozen_linear_and_pchip_results(method: str, expected: np.ndarray) -> None:
    source = _spectra()
    reference = _reference()

    aligned, diagnostics = _wavenumber_align_dispatch(
        source.X,
        source.feature_axis.values,
        reference.feature_axis.values,
        method=method,
        extrapolation="reject",
    )

    np.testing.assert_allclose(aligned, expected, atol=1e-12, rtol=0.0)
    assert diagnostics["method"] == method
    assert diagnostics["extrapolation"] == "reject"
    assert diagnostics["source_direction"] == "increasing"
    assert diagnostics["reference_direction"] == "increasing"
    assert diagnostics["source_features"] == 4
    assert diagnostics["reference_features"] == 3
    assert diagnostics["reference_grid_sha256"] == "0f8531ab2d2a2f68ea5ff6145e771bc9bd61ea2a38ecbb16537db734828601a1"
    assert diagnostics["upsampled"] is False
    assert diagnostics["upsampling_factor"] == 1.0
    assert diagnostics["adds_measured_resolution"] is False
    assert diagnostics["resolution_note"] is None


def test_wavenumber_align_preserves_reference_direction() -> None:
    source = _spectra(descending=True)
    reference = _reference(np.array([1002.5, 1001.5, 1000.5]))

    aligned, diagnostics = _wavenumber_align_dispatch(
        source.X,
        source.feature_axis.values,
        reference.feature_axis.values,
        method="linear",
        extrapolation="reject",
    )

    np.testing.assert_allclose(aligned[0], [6.5, 2.5, 0.5])
    assert diagnostics["source_direction"] == "decreasing"
    assert diagnostics["reference_direction"] == "decreasing"


def test_sinc_alignment_reproduces_measured_points_and_rejects_nonuniform_source() -> None:
    source = _spectra()
    aligned, diagnostics = _wavenumber_align_dispatch(
        source.X,
        source.feature_axis.values,
        source.feature_axis.values,
        method="sinc",
        extrapolation="reject",
    )
    np.testing.assert_array_equal(aligned, source.X)
    assert diagnostics["identical_grid"] is True
    assert diagnostics["sinc_kernel_half_width"] == 8

    with pytest.raises(ValueError, match="uniformly spaced"):
        _wavenumber_align_dispatch(
            source.X,
            np.array([1000.0, 1001.0, 1002.2, 1003.0]),
            np.array([1000.5, 1001.5]),
            method="sinc",
            extrapolation="reject",
        )

    with pytest.raises(ValueError, match="uniformly spaced"):
        _wavenumber_align_dispatch(
            source.X,
            np.array([1000.0, 1001.0, 1002.2, 1003.0]),
            np.array([1000.0, 1001.0, 1002.2, 1003.0]),
            method="sinc",
            extrapolation="reject",
        )


@pytest.mark.parametrize("descending_source", [False, True])
@pytest.mark.parametrize("descending_reference", [False, True])
def test_precomputed_sinc_plan_matches_the_literal_exact_coordinate_rule(
    descending_source: bool,
    descending_reference: bool,
) -> None:
    rng = np.random.default_rng(20260810)
    source_axis = 1000.0 + np.arange(33, dtype=np.float64)
    source_axis[1::2] += 2.0e-10
    matrix = rng.normal(size=(7, source_axis.size))
    reference_axis = np.linspace(1000.25, 1031.75, 65)
    ascending_axis = source_axis.copy()
    ascending_matrix = matrix.copy()
    if descending_source:
        source_axis = source_axis[::-1]
        matrix = matrix[:, ::-1]
    if descending_reference:
        reference_axis = reference_axis[::-1]

    spacing = float(np.median(np.abs(np.diff(ascending_axis))))
    expected = _scalar_sinc_reference(
        ascending_axis,
        ascending_matrix,
        reference_axis,
        spacing=spacing,
    )
    actual, diagnostics = _wavenumber_align_dispatch(
        matrix,
        source_axis,
        reference_axis,
        method="sinc",
        extrapolation="reject",
    )

    np.testing.assert_allclose(actual, expected, rtol=2e-15, atol=2e-15)
    assert diagnostics["source_direction"] == ("decreasing" if descending_source else "increasing")
    assert diagnostics["reference_direction"] == ("decreasing" if descending_reference else "increasing")
    assert diagnostics["upsampled"] is True
    expected_factor = spacing / float(np.median(np.abs(np.diff(reference_axis))))
    assert diagnostics["upsampling_factor"] == pytest.approx(expected_factor)
    assert diagnostics["upsampling_factor"] > 2.0
    assert diagnostics["adds_measured_resolution"] is False
    assert diagnostics["resolution_note"] == (
        "Interpolation onto a finer grid does not add measured spectral resolution."
    )


def test_sinc_interpolation_plan_is_built_once_for_all_spectra(monkeypatch: pytest.MonkeyPatch) -> None:
    import spectra_sherpa.app.services.dag.nodes.preprocessing.wavenumber_align_node as align_module

    original_builder = align_module._sinc_interpolation_plan
    calls = 0

    def counted_builder(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original_builder(*args, **kwargs)

    monkeypatch.setattr(align_module, "_sinc_interpolation_plan", counted_builder)
    source_axis = np.arange(1_500, dtype=np.float64)
    reference_axis = np.arange(0.5, 1_499.0, 1.0)
    _wavenumber_align_dispatch(
        np.ones((20, source_axis.size)),
        source_axis,
        reference_axis,
        method="sinc",
        extrapolation="reject",
    )

    assert calls == 1


@pytest.mark.parametrize(
    "source_axis,reference_axis,error",
    [
        (np.array([1000.0, 1001.0, 1001.0, 1003.0]), np.array([1000.5, 1001.5]), "source axis"),
        (np.array([1000.0, 1001.0, 1002.0, 1003.0]), np.array([1000.5, 1002.5, 1001.5]), "reference axis"),
        (np.array([1000.0, np.nan, 1002.0, 1003.0]), np.array([1000.5, 1001.5]), "source axis"),
    ],
)
def test_wavenumber_align_rejects_invalid_axes(
    source_axis: np.ndarray,
    reference_axis: np.ndarray,
    error: str,
) -> None:
    with pytest.raises(ValueError, match=error):
        _wavenumber_align_dispatch(
            np.zeros((1, source_axis.size)),
            source_axis,
            reference_axis,
            method="linear",
            extrapolation="reject",
        )


@pytest.mark.parametrize(
    ("source_axis", "reference_axis", "error"),
    [
        (
            np.array([-np.finfo(np.float64).max, np.finfo(np.float64).max]),
            np.array([-1.0, 1.0]),
            "finitely representable",
        ),
        (
            np.array(
                [
                    0.0,
                    np.nextafter(0.0, 1.0),
                    np.nextafter(np.nextafter(0.0, 1.0), 1.0),
                    1.0,
                ]
            ),
            np.array([0.0, 1.0]),
            "spacing ratio",
        ),
    ],
)
def test_wavenumber_align_rejects_non_json_safe_spacing_evidence(
    source_axis: np.ndarray,
    reference_axis: np.ndarray,
    error: str,
) -> None:
    with pytest.raises(ValueError, match=error):
        _wavenumber_align_dispatch(
            np.zeros((1, source_axis.size)),
            source_axis,
            reference_axis,
            method="linear",
            extrapolation="reject",
        )


def test_wavenumber_align_rejects_extrapolation_nonfinite_data_and_wrong_units() -> None:
    source = _spectra()
    with pytest.raises(ValueError, match="outside"):
        asyncio.run(
            WavenumberAlignNode("align", {}).execute(
                spectra=source,
                reference=_reference(np.array([999.0, 1000.0, 1001.0])),
            )
        )
    source.X[0, 0] = np.nan
    with pytest.raises(ValueError, match="finite"):
        asyncio.run(WavenumberAlignNode("align", {}).execute(spectra=source, reference=_reference()))
    with pytest.raises(ValueError, match="cm-1"):
        asyncio.run(
            WavenumberAlignNode("align", {}).execute(
                spectra=_spectra(units="nm"),
                reference=_reference(units="nm"),
            )
        )


def test_node_edge_refuses_raman_shift_as_wavenumber_even_on_identical_grid() -> None:
    source = _spectra()
    reference = _reference(np.asarray(source.feature_axis.values))
    reference.feature_axis = SpectralAxis(
        values=np.asarray(source.feature_axis.values),
        title="Raman shift",
        units="cm⁻¹",
    )
    node = WavenumberAlignNode("align", {"method": "linear", "extrapolation": "reject"})

    with pytest.raises(ValueError, match="cannot combine 'wavenumber' and 'raman_shift'"):
        asyncio.run(node.run(spectra=source, reference=reference))


def test_live_and_generated_execution_share_values_metadata_diagnostics_and_impact() -> None:
    source = _spectra()
    reference = _reference()
    node = WavenumberAlignNode("align", {"method": "linear", "extrapolation": "reject"})
    live = asyncio.run(node.execute(spectra=source, reference=reference))
    generated_source = "\n".join(
        node.generate_python(
            {"spectra": "source", "reference": "reference"},
            indent="",
            use_scp=False,
        )
    )
    namespace = {"results": {}, "source": source, "reference": reference}
    exec(compile(generated_source, "<canonical alignment export>", "exec"), namespace)
    generated = namespace["results"]["align"]
    output = live.outputs["default"]

    np.testing.assert_allclose(output.X, [[0.5, 2.5, 6.5], [2.5, 4.5, 8.5]])
    np.testing.assert_array_equal(generated.X, output.X)
    np.testing.assert_array_equal(output.feature_axis.values, reference.feature_axis.values)
    np.testing.assert_array_equal(output.sample_axis.values, source.sample_axis.values)
    np.testing.assert_array_equal(output.target, source.target)
    assert output.feature_axis.units == "cm^-1"
    assert output.feature_axis.title == "Instrument transfer grid"
    assert output.sample_axis.labels == ["sample-a", "sample-b"]
    assert output.sample_axis.sample_table == {"batch": ["A", "B"]}
    assert output.is_time_series is True
    assert output.units == "absorbance"
    assert output.data_role == "X_spectra"
    assert output.provenance[-1].node_id == "align"
    assert dict(output.provenance[-1].parameters) == {"method": "linear", "extrapolation": "reject"}
    assert output.meta["wavenumber_align_diagnostics"] == live.diagnostics
    assert dict(output.provenance[-1].impact or {}) == {
        "schema_version": "spectrasherpa-preprocess-wavenumber-align-impact/1",
        **live.diagnostics,
    }
    generated_entry = generated.provenance.to_list()[-1]
    output_entry = output.provenance.to_list()[-1]
    assert generated_entry | {"timestamp": "ignored"} == output_entry | {"timestamp": "ignored"}
    assert generated.meta["wavenumber_align_diagnostics"] == live.diagnostics
    json.dumps(output.provenance.to_list(), allow_nan=False)


def test_reference_intensities_do_not_influence_alignment() -> None:
    source = _spectra()
    reference_a = _reference()
    reference_b = _reference()
    reference_b.X[:] = -99999.0

    result_a = asyncio.run(WavenumberAlignNode("a", {}).execute(spectra=source, reference=reference_a))
    result_b = asyncio.run(WavenumberAlignNode("b", {}).execute(spectra=source, reference=reference_b))

    np.testing.assert_array_equal(result_a.outputs["default"].X, result_b.outputs["default"].X)
    assert result_a.diagnostics == result_b.diagnostics


def test_wavenumber_align_executes_in_a_real_spawned_worker() -> None:
    context = WorkerExecutionContext(
        execution_id="canonical-wavenumber-align",
        runtime=ExecutionRuntime(),
        capabilities=(WorkerCapability.READ_DATASET.value,),
        origin_pid=os.getpid(),
    )
    try:
        pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))
    except (NotImplementedError, PermissionError, OSError) as exc:
        pytest.skip(f"spawn worker unavailable: {exc}")
    try:
        result = pool.submit(
            _run_node_in_worker,
            "preprocess.wavenumber_align",
            "align",
            {"method": "linear", "extrapolation": "reject"},
            (),
            {"spectra": _spectra(), "reference": _reference()},
            context,
        ).result(timeout=30)
    finally:
        pool.shutdown(wait=True)

    np.testing.assert_allclose(result.outputs["default"].X[0], [0.5, 2.5, 6.5])
    worker = result.diagnostics["worker_execution"]
    assert worker["mode"] == "spawned_worker"
    assert worker["origin_pid"] == os.getpid()
    assert worker["worker_pid"] != os.getpid()


def test_wavenumber_align_requires_its_declared_dataset_capability() -> None:
    context = WorkerExecutionContext(
        execution_id="canonical-align-denied", runtime=ExecutionRuntime(), origin_pid=os.getpid()
    )
    with pytest.raises(PermissionError, match="worker capabilities are missing"):
        _run_node_in_worker(
            "preprocess.wavenumber_align",
            "align",
            {"method": "linear", "extrapolation": "reject"},
            (),
            {"spectra": _spectra(), "reference": _reference()},
            context,
        )


def test_alignment_has_one_numerical_authority_and_no_single_input_node() -> None:
    package_root = Path(__file__).resolve().parents[1]
    retired_preprocessing = package_root / "src/spectra_sherpa/app/lib/preprocessing.py"
    canonical_source = (
        package_root / "src/spectra_sherpa/app/services/dag/nodes/preprocessing/wavenumber_align_node.py"
    ).read_text(encoding="utf-8")
    retired_module = package_root / "src/spectra_sherpa/app/services/dag/nodes/preprocessing/cleaning_nodes.py"

    assert not retired_preprocessing.exists()
    assert not retired_module.exists()
    assert "_wavenumber_align_dispatch" in canonical_source
    assert "PchipInterpolator(" in canonical_source
    assert "_sinc_interpolate_row(" in canonical_source
