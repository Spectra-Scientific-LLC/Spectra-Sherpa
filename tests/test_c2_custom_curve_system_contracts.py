"""Canonical contracts for local curve generators and system saturation."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.axes import SpectralAxis
from spectra_sherpa.app.lib.curves import initial_curve_points
from spectra_sherpa.app.lib.saturation_response import apply_saturation_transition
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.node_base import NodeMetadata, NodeParameter, node_registry
from spectra_sherpa.app.services.dag.nodes.custom_contracts import (
    build_catmull_rom_curve_result,
    build_concentration_curve_result,
    build_system_saturation_result,
    canonical_catmull_rom_curve_parameters,
    canonical_concentration_curve_parameters,
    canonical_system_saturation_parameters,
)
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


def _dataset(*, samples: int = 8, features: int = 12) -> SherpaDataset:
    return SherpaDataset(
        X=np.linspace(0.0, 4.0, samples * features, dtype=np.float64).reshape(samples, features),
        feature_axis=SpectralAxis(values=np.linspace(900.0, 1800.0, features), units="cm-1"),
        units="absorbance",
    )


def test_custom_curve_and_system_nodes_publish_exact_local_contracts() -> None:
    expected = {
        "custom.system_saturation": LifecycleKind.STATELESS_TRANSFORM.value,
        "custom.catmull_rom_curve": LifecycleKind.DATA_SOURCE.value,
        "custom.concentration_curve": LifecycleKind.DATA_SOURCE.value,
    }
    for node_type, lifecycle in expected.items():
        metadata = node_registry.get_metadata(node_type)
        contract = metadata.resolved_execution_contract()
        assert contract is not None
        assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
        assert contract.payload["lifecycle_kind"] == lifecycle
        assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
        assert contract.payload["citations"]
        assert metadata.output_ports and metadata.output_ports[0].type_ref.startswith("spectrasherpa://types/")


def test_json_parameters_require_a_node_specific_canonical_validator() -> None:
    metadata = NodeMetadata(
        node_type="test.unclosed_json",
        category="test",
        label="Unclosed JSON",
        description="Exercise the generic JSON admission guard",
        parameters=[NodeParameter(name="payload", label="Payload", param_type="json", default={})],
        input_ports=[],
        output_ports=[],
    )
    with pytest.raises(ValueError, match="unsupported canonical parameter type"):
        metadata.canonicalize_parameters({})


def test_curve_and_system_parameter_grammars_are_closed_and_explicit() -> None:
    system = canonical_system_saturation_parameters({"s_system": 2.0, "p_system": 1.0})
    assert system == {"p_system": 1.0, "s_system": 2.0}
    catmull = canonical_catmull_rom_curve_parameters({"n_points": 100, "max_concentration": 1.0, "control_points": []})
    assert catmull["control_points"] == initial_curve_points(11)
    concentration = canonical_concentration_curve_parameters(
        {"curve_type": "sigmoid", "n_points": 100, "max_concentration": 1.0, "center": 0.5, "width": 0.1}
    )
    assert concentration["curve_type"] == "sigmoid"

    invalid = (
        lambda: canonical_system_saturation_parameters({"s_system": 2.0, "p_system": 0.0}),
        lambda: canonical_catmull_rom_curve_parameters(
            {
                "n_points": 100,
                "max_concentration": 1.0,
                "control_points": [{"x": 10.0, "y": 0.5}, {"x": 10.0, "y": 0.6}],
            }
        ),
        lambda: canonical_catmull_rom_curve_parameters(
            {"n_points": 100, "max_concentration": 1.0, "control_points": [{"x": 0.0, "y": 2.0}]}
        ),
        lambda: canonical_concentration_curve_parameters(
            {"curve_type": "unknown", "n_points": 100, "max_concentration": 1.0, "center": 0.5, "width": 0.1}
        ),
        lambda: canonical_concentration_curve_parameters(
            {"curve_type": "linear", "n_points": 100, "max_concentration": 1.0, "center": 0.4, "width": 0.1}
        ),
    )
    for operation in invalid:
        with pytest.raises(ValueError):
            operation()


def test_system_saturation_live_generated_and_transition_paths_share_one_authority() -> None:
    dataset = _dataset()
    parameters = {"s_system": 2.0, "p_system": 1.5}
    node = node_registry.create_node("custom.system_saturation", "system", parameters)
    live = asyncio.run(node.execute(input_data=dataset))
    namespace = {"dataset": dataset, "results": {}}
    exec("\n".join(node.generate_python({"default": "dataset"}, indent="")), namespace)  # noqa: S102
    generated = namespace["results"]["system"]
    expected = apply_saturation_transition(dataset.X, 2.0, 1.5)

    np.testing.assert_array_equal(live.outputs["default"].X, expected)
    np.testing.assert_array_equal(generated.X, expected)
    assert live.diagnostics == generated.meta["system_saturation"]
    with pytest.raises(ValueError, match="non-negative"):
        build_system_saturation_result(SherpaDataset(X=np.array([[-1.0]])), parameters, node_id="system")


@pytest.mark.parametrize(
    "node_type,parameters,builder",
    [
        (
            "custom.catmull_rom_curve",
            {"n_points": 101, "max_concentration": 2.0, "control_points": []},
            build_catmull_rom_curve_result,
        ),
        (
            "custom.concentration_curve",
            {"curve_type": "gaussian", "n_points": 101, "max_concentration": 2.0, "center": 0.4, "width": 0.2},
            build_concentration_curve_result,
        ),
    ],
)
def test_curve_live_generated_and_core_paths_are_identical(node_type, parameters, builder) -> None:
    node = node_registry.create_node(node_type, "curve", parameters)
    live = asyncio.run(node.execute())
    namespace = {"results": {}}
    exec("\n".join(node.generate_python({}, indent="")), namespace)  # noqa: S102
    core, diagnostics = builder(node.metadata.canonicalize_parameters(parameters))
    np.testing.assert_array_equal(live.outputs["default"], core)
    np.testing.assert_array_equal(namespace["results"]["curve"], core)
    assert live.diagnostics == diagnostics


def test_custom_curve_and_system_fixed_workloads_stay_inside_reviewed_ceilings() -> None:
    dataset = _dataset(samples=200, features=1600)
    points = initial_curve_points(100)
    with PerformanceCeiling("custom.system_saturation", "200x1600-transition", 5.0).measure():
        build_system_saturation_result(dataset, {"s_system": 2.0, "p_system": 1.5}, node_id="system")
    with PerformanceCeiling("custom.catmull_rom_curve", "1000-points-100-controls", 5.0).measure():
        build_catmull_rom_curve_result({"n_points": 1000, "max_concentration": 1.0, "control_points": points})
    with PerformanceCeiling("custom.concentration_curve", "100000-points", 5.0).measure():
        build_concentration_curve_result(
            {"curve_type": "gaussian", "n_points": 100000, "max_concentration": 1.0, "center": 0.5, "width": 0.1}
        )
