"""Canonical NMF definition, lifecycle, projection, and cost proofs."""

from __future__ import annotations

import copy

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib import nmf_core
from spectra_sherpa.app.lib.axes import FeatureAxis
from spectra_sherpa.app.lib.fitted_state import NMFExtract
from spectra_sherpa.app.lib.nmf_core import (
    NMF_APPLICATION_RULE,
    NMF_COMPONENT_ORDER,
    NMF_STATE_SERIALIZER,
    apply_nmf,
    canonical_nmf_parameters,
    fit_nmf,
    validate_nmf_state,
)
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.modeling.decomposition_nodes import NMFNode
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility
from tests.performance_contract import PerformanceCeiling


def _parameters(**overrides: object) -> dict[str, object]:
    result: dict[str, object] = {
        "n_components": 3,
        "solver": "mu",
        "max_iter": 1000,
        "tol": 1e-5,
        "random_state": 42,
    }
    result.update(overrides)
    return result


def _mixture(*, samples: int = 48, features: int = 32) -> SherpaDataset:
    rng = np.random.default_rng(20260813)
    concentrations = rng.uniform(0.05, 1.0, size=(samples, 3))
    spectra = rng.uniform(0.05, 1.0, size=(3, features))
    return SherpaDataset(
        X=concentrations @ spectra,
        feature_axis=FeatureAxis(
            values=np.linspace(900.0, 1800.0, features),
            labels=[f"band-{index:03d}" for index in range(features)],
            units="cm^-1",
        ),
        data_role="X_spectra",
    )


def test_nmf_has_closed_deterministic_local_fitted_model_contract() -> None:
    contract = node_registry.get_metadata("model.nmf").resolved_execution_contract()

    assert contract is not None
    assert contract.payload["operation_id"] == "model.nmf"
    assert contract.payload["lifecycle_kind"] == LifecycleKind.FITTED_MODEL.value
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["fitted_state_serializer"] == NMF_STATE_SERIALIZER
    assert contract.payload["deterministic"] is True
    assert any("Lee and Seung" in citation for citation in contract.payload["citations"])
    assert any("R package NMF" in citation for citation in contract.payload["citations"])


def test_nmf_parameter_contract_is_closed() -> None:
    assert canonical_nmf_parameters(_parameters()) == _parameters()
    for invalid in (
        {},
        _parameters(n_components=1),
        _parameters(n_components=True),
        _parameters(solver="coordinate_descent"),
        _parameters(max_iter=0),
        _parameters(tol=0.0),
        _parameters(random_state=-1),
        {**_parameters(), "init": "random"},
    ):
        with pytest.raises(ValueError):
            canonical_nmf_parameters(invalid)


