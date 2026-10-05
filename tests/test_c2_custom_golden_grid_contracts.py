"""Canonical common-grid alignment science, contracts, and projections."""

from __future__ import annotations

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.golden_grid import build_common_overlap_grid
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.custom import GoldenGridAlignNode
from spectra_sherpa.app.services.dag.nodes.custom_contracts import (
    build_golden_grid_alignment_result,
    canonical_golden_grid_parameters,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling

PARAMETERS = {
    "coverage_policy": "common_overlap",
    "extrapolation": "reject",
    "max_upsampling_factor": 1.1,
    "merge_tolerance": 0.05,
    "method": "linear",
}


def _dataset(
    axis: np.ndarray,
    *,
    samples: int = 2,
    offset: float = 0.0,
    units: str = "absorbance",
    target: np.ndarray | None = None,
) -> SherpaDataset:
    coordinates = np.asarray(axis, dtype=np.float64)
    rows = np.vstack([2.0 * coordinates + offset + sample for sample in range(samples)])
    return SherpaDataset(
        X=rows,
        feature_axis=SpectralAxis(values=coordinates, units="cm-1", title="Wavenumber"),
        sample_axis=SampleAxis(
            values=np.arange(samples),
            labels=[f"sample-{offset:g}-{index}" for index in range(samples)],
            sample_table={"batch": [f"batch-{offset:g}"] * samples},
        ),
        target=target,
        target_context=TargetContext(target_type="continuous", target_name="reference", target_units="%"),
        units=units,
        data_role="X_spectra",
    )


def test_golden_grid_contract_is_typed_local_and_variadic() -> None:
    metadata = node_registry.get_metadata("custom.golden_grid_align")
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["sample_effect"] == "generates_samples"
    assert contract.payload["axis_effect"] == "changes_axis"
    assert contract.payload["unit_effect"] == "requires_compatible_units"
    assert contract.payload["semantic_inputs"][0]["variadic"] is True
    assert contract.payload["semantic_outputs"][0]["type_ref"].endswith("/SpectralDataset/1.0")


def test_golden_grid_parameter_grammar_is_closed() -> None:
    assert canonical_golden_grid_parameters(PARAMETERS) == PARAMETERS
    for invalid in (
        {**PARAMETERS, "extrapolation": "allow"},
        {**PARAMETERS, "coverage_policy": "union"},
        {**PARAMETERS, "max_upsampling_factor": 0.99},
        {**PARAMETERS, "merge_tolerance": 0.0},
        {**PARAMETERS, "method": "cubic"},
        {**PARAMETERS, "warning_only": True},
    ):
        with pytest.raises(ValueError):
            canonical_golden_grid_parameters(invalid)


def test_common_grid_is_overlap_only_and_clusters_have_bounded_diameter() -> None:
    first = np.array([1000.0, 1001.0, 1002.0, 1003.0, 1004.0])
    second = np.array([1003.02, 1002.02, 1001.02, 1000.02])
    grid = build_common_overlap_grid([first, second], merge_tolerance=0.05)
    np.testing.assert_allclose(grid, [1000.02, 1001.01, 1002.01, 1003.01])

    chained = build_common_overlap_grid(
        [np.array([0.0, 0.04, 0.08, 1.0]), np.array([0.0, 1.0])],
        merge_tolerance=0.05,
    )
    np.testing.assert_allclose(chained, [0.04 / 3.0, 0.08, 1.0])


@pytest.mark.asyncio
async def test_golden_grid_live_and_generated_paths_share_one_authority() -> None:
    left = _dataset(np.array([1000.0, 1001.0, 1002.0, 1003.0, 1004.0]), target=np.array([1.0, 2.0]))
    right = _dataset(
        np.array([1003.02, 1002.02, 1001.02, 1000.02]),
        offset=10.0,
        target=np.array([3.0, 4.0]),
    )
    node = GoldenGridAlignNode("golden", PARAMETERS)

    live = await node.execute(default=[left, right])
    result = live.outputs["default"]
    assert isinstance(result, SherpaDataset)
    assert result.shape == (4, 4)
    np.testing.assert_allclose(result.feature_axis.values, [1000.02, 1001.01, 1002.01, 1003.01])
    np.testing.assert_allclose(result.target, [1.0, 2.0, 3.0, 4.0])
    assert result.sample_axis.labels == ["sample-0-0", "sample-0-1", "sample-10-0", "sample-10-1"]
    assert result.sample_axis.sample_table["golden_grid_source_index"] == [0, 0, 1, 1]
    assert live.diagnostics["adds_measured_resolution"] is False
    assert len(live.diagnostics["input_dataset_digests"]) == 2

    namespace = {"left": left, "right": right, "results": {}}
    exec(
        "\n".join(node.generate_python({"default": ["left", "right"]}, indent="")),
        namespace,
    )  # noqa: S102
    generated = namespace["results"]["golden"]
    np.testing.assert_array_equal(generated.X, result.X)
    np.testing.assert_array_equal(generated.target, result.target)
    assert generated.provenance.to_list()[0]["impact"] == result.provenance.to_list()[0]["impact"]


def test_golden_grid_rejects_extrapolation_incompatible_semantics_and_mixed_targets() -> None:
    left = _dataset(np.array([1000.0, 1001.0, 1002.0]))
    disjoint = _dataset(np.array([2000.0, 2001.0, 2002.0]))
    wrong_units = _dataset(np.array([1000.0, 1001.0, 1002.0]), units="transmittance")
    targeted = _dataset(np.array([1000.0, 1001.0, 1002.0]), target=np.array([1.0, 2.0]))

    with pytest.raises(ValueError, match="positive spectral overlap"):
        build_golden_grid_alignment_result([left, disjoint], PARAMETERS, node_id="golden")
    with pytest.raises(ValueError, match="signal units"):
        build_golden_grid_alignment_result([left, wrong_units], PARAMETERS, node_id="golden")
    with pytest.raises(ValueError, match="all provide targets"):
        build_golden_grid_alignment_result([left, targeted], PARAMETERS, node_id="golden")


def test_golden_grid_requires_explicit_admission_before_upsampling() -> None:
    coarse = _dataset(np.array([1000.0, 1002.0, 1004.0]))
    fine = _dataset(np.array([1000.0, 1001.0, 1002.0, 1003.0, 1004.0]), offset=10.0)
    with pytest.raises(ValueError, match="above the admitted maximum"):
        build_golden_grid_alignment_result(
            [coarse, fine],
            {**PARAMETERS, "merge_tolerance": 0.01, "max_upsampling_factor": 1.0},
            node_id="golden",
        )

    result, diagnostics = build_golden_grid_alignment_result(
        [coarse, fine],
        {**PARAMETERS, "merge_tolerance": 0.01, "max_upsampling_factor": 2.0},
        node_id="golden",
    )
    assert result.shape == (4, 5)
    assert diagnostics["per_source_alignment"][0]["upsampling_factor"] == 2.0
    assert diagnostics["adds_measured_resolution"] is False


def test_golden_grid_fixed_workload_stays_inside_reviewed_ceiling() -> None:
    axis = np.linspace(900.0, 2500.0, 1600)
    datasets = [_dataset(axis, samples=200, offset=float(index)) for index in range(3)]
    parameters = {**PARAMETERS, "merge_tolerance": 1e-6, "max_upsampling_factor": 1.0}

    build_golden_grid_alignment_result(datasets, parameters, node_id="golden")
    with PerformanceCeiling("custom.golden_grid_align", "3x200x1600-common-grid", 5.0).measure():
        build_golden_grid_alignment_result(datasets, parameters, node_id="golden")
