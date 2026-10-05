"""Scientific and lifecycle contract tests for canonical fitted MSC."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes.preprocessing  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.preprocessing.msc_node import (
    MSCNode,
    _apply_msc_state,
    _fit_msc_state,
    _msc_dispatch,
)
from spectra_sherpa.app.services.dag.nodes.preprocessing.normalize_node import _normalize_dispatch
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility
from tests.performance_contract import PerformanceCeiling


def _dataset(rows: list[list[float]]) -> SherpaDataset:
    features = len(rows[0])
    return SherpaDataset(
        X=np.asarray(rows, dtype=np.float64),
        feature_axis=SpectralAxis(values=np.linspace(1000.0, 1800.0, features), units="cm-1"),
        units="absorbance",
    )


def test_msc_has_one_fitted_contract_and_normalize_rejects_the_old_alias() -> None:
    contract = node_registry.get_metadata("preprocess.msc").resolved_execution_contract()

    assert contract is not None
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_TRANSFORM.value
    assert contract.payload["fitted_state_serializer"] == "spectra.msc-reference-json.v2"
    assert contract.payload["managed_optimization_eligibility"] == (
        ManagedOptimizationEligibility.LOCAL.value,
        ManagedOptimizationEligibility.DEVELOPMENT.value,
        ManagedOptimizationEligibility.FULL_REFIT.value,
    )
    assert contract.payload["managed_optimization_profiles"] == ("first_party_pls",)
    assert contract.payload["citations"][0].startswith("Geladi, MacDougall & Martens")
    with pytest.raises(ValueError, match="not an admitted option"):
        node_registry.create_node("preprocess.normalize", "old-msc", {"method": "msc"})


def test_fit_on_training_rows_applies_exact_reference_without_refitting() -> None:
    training = _dataset([[1.0, 2.0, 4.0, 8.0], [1.2, 2.4, 4.8, 9.6]])
    held_out = _dataset([[2.5, 5.1, 10.0, 20.1]])
    node = MSCNode("msc", {"reference_method": "mean"})

    state = node.fit_fitted_state(training)
    applied = node.apply_fitted_state(held_out, state)
    refit = node.apply_fitted_state(held_out, node.fit_fitted_state(held_out))

    reference = np.mean(training.X, axis=0)
    design = np.column_stack((reference, np.ones(reference.shape[0])))
    slope, intercept = np.linalg.lstsq(design, held_out.X[0], rcond=None)[0]
    np.testing.assert_allclose(applied.X[0], (held_out.X[0] - intercept) / slope)
    assert not np.allclose(applied.X, refit.X)
    assert applied.provenance[-1].op_id == "preprocess.msc"
    recorded_state = applied.provenance[-1].parameters["transform_state"]
    assert recorded_state["serializer"] == state["serializer"]
    np.testing.assert_allclose(recorded_state["reference_spectrum"], state["reference_spectrum"])


@pytest.mark.parametrize("reference_method", ["mean", "median", "first"])
def test_live_and_generated_dispatch_share_the_fitted_authority(reference_method: str) -> None:
    source = _dataset([[1.0, 2.1, 4.2, 8.1], [1.3, 2.5, 5.2, 10.4], [0.8, 1.7, 3.5, 7.1]])
    reference = _dataset([[1.0, 2.0, 4.0, 8.0], [1.1, 2.2, 4.4, 8.8]])
    node = MSCNode("msc", {"reference_method": reference_method})

    live = asyncio.run(node.execute(default=source, reference=reference)).outputs["default"]
    dispatched = _msc_dispatch(source, reference_method=reference_method, reference_data=reference)

    np.testing.assert_allclose(live.X, dispatched, rtol=1e-13, atol=1e-13)
    generated = "\n".join(node.generate_python({"default": "source", "reference": "reference"}))
    assert "fit_fitted_state(reference)" in generated
    assert "apply_fitted_state(source, _state)" in generated
    assert "lstsq" not in generated


def test_fit_and_apply_reject_nonfinite_axis_drift_and_unresolved_slope() -> None:
    source = _dataset([[1.0, 2.0, 4.0, 8.0], [1.1, 2.2, 4.4, 8.8]])
    node = MSCNode("msc", {"reference_method": "mean"})
    state = node.fit_fitted_state(source)

    with pytest.raises(ValueError, match="finite"):
        node.fit_fitted_state(_dataset([[1.0, 2.0, float("nan"), 8.0]]))
    shifted_axis = SherpaDataset(
        X=source.X,
        feature_axis=SpectralAxis(values=np.linspace(1001.0, 1801.0, 4), units="cm-1"),
        units="absorbance",
    )
    with pytest.raises(ValueError, match="axis differs"):
        node.apply_fitted_state(shifted_axis, state)
    with pytest.raises(ValueError, match="unresolved"):
        node.apply_fitted_state(_dataset([[3.0, 3.0, 3.0, 3.0]]), state)


@pytest.mark.parametrize(
    "mutation",
    [
        {"extra": True},
        {"serializer": "unknown"},
        {"feature_count": 3},
        {"reference_method": "unknown"},
        {"reference_spectrum": [1.0, 1.0, 1.0, 1.0]},
    ],
)
def test_fitted_state_is_closed_and_self_validating(mutation: dict[str, object]) -> None:
    source = _dataset([[1.0, 2.0, 4.0, 8.0], [1.1, 2.2, 4.4, 8.8]])
    state = MSCNode("msc", {"reference_method": "mean"}).fit_fitted_state(source)
    forged = {**state, **mutation}

    with pytest.raises(ValueError, match="MSC|fitted MSC"):
        _apply_msc_state(
            source.X,
            forged,
            feature_axis_values=source.feature_axis.values,
            feature_axis_units=source.feature_axis.units,
        )


def test_partitioned_fit_uses_training_rows_only() -> None:
    X = np.asarray(
        [
            [1.0, 2.0, 4.0, 8.0],
            [1.1, 2.2, 4.4, 8.8],
            [0.9, 1.8, 3.6, 7.2],
            [4.0, 8.1, 16.0, 32.2],
            [5.0, 10.2, 20.1, 40.0],
            [6.0, 12.0, 24.2, 48.1],
        ],
        dtype=np.float64,
    )
    training = X[[2, 3, 4, 5]]
    held_out = X[[0, 1]]
    state = _fit_msc_state(
        training,
        reference_method="mean",
        feature_axis_values=None,
        feature_axis_units=None,
    )
    expected = _apply_msc_state(
        held_out,
        state,
        feature_axis_values=None,
        feature_axis_units=None,
    )

    applied = MSCNode("msc", {"reference_method": "mean"}).apply_fitted_state(SherpaDataset(X=held_out), state)
    np.testing.assert_allclose(applied.X, expected)
    full_state = _fit_msc_state(
        X,
        reference_method="mean",
        feature_axis_values=None,
        feature_axis_units=None,
    )
    leaked = _apply_msc_state(
        held_out,
        full_state,
        feature_axis_values=None,
        feature_axis_units=None,
    )
    assert not np.allclose(applied.X, leaked)


def test_msc_fixed_workload_completes_within_shared_ceiling() -> None:
    rng = np.random.default_rng(42)
    reference = np.linspace(0.3, 1.8, 1600)
    matrix = rng.uniform(0.8, 1.2, size=(200, 1)) * reference + rng.normal(0.0, 0.003, size=(200, 1600))
    with PerformanceCeiling("preprocess.msc", "msc-200x1600", 5.0).measure():
        state = _fit_msc_state(
            matrix,
            reference_method="mean",
            feature_axis_values=None,
            feature_axis_units=None,
        )
        corrected = _apply_msc_state(
            matrix,
            state,
            feature_axis_values=None,
            feature_axis_units=None,
        )

    assert corrected.shape == matrix.shape
    assert np.isfinite(corrected).all()

    with PerformanceCeiling("preprocess.apply_fitted_msc", "msc-200x1600-state-replay", 5.0).measure():
        replayed = _apply_msc_state(
            matrix,
            state,
            feature_axis_values=None,
            feature_axis_units=None,
        )
    np.testing.assert_array_equal(replayed, corrected)


def test_sample_local_normalization_completes_within_shared_ceiling() -> None:
    rng = np.random.default_rng(43)
    matrix = rng.normal(size=(200, 1600))
    with PerformanceCeiling("preprocess.normalize", "snv-200x1600", 2.0).measure():
        normalized = _normalize_dispatch(matrix, method="snv", std_ddof=0)

    assert normalized.shape == matrix.shape
    assert np.isfinite(normalized).all()