@pytest.mark.asyncio
async def test_nmf_live_and_generated_paths_share_exact_factors() -> None:
    dataset = _mixture()
    node = NMFNode("nmf", _parameters())

    live = await node.execute(input_data=dataset)
    namespace = {"dataset": dataset, "results": {}}
    exec("\n".join(node.generate_python({"default": "dataset"}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["nmf"]

    np.testing.assert_allclose(live.outputs["default"].X, generated["default"], rtol=0.0, atol=0.0)
    np.testing.assert_allclose(live.outputs["spectra"].X, generated["spectra"], rtol=0.0, atol=0.0)
    assert live.outputs["model"] == generated["model"]
    assert live.outputs["reconstruction_error"] == generated["reconstruction_error"]
    assert set(generated) == {"default", "concentrations", "spectra", "model", "reconstruction_error"}
    assert set(live.outputs) == {
        "default",
        "concentrations",
        "spectra",
        "model",
        "reconstruction_error",
        "_model_artifact",
    }
    concentrations = live.outputs["concentrations"]
    assert concentrations.data_role == "X_features"
    assert concentrations.meta["scientific_matrix_role"] == "component_concentrations"
    assert concentrations.feature_axis.labels == ["Component 1", "Component 2", "Component 3"]
    assert live.outputs["spectra"].meta["scientific_matrix_role"] == "component_spectra"


def test_nmf_state_is_deterministic_nonnegative_and_reconstructs_the_declared_error() -> None:
    dataset = _mixture()
    first = fit_nmf(dataset, parameters=_parameters())
    second = fit_nmf(dataset, parameters=_parameters())

    assert first == second
    assert first["component_order"] == NMF_COMPONENT_ORDER
    assert first["application_rule"] == NMF_APPLICATION_RULE
    assert first["convergence_status"] in {"converged", "max_iter_reached"}
    concentrations = np.asarray(first["concentrations"])
    components = np.asarray(first["components"])
    assert np.all(concentrations >= 0.0)
    assert np.all(components >= 0.0)
    assert first["reconstruction_error"] == pytest.approx(
        np.linalg.norm(dataset.X - concentrations @ components, ord="fro"),
        rel=1e-14,
    )


def test_nmf_fixed_basis_application_is_nonnegative_and_does_not_mutate_state() -> None:
    dataset = _mixture()
    state = fit_nmf(dataset, parameters=_parameters())
    before = copy.deepcopy(state)
    application = SherpaDataset(X=dataset.X[:7], feature_axis=dataset.feature_axis)
    applied = apply_nmf(application, state)

    assert applied.shape == (7, 3)
    assert np.all(np.isfinite(applied))
    assert np.all(applied >= 0.0)
    assert state == before
    with pytest.raises(ValueError, match="feature count"):
        apply_nmf(dataset.X[:7, :-1], state)
    wrong_axis = SherpaDataset(
        X=dataset.X[:7],
        feature_axis=FeatureAxis(
            values=np.asarray(dataset.feature_axis.values) + 0.25,
            labels=list(dataset.feature_axis.labels),
            units=dataset.feature_axis.units,
        ),
    )
    with pytest.raises(ValueError, match="fitted feature axis"):
        apply_nmf(wrong_axis, state)


def test_nmf_artifact_adapter_uses_the_same_fixed_basis_authority() -> None:
    dataset = _mixture()
    state = fit_nmf(dataset, parameters=_parameters())
    extract = NMFExtract(
        H=np.asarray(state["components"]),
        n_components=3,
        solver="mu",
        max_iter=1000,
        tol=1e-5,
        random_state=42,
    )
    application = dataset.X[:7]

    np.testing.assert_allclose(
        extract.transform(application),
        nmf_core.apply_nmf_basis(
            application,
            components=state["components"],
            parameters=_parameters(),
        ),
        rtol=0.0,
        atol=0.0,
    )
    metadata, arrays = extract.to_artifact()
    restored = NMFExtract.from_artifact(metadata, arrays)
    np.testing.assert_allclose(restored.transform(application), extract.transform(application), rtol=0.0, atol=0.0)


def test_nmf_rejects_implicit_correction_and_corrupted_state() -> None:
    matrix = _mixture().X
    matrix[0, 0] = -1e-12
    with pytest.raises(ValueError, match="scientifically justified correction"):
        fit_nmf(matrix, parameters=_parameters())

    state = fit_nmf(_mixture(), parameters=_parameters())
    for corruption in (
        {**state, "unexpected": True},
        {**state, "schema_version": "forged"},
        {**state, "components": state["components"][:-1]},
        {**state, "application_rule": "unbound"},
    ):
        with pytest.raises(ValueError):
            validate_nmf_state(corruption)


def test_nmf_fixed_workload_stays_inside_reviewed_ceiling() -> None:
    dataset = _mixture(samples=180, features=80)
    fit_nmf(dataset, parameters=_parameters(max_iter=400))

    with PerformanceCeiling("model.nmf", "180x80-three-components", 5.0).measure():
        fit_nmf(dataset, parameters=_parameters(max_iter=400))
