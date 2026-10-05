"""Canonical EFA and SIMPLISMA definition, projection, and cost proofs."""

from __future__ import annotations

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.axes import FeatureAxis
from spectra_sherpa.app.lib.fitted_state import EXTRACT_REGISTRY
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.modeling.efa_nodes import (
    EFANode,
    _canonical_efa_parameters,
    _efa_numeric_outputs,
)
from spectra_sherpa.app.services.dag.nodes.modeling.simplisma_nodes import (
    SIMPLISMANode,
    _canonical_simplisma_parameters,
    _simplisma_numeric_outputs,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility
from tests._optional_scp import HAS_SCP
from tests.performance_contract import PerformanceCeiling

pytestmark = pytest.mark.skipif(not HAS_SCP, reason="EFA and SIMPLISMA require SpectroChemPy")


def _mixture(*, samples: int = 48, features: int = 40) -> SherpaDataset:
    axis = np.linspace(900.0, 1800.0, features)
    profiles = np.vstack(
        (
            np.exp(-0.5 * ((axis - 1080.0) / 55.0) ** 2),
            np.exp(-0.5 * ((axis - 1360.0) / 75.0) ** 2),
            np.exp(-0.5 * ((axis - 1640.0) / 45.0) ** 2),
        )
    )
    progress = np.linspace(0.0, 1.0, samples)
    concentrations = np.column_stack(
        (
            np.clip(1.0 - 1.4 * progress, 0.0, None),
            np.sin(np.pi * progress) ** 2,
            np.clip(1.4 * progress - 0.4, 0.0, None),
        )
    )
    concentrations += 0.015
    return SherpaDataset(
        X=concentrations @ profiles + 0.001,
        feature_axis=FeatureAxis(
            values=axis,
            labels=[f"band-{index:03d}" for index in range(features)],
            units="cm^-1",
        ),
        data_role="X_spectra",
        is_time_series=True,
    )


def test_efa_refuses_arbitrary_sample_order_before_optional_runtime_loading() -> None:
    dataset = _mixture()
    dataset.is_time_series = False

    with pytest.raises(ValueError, match="explicitly ordered evolution coordinate"):
        _efa_numeric_outputs(dataset, parameters={"n_components": 3})


@pytest.mark.parametrize("node_type", ["model.efa", "model.simplisma"])
def test_scp_unmixing_nodes_have_closed_local_stateless_contracts(node_type: str) -> None:
    contract = node_registry.get_metadata(node_type).resolved_execution_contract()

    assert contract is not None
    assert contract.payload["operation_id"] == node_type
    assert contract.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["fitted_state_serializer"] is None
    assert contract.payload["deterministic"] is True
    assert any("SpectroChemPy" in citation for citation in contract.payload["citations"])


def test_scp_unmixing_parameter_contracts_are_closed() -> None:
    assert _canonical_efa_parameters({"n_components": 3}) == {"n_components": 3}
    assert _canonical_simplisma_parameters({"n_components": 3, "noise": 3.0, "tol": 0.1}) == {
        "n_components": 3,
        "noise": 3.0,
        "tol": 0.1,
    }
    for invalid in ({}, {"n_components": True}, {"n_components": 501}, {"n_components": 3, "extra": 1}):
        with pytest.raises(ValueError):
            _canonical_efa_parameters(invalid)
    for invalid in (
        {},
        {"n_components": 1, "noise": 3.0, "tol": 0.1},
        {"n_components": 3, "noise": 15.1, "tol": 0.1},
        {"n_components": 3, "noise": 3.0, "tol": 0.0},
        {"n_components": 3, "noise": 3.0, "tol": 0.1, "extra": 1},
    ):
        with pytest.raises(ValueError):
            _canonical_simplisma_parameters(invalid)


def test_exploratory_outputs_are_not_registered_as_replayable_model_artifacts() -> None:
    assert "efa" not in EXTRACT_REGISTRY
    assert "simplisma" not in EXTRACT_REGISTRY


@pytest.mark.asyncio
async def test_efa_live_and_generated_paths_share_exact_diagnostics() -> None:
    dataset = _mixture()
    node = EFANode("efa", {"n_components": 4})

    live = await node.execute(input_data=dataset)
    namespace = {"dataset": dataset, "results": {}}
    exec("\n".join(node.generate_python({"default": "dataset"}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["efa"]

    assert set(live.outputs) == {"default", "forward_eigenvalues", "backward_eigenvalues"}
    assert set(generated) == {"default", "forward_eigenvalues", "backward_eigenvalues"}
    np.testing.assert_allclose(live.outputs["forward_eigenvalues"].X, generated["forward_eigenvalues"])
    np.testing.assert_allclose(live.outputs["backward_eigenvalues"].X, generated["backward_eigenvalues"])
    assert live.diagnostics["evolution_order"] == "declared_sample_order"
    assert live.outputs["default"].meta["interpretation"] == "ordered_evolution_rank_diagnostic"


@pytest.mark.asyncio
async def test_simplisma_live_and_generated_paths_share_exact_estimates() -> None:
    dataset = _mixture()
    parameters = {"n_components": 3, "noise": 3.0, "tol": 0.1}
    node = SIMPLISMANode("simplisma", parameters)

    live = await node.execute(input_data=dataset)
    namespace = {"dataset": dataset, "results": {}}
    exec("\n".join(node.generate_python({"default": "dataset"}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["simplisma"]

    assert set(live.outputs) == {"default", "concentrations", "spectra", "purity_values"}
    assert set(generated) == {"default", "concentrations", "spectra", "purity_values"}
    np.testing.assert_allclose(live.outputs["concentrations"].X, generated["concentrations"])
    np.testing.assert_allclose(live.outputs["spectra"].X, generated["spectra"])
    np.testing.assert_allclose(live.outputs["purity_values"], generated["purity_values"])
    assert np.asarray(live.outputs["purity_values"]).shape == (3,)
    assert np.isfinite(live.outputs["purity_values"]).all()


def test_scp_unmixing_fixed_workloads_stay_inside_reviewed_ceiling() -> None:
    dataset = _mixture(samples=80, features=60)
    efa_parameters = {"n_components": 5}
    simplisma_parameters = {"n_components": 3, "noise": 3.0, "tol": 0.1}
    _efa_numeric_outputs(dataset, parameters=efa_parameters)
    _simplisma_numeric_outputs(dataset, parameters=simplisma_parameters)

    with PerformanceCeiling("model.efa", "80x60-five-components", 5.0).measure():
        _efa_numeric_outputs(dataset, parameters=efa_parameters)
    with PerformanceCeiling("model.simplisma", "80x60-three-components", 5.0).measure():
        _simplisma_numeric_outputs(dataset, parameters=simplisma_parameters)
