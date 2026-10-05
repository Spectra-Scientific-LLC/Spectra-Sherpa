"""Canonical MCR-ALS scientific, lifecycle, projection, and cost proofs."""

from __future__ import annotations

import copy

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.fitted_state import MCRExtract
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.modeling.mcr_nodes import (
    MCR_FITTED_STATE_SERIALIZER,
    MCRNode,
    _canonical_mcr_parameters,
    _mcr_scientific_core,
    apply_mcr_fitted_state,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests._optional_scp import HAS_SCP
from tests.performance_contract import PerformanceCeiling

_requires_scp = pytest.mark.skipif(not HAS_SCP, reason="MCR-ALS execution requires SpectroChemPy")


def _parameters(**overrides: object) -> dict[str, object]:
    parameters: dict[str, object] = {
        "n_components": 3,
        "non_negative_C": True,
        "non_negative_St": True,
        "max_iter": 80,
        "tol": 1e-5,
        "normSpec": "euclid",
        "validation_target_index": 1,
        "validation_component_index": 1,
    }
    parameters.update(overrides)
    return parameters


def _dataset(*, samples: int = 28, features: int = 36) -> SherpaDataset:
    rng = np.random.default_rng(1995)
    axis = np.linspace(900.0, 1800.0, features)
    pure_spectra = np.vstack(
        [
            np.exp(-0.5 * ((axis - 1050.0) / 55.0) ** 2),
            0.8 * np.exp(-0.5 * ((axis - 1370.0) / 70.0) ** 2),
            0.6 * np.exp(-0.5 * ((axis - 1650.0) / 45.0) ** 2),
        ]
    )
    concentrations = rng.uniform(0.05, 1.5, size=(samples, 3))
    matrix = concentrations @ pure_spectra + rng.uniform(0.0, 2e-4, size=(samples, features))
    return SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(values=axis, units="cm-1"),
        sample_axis=SampleAxis(labels=[f"mixture-{index}" for index in range(samples)]),
    )


def test_mcr_has_one_exact_local_fitted_model_contract() -> None:
    metadata = node_registry.get_metadata("model.mcr_als")
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["operation_id"] == "model.mcr_als"
    assert contract.payload["runtime_family"] == RuntimeFamily.SPECTROCHEMPY.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_MODEL.value
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["target_access"] == "none"
    assert contract.payload["fitted_state_serializer"] == MCR_FITTED_STATE_SERIALIZER
    assert any("Tauler" in citation for citation in contract.payload["citations"])
    assert metadata.requires_scp is True


def test_mcr_parameter_contract_is_closed() -> None:
    assert _canonical_mcr_parameters(_parameters()) == _parameters()
    for invalid in (
        {},
        _parameters(n_components=True),
        _parameters(n_components=1),
        _parameters(n_components=51),
        _parameters(non_negative_C=1),
        _parameters(non_negative_St="yes"),
        _parameters(max_iter=9),
        _parameters(max_iter=2_001),
        _parameters(tol=float("nan")),
        _parameters(tol=0.2),
        _parameters(normSpec="unit-area"),
        _parameters(validation_target_index=0),
        {**_parameters(), "initialization": "random"},
    ):
        with pytest.raises(ValueError):
            _canonical_mcr_parameters(invalid)


@pytest.mark.asyncio
@_requires_scp
async def test_mcr_live_generated_and_fitted_state_share_one_scientific_core() -> None:
    dataset = _dataset()
    node = MCRNode("mcr", _parameters())

    live = await node.execute(input_data=dataset)
    namespace = {"dataset": dataset, "results": {}}
    exec("\n".join(node.generate_python({"default": "dataset"}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["mcr"]
    replay = apply_mcr_fitted_state(dataset, live.outputs["fitted_state"])

    np.testing.assert_allclose(generated["C"], live.outputs["C"].data, rtol=1e-10, atol=1e-10)
    np.testing.assert_allclose(generated["St"], live.outputs["St"].data, rtol=1e-10, atol=1e-10)
    np.testing.assert_allclose(generated["residuals"], live.outputs["residuals"].data, rtol=1e-10, atol=1e-10)
    np.testing.assert_allclose(replay, live.outputs["C"].data, rtol=1e-5, atol=1e-7)
    np.testing.assert_allclose(
        live.outputs["residuals"].data,
        np.asarray(dataset.X) - np.asarray(live.outputs["C"].data) @ np.asarray(live.outputs["St"].data),
        rtol=0.0,
        atol=1e-12,
    )
    assert np.min(live.outputs["C"].data) >= 0.0
    assert np.min(live.outputs["St"].data) >= 0.0
    assert generated["fitted_state"] == live.outputs["fitted_state"]
    assert generated["model"] == live.outputs["model"] == live.outputs["fitted_state"]
    assert live.diagnostics["residual_definition"] == "observed_minus_reconstructed"


@_requires_scp
def test_mcr_fitted_state_fails_closed_on_identity_shape_and_numeric_corruption() -> None:
    dataset = _dataset()
    state = _mcr_scientific_core(dataset, parameters=_parameters())["fitted_state"]
    corruptions: list[dict[str, object]] = []

    extra = copy.deepcopy(state)
    extra["unexpected"] = True
    corruptions.append(extra)
    wrong_serializer = copy.deepcopy(state)
    wrong_serializer["serializer"] = "spectrasherpa.model-artifact.mcr-als/0"
    corruptions.append(wrong_serializer)
    wrong_solver = copy.deepcopy(state)
    wrong_solver["metadata"]["concentration_solver"] = "pinv"
    corruptions.append(wrong_solver)
    wrong_shape = copy.deepcopy(state)
    wrong_shape["arrays"]["St"] = [[1.0, 2.0]]
    corruptions.append(wrong_shape)
    nonfinite = copy.deepcopy(state)
    nonfinite["arrays"]["C"][0][0] = float("nan")
    corruptions.append(nonfinite)

    for corrupted in corruptions:
        with pytest.raises(ValueError):
            apply_mcr_fitted_state(dataset, corrupted)


def test_mcr_artifact_replay_preserves_the_fitted_concentration_constraint() -> None:
    spectra = np.asarray([[1.0, 0.0, 1.0], [0.0, 1.0, 1.0]])
    application = np.asarray([[1.0, -0.2, 0.8]])
    for solver in ("nnls", "lstsq"):
        fitted = MCRExtract(
            C=np.ones((4, 2)),
            St=spectra,
            n_components=2,
            concentration_solver=solver,
        )
        metadata, arrays = fitted.to_artifact()
        replay = MCRExtract.from_artifact(metadata, arrays)
        actual = replay.transform(application)

        assert replay.concentration_solver == solver
        if solver == "nnls":
            assert np.all(actual >= 0.0)
        else:
            np.testing.assert_allclose(actual, np.linalg.lstsq(spectra.T, application.T, rcond=None)[0].T)


@_requires_scp
def test_mcr_fixed_local_workload_stays_inside_reviewed_ceiling() -> None:
    dataset = _dataset(samples=40, features=80)
    parameters = _parameters(max_iter=40)
    _mcr_scientific_core(dataset, parameters=parameters)

    with PerformanceCeiling("model.mcr_als", "40x80-three-components", 5.0).measure():
        _mcr_scientific_core(dataset, parameters=parameters)
