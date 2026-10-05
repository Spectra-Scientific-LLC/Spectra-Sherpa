"""Canonical spectral-library comparison contract proofs."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.modeling.library_compare_node import (
    canonical_library_comparison_parameters,
    execute_library_comparison,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


def _parameters(**updates: object) -> dict[str, object]:
    result: dict[str, object] = {
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
    result.update(updates)
    return result


def _dataset(values: np.ndarray, labels: list[str], *, axis: np.ndarray | None = None) -> SherpaDataset:
    matrix = np.asarray(values, dtype=np.float64)
    positions = np.linspace(900.0, 1800.0, matrix.shape[1]) if axis is None else np.asarray(axis, dtype=np.float64)
    return SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(values=positions, units="cm-1", title="Wavenumber"),
        sample_axis=SampleAxis(labels=labels),
        units="absorbance",
        data_role="X_spectra",
    )


def test_library_comparison_publishes_one_local_evaluator_contract() -> None:
    metadata = node_registry.get_metadata("analysis.compare_library")
    contract = metadata.resolved_execution_contract()
    assert contract is not None
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.EVALUATOR.value
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["citations"]
    assert metadata.output_ports and metadata.output_ports[0].type_ref == "spectrasherpa://types/Comparison/1.0"


def test_library_comparison_parameters_are_closed_bounded_and_ordered() -> None:
    canonical = canonical_library_comparison_parameters(_parameters(library_filter=" Ethanol, Water "))
    assert canonical["library_filter"] == "Ethanol,Water"
    for invalid in (
        _parameters(hqi_mode="cosine"),
        _parameters(hqi_accept_threshold=1001),
        _parameters(hqi_accept_threshold=400, hqi_reject_threshold=500),
        _parameters(min_overlap_coverage=1.1),
        _parameters(min_overlap_points=True),
        _parameters(library_filter="water,WATER"),
        {**_parameters(), "repair_axis": True},
    ):
        with pytest.raises(ValueError):
            canonical_library_comparison_parameters(invalid)


def test_identical_spectrum_is_the_top_exact_hqi_match() -> None:
    axis = np.linspace(900.0, 1800.0, 101)
    reference = np.exp(-(((axis - 1300.0) / 55.0) ** 2))
    distractor = np.exp(-(((axis - 1600.0) / 80.0) ** 2))
    sample = _dataset(reference.reshape(1, -1), ["unknown"], axis=axis)
    library = _dataset(np.vstack([distractor, reference]), ["distractor", "reference"], axis=axis)
    result = execute_library_comparison(sample, library, parameters=_parameters(), node_id="comparison")
    rows = result.outputs["default"]["data"]
    assert rows[0]["library"] == "reference"
    assert rows[0]["hqi"] == pytest.approx(1000.0)
    assert rows[0]["candidate_status"] == "auto_selected"
    assert result.diagnostics["best_match"] == "reference"


def test_library_live_generated_and_core_paths_share_one_authority() -> None:
    axis = np.linspace(900.0, 1800.0, 80)
    library = _dataset(
        np.vstack([np.sin(axis / 80.0), np.cos(axis / 100.0)]),
        ["alpha", "beta"],
        axis=axis,
    )
    sample = _dataset(np.sin(axis / 80.0).reshape(1, -1), ["query"], axis=axis)
    node = node_registry.create_node("analysis.compare_library", "comparison", _parameters(top_n=2))
    live = asyncio.run(node.execute(sample=sample, library=library))
    namespace = {"sample": sample, "library": library, "results": {}}
    exec(
        "\n".join(node.generate_python({"sample": "sample", "library": "library"}, indent="")), namespace
    )  # noqa: S102
    generated = namespace["results"]["comparison"]
    assert generated == live.outputs
    assert generated["hqi_report"] == live.outputs["hqi_report"]


def test_library_comparison_fails_closed_on_axis_and_overlap_defects() -> None:
    sample = _dataset(np.ones((1, 20)), ["query"], axis=np.linspace(900.0, 1000.0, 20))
    library = _dataset(np.ones((1, 20)), ["reference"], axis=np.linspace(1200.0, 1300.0, 20))
    with pytest.raises(ValueError, match="no comparable"):
        execute_library_comparison(sample, library, parameters=_parameters(), node_id="comparison")
    with pytest.raises(ValueError, match="filter"):
        execute_library_comparison(
            sample,
            _dataset(np.ones((1, 20)), ["reference"], axis=np.linspace(900.0, 1000.0, 20)),
            parameters=_parameters(library_filter="absent"),
            node_id="comparison",
        )


def test_library_comparison_fixed_workload_stays_inside_reviewed_ceiling() -> None:
    axis = np.linspace(900.0, 1800.0, 800)
    sample = _dataset(np.vstack([np.sin(axis / (70.0 + i)) for i in range(8)]), [f"q{i}" for i in range(8)], axis=axis)
    library = _dataset(
        np.vstack([np.cos(axis / (80.0 + i)) for i in range(20)]),
        [f"r{i}" for i in range(20)],
        axis=axis,
    )
    with PerformanceCeiling("analysis.compare_library", "8x20-pairs-800-features", 5.0).measure():
        execute_library_comparison(sample, library, parameters=_parameters(top_n=5), node_id="comparison")
