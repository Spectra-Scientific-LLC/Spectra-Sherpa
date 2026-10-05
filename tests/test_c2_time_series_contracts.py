"""Canonical contracts and core numerical proofs for local time-series nodes."""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.time_series import (
    _canonical_moving_window_parameters,
    _canonical_trend_parameters,
    build_moving_window_result,
    build_trend_removal_result,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


def _dataset(values: np.ndarray | None = None) -> SherpaDataset:
    matrix = np.arange(24, dtype=np.float64).reshape(6, 4) if values is None else np.asarray(values, dtype=np.float64)
    return SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(values=np.arange(matrix.shape[1], dtype=np.float64), units="channel"),
        sample_axis=SampleAxis(labels=[f"time-{index}" for index in range(matrix.shape[0])]),
        target=np.arange(matrix.shape[0], dtype=np.float64),
    )


@pytest.mark.parametrize(
    ("node_type", "sample_effect"),
    [
        ("time_series.moving_window", "generates_samples"),
        ("time_series.trend_removal", "preserves_samples"),
    ],
)
def test_time_series_nodes_have_explicit_local_contracts(node_type: str, sample_effect: str) -> None:
    metadata = node_registry.get_metadata(node_type)
    contract = metadata.resolved_execution_contract()
    assert contract is not None
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["sample_effect"] == sample_effect
    assert contract.payload["deterministic"] is True
    assert contract.payload["citations"]
    assert metadata.policy.safe_for_auto_apply is True
    assert metadata.policy.data_egress_risk == "none"


def test_time_series_parameter_schemas_are_closed_and_bounded() -> None:
    assert _canonical_moving_window_parameters({}) == {
        "window_size": 10,
        "step_size": 1,
        "aggregation": "none",
    }
    assert _canonical_trend_parameters({}) == {"method": "linear", "poly_order": 2, "window_size": 5}
    for validator, parameters in (
        (_canonical_moving_window_parameters, {"window_size": True}),
        (_canonical_moving_window_parameters, {"aggregation": "sum"}),
        (_canonical_trend_parameters, {"method": "loess"}),
        (_canonical_trend_parameters, {"unknown": 1}),
    ):
        with pytest.raises(ValueError):
            validator(parameters)


def test_moving_window_has_explicit_rows_and_drops_invalidated_sample_identity() -> None:
    source = _dataset()
    result = build_moving_window_result(
        source,
        parameters={"window_size": 3, "step_size": 2, "aggregation": "mean"},
        node_id="window",
    )
    expected = np.vstack([np.mean(source.X[0:3], axis=0), np.mean(source.X[2:5], axis=0)])
    np.testing.assert_allclose(result.X, expected)
    assert result.sample_axis is not None
    assert result.sample_axis.labels == ["window-0000:source-000000-000003", "window-0001:source-000002-000005"]
    assert result.target is None
    assert result.meta["time_series_windows"]["window_intervals"] == [[0, 3], [2, 5]]
    assert result.provenance[-1].node_id == "window"


@pytest.mark.parametrize("method", ["linear", "polynomial"])
def test_trend_removal_eliminates_the_declared_polynomial_subspace(method: str) -> None:
    time = np.linspace(-1.0, 1.0, 12)
    values = np.column_stack([3.0 + 2.0 * time, -1.0 + time + (time**2 if method == "polynomial" else 0.0)])
    result = build_trend_removal_result(
        _dataset(values),
        parameters={"method": method, "poly_order": 2, "window_size": 5},
        node_id="trend",
    )
    np.testing.assert_allclose(result.X, 0.0, atol=1e-12)
    assert result.meta["time_series_trend_removal"]["scope"] == "current_batch_local_only"
    assert result.provenance[-1].node_id == "trend"


def test_live_and_generated_time_series_paths_share_one_authority() -> None:
    source = _dataset()
    for node_type, parameters in (
        ("time_series.trend_removal", {"method": "difference"}),
        ("time_series.moving_window", {"window_size": 3, "step_size": 2, "aggregation": "mean"}),
    ):
        node = node_registry.create_node(node_type, "time", parameters)
        live = asyncio.run(node.execute(input_data=source))
        generated = "\n".join(node.generate_python({"default": "source"}, indent=""))
        namespace = {"source": source, "results": {}}
        exec(generated, namespace)  # noqa: S102 - exercises exported project source
        projected = namespace["results"]["time"]
        np.testing.assert_allclose(projected.X, live.X)
        assert projected.meta == live.meta
        assert projected.provenance[-1].model_dump(exclude={"timestamp"}) == live.provenance[-1].model_dump(
            exclude={"timestamp"}
        )


def test_time_series_nodes_fail_closed_and_have_representative_capacity_ceilings() -> None:
    source = _dataset()
    with pytest.raises(ValueError, match="cannot exceed"):
        build_moving_window_result(source, parameters={"window_size": 7, "step_size": 1, "aggregation": "mean"})
    with pytest.raises(ValueError, match="finite"):
        build_trend_removal_result(
            _dataset(np.array([[1.0, np.nan], [2.0, 3.0]])),
            parameters={"method": "linear", "poly_order": 1, "window_size": 2},
        )

    representative = _dataset(np.arange(200 * 1600, dtype=np.float64).reshape(200, 1600))
    with PerformanceCeiling("time_series.trend_removal", "200x1600-dataset", 5.0).measure():
        build_trend_removal_result(
            representative,
            parameters={"method": "linear", "poly_order": 2, "window_size": 5},
        )
    with PerformanceCeiling("time_series.moving_window", "200x1600-dataset", 5.0).measure():
        build_moving_window_result(
            representative,
            parameters={"window_size": 10, "step_size": 5, "aggregation": "mean"},
        )


def test_ready_oes_project_consumes_both_time_series_nodes_in_order() -> None:
    path = Path(__file__).parents[1] / "src/spectra_sherpa/data/templates/oes_process_monitoring.yaml"
    text = path.read_text(encoding="utf-8")
    assert "node_type: time_series.trend_removal" in text
    assert "node_type: time_series.moving_window" in text
    assert text.index("node_type: time_series.trend_removal") < text.index("node_type: time_series.moving_window")
