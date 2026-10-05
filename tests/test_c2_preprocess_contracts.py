"""C2c contracts and fail-closed admission for retained local preprocessing."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.core.template_loader import TemplateLoader
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.meta_helpers import get_processing_history
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.preprocessing.derivative_node import (
    DerivativeNode,
    _derivative_dispatch,
)
from spectra_sherpa.app.services.dag.nodes.preprocessing.normalize_node import (
    NormalizeNode,
    _normalize_dispatch,
)
from spectra_sherpa.app.services.dag.nodes.preprocessing.norris_williams import norris_williams
from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode
from spectra_sherpa.app.services.dag.nodes.preprocessing.smooth_node import (
    SmoothNode,
    _smooth_dispatch,
)
from spectra_sherpa.execution_contract_vocabulary import (
    LifecycleKind,
    ManagedOptimizationEligibility,
    RuntimeFamily,
    WorkerCapability,
)
from tests.performance_contract import PerformanceCeiling


@pytest.mark.parametrize(
    ("node_type", "implementation_id"),
    [
        ("preprocess.normalize", "spectrasherpa.preprocess.normalize"),
        ("preprocess.derivative", "spectrasherpa.preprocess.derivative"),
    ],
)
def test_retained_preprocess_node_has_one_complete_managed_contract(node_type: str, implementation_id: str) -> None:
    metadata = node_registry.get_metadata(node_type)
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["contract_version"] == "4.0"
    assert contract.payload["operation_id"] == node_type
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
    assert contract.payload["implementation_id"] == implementation_id
    assert contract.payload["managed_optimization_eligibility"] == (
        ManagedOptimizationEligibility.LOCAL.value,
        ManagedOptimizationEligibility.DEVELOPMENT.value,
        ManagedOptimizationEligibility.FULL_REFIT.value,
    )
    assert contract.payload["managed_optimization_profiles"] == ("first_party_pls",)
    assert contract.payload["required_worker_capabilities"] == (WorkerCapability.READ_DATASET.value,)
    assert [port["name"] for port in contract.payload["semantic_inputs"]] == ["default"]
    assert [port["name"] for port in contract.payload["semantic_outputs"]] == ["default"]
    assert contract.payload["semantic_inputs"][0]["type_ref"] == "spectrasherpa://types/SpectralDataset/1.0"
    assert contract.payload["semantic_outputs"][0]["type_ref"] == "spectrasherpa://types/SpectralDataset/1.0"
    assert not any("._transforms" in component for component in contract.payload["implementation_components"])


def test_preprocess_implementations_are_isolated_from_prototype_companion_nodes() -> None:
    assert NormalizeNode.__module__.endswith(".normalize_node")
    assert DerivativeNode.__module__.endswith(".derivative_node")
    assert SmoothNode.__module__.endswith(".smooth_node")
    assert ScaleNode.__module__.endswith(".scale_node")
    assert node_registry.get_metadata("preprocess.scale").resolved_execution_contract() is not None
    with pytest.raises(KeyError):
        node_registry.get_metadata("preprocess.fitted_scale")


def test_python_export_delegates_to_the_same_canonical_dispatchers() -> None:
    normalize = NormalizeNode(node_id="normalize", parameters={"method": "snv"})
    derivative = DerivativeNode(
        node_id="derivative",
        parameters={"method": "savitzky_golay", "deriv": "1", "size": 5, "order": 2},
    )

    normalize_source = "\n".join(normalize.generate_python({"default": "input_data"}))
    derivative_source = "\n".join(derivative.generate_python({"default": "input_data"}))

    assert "NormalizeNode" in normalize_source
    assert "transform_dataset(input_data)" in normalize_source
    assert "_execute_derivative" in derivative_source
    assert "_derivative_dispatch" not in derivative_source
    assert "with_data(" not in normalize_source
    assert "savgol_filter" not in derivative_source


@pytest.mark.asyncio
async def test_derivative_live_and_exported_results_share_data_units_and_provenance() -> None:
    source = SherpaDataset(
        X=np.array([[0.0, 1.0, 4.0, 9.0, 16.0, 25.0, 36.0]]),
        feature_axis=SpectralAxis(values=np.arange(7, dtype=np.float64), units="cm-1"),
        units="absorbance",
        backend="numpy",
    )
    node = DerivativeNode(
        node_id="derivative",
        parameters={"method": "savitzky_golay", "deriv": "1", "size": 5, "order": 2},
    )

    live = (await node.execute(input_data=source)).outputs["default"]
    namespace: dict[str, Any] = {"input_data": source, "results": {}}
    exec("\n".join(node.generate_python({"default": "input_data"}, indent="")), namespace)
    generated = namespace["results"]["derivative"]

    np.testing.assert_allclose(generated.X, live.X)
    assert generated.units == live.units
    generated_history = get_processing_history(generated)
    live_history = get_processing_history(live)
    assert all(record.get("timestamp") for record in (*generated_history, *live_history))
    assert [{key: value for key, value in record.items() if key != "timestamp"} for record in generated_history] == [
        {key: value for key, value in record.items() if key != "timestamp"} for record in live_history
    ]


def test_smooth_has_one_complete_managed_contract_and_one_dispatcher() -> None:
    metadata = node_registry.get_metadata("preprocess.smooth")
    contract = metadata.resolved_execution_contract()

    assert contract is not None
    assert contract.payload["contract_version"] == "4.0"
    assert contract.payload["operation_id"] == "preprocess.smooth"
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
    assert contract.payload["implementation_id"] == "spectrasherpa.preprocess.smooth"
    assert contract.payload["managed_optimization_eligibility"] == (
        ManagedOptimizationEligibility.LOCAL.value,
        ManagedOptimizationEligibility.DEVELOPMENT.value,
        ManagedOptimizationEligibility.FULL_REFIT.value,
    )
    assert contract.payload["required_worker_capabilities"] == (WorkerCapability.READ_DATASET.value,)
    assert contract.payload["semantic_inputs"][0]["accepted_data_roles"] == ("X_spectra",)
    assert contract.payload["semantic_outputs"][0]["accepted_data_roles"] == ("X_spectra",)
    components = {item["component_id"] for item in contract.payload["implementation_components"]}
    assert "spectra_sherpa.app.services.dag.nodes.preprocessing.smooth_node" in components
    assert "spectra_sherpa.app.services.dag.nodes.preprocessing._transforms" not in components

    node = SmoothNode(node_id="smooth", parameters={"method": "savitzky_golay", "size": 5, "order": 2})
    source = "\n".join(node.generate_python({"default": "input_data"}, use_scp=True))
    assert "SmoothNode" in source
    assert "transform_dataset(input_data)" in source
    assert "savgol_filter" not in source
    assert ".smooth(" not in source


def test_smooth_admission_fills_one_exact_parameter_shape() -> None:
    node = node_registry.create_node("preprocess.smooth", "smooth", {"method": "gaussian", "sigma": 1})

    assert node.parameters == {
        "method": "gaussian",
        "size": 11,
        "order": 2,
        "lam": 100.0,
        "d": "2",
        "sigma": 1.0,
    }


@pytest.mark.parametrize(
    "parameters",
    [
        {"method": "savitzky_golay", "size": 10},
        {"method": "savitzky_golay", "size": 11.0},
        {"method": "savitzky_golay", "size": 5, "order": 5},
        {"method": "savitzky_golay", "sigma": 1.0},
        {"method": "whittaker", "size": 9},
        {"method": "whittaker", "d": 2},
        {"method": "gaussian", "sigma": 0.0},
        {"method": "gaussian", "lam": 200.0},
        {"method": "gaussian", "shortcut": "fast"},
    ],
)
def test_smooth_rejects_coercion_irrelevant_settings_and_extra_fields(
    parameters: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        node_registry.create_node("preprocess.smooth", "smooth", parameters)


def test_direct_smooth_dispatch_cannot_bypass_the_registered_grammar() -> None:
    data = np.arange(42, dtype=np.float64).reshape(2, 21)

    with pytest.raises(ValueError, match="exact integers"):
        _smooth_dispatch(data, size=11.0)
    with pytest.raises(ValueError, match="scientifically admissible"):
        _smooth_dispatch(data, size=10)
    with pytest.raises(ValueError, match="may not carry"):
        _smooth_dispatch(data, method="gaussian", sigma=1.0, lam=200.0)
    with pytest.raises(ValueError, match="greater than or equal to 0.1"):
        _smooth_dispatch(data, method="gaussian", sigma=0.05)
    with pytest.raises(ValueError, match="feature count"):
        _smooth_dispatch(data[:, :5], size=11)


@pytest.mark.parametrize(
    "transform",
    [
        lambda data: _normalize_dispatch(data, method="snv"),
        lambda data: _smooth_dispatch(data, method="savitzky_golay", size=5, order=2),
        lambda data: _derivative_dispatch(data, method="savitzky_golay", size=5, order=2),
        lambda data: norris_williams(data, gap=1, segment=1),
    ],
)
def test_numerical_preprocessing_refuses_missing_values_at_the_responsible_step(transform) -> None:
    data = np.arange(24, dtype=np.float64).reshape(2, 12)
    data[0, 4] = np.nan

    with pytest.raises(ValueError, match="finite input values"):
        transform(data)


@pytest.mark.asyncio
async def test_smooth_executes_the_same_admitted_savgol_transform() -> None:
    source = SherpaDataset(
        X=np.array([[0.0, 1.0, 4.0, 9.0, 16.0, 25.0, 36.0]]),
        backend="numpy",
    )
    node = node_registry.create_node(
        "preprocess.smooth",
        "smooth",
        {"method": "savitzky_golay", "size": 5, "order": 2},
    )

    execution = await node.execute(input_data=source)
    expected = _smooth_dispatch(source.X, **node.parameters)

    np.testing.assert_allclose(execution.outputs["default"].X, expected)
    assert execution.diagnostics["method"] == "savitzky_golay"


@pytest.mark.parametrize(
    "parameters",
    [
        {"method": "whittaker", "lam": 50.0, "d": "2"},
        {"method": "gaussian", "sigma": 1.25},
    ],
)
@pytest.mark.asyncio
async def test_local_smooth_methods_execute_only_the_admitted_dispatch(
    parameters: dict[str, object],
) -> None:
    source = SherpaDataset(
        X=np.array([[0.0, 1.0, 0.0, 4.0, 0.0, 1.0, 0.0]]),
        backend="numpy",
    )
    node = node_registry.create_node("preprocess.smooth", "smooth", parameters)

    execution = await node.execute(input_data=source)
    expected = _smooth_dispatch(source.X, **node.parameters)

    np.testing.assert_allclose(execution.outputs["default"].X, expected)
    assert execution.diagnostics["method"] == node.parameters["method"]


def test_sdk_and_registered_savgol_defaults_are_the_same() -> None:
    import inspect

    from spectra_sherpa.sdk.preprocess import savgol

    signature = inspect.signature(savgol)
    assert signature.parameters["window"].default == SmoothNode.metadata.canonicalize_parameters({})["size"]
    assert signature.parameters["polyorder"].default == SmoothNode.metadata.canonicalize_parameters({})["order"]


def test_shipped_savgol_starters_canonicalize_without_hidden_method_parameters() -> None:
    templates = {template["slug"]: template for template in TemplateLoader().load_all()}

    for slug in ("preprocessing", "peaks"):
        smooth = next(
            node for node in templates[slug]["template_data"]["nodes"] if node["node_type"] == "preprocess.smooth"
        )
        canonical = SmoothNode.metadata.canonicalize_parameters(smooth["parameters"])
        assert canonical["method"] == "savitzky_golay"
        assert canonical["lam"] == 100.0
        assert canonical["d"] == "2"
        assert canonical["sigma"] == 2.0


def test_normalize_admission_fills_one_exact_parameter_shape() -> None:
    node = node_registry.create_node("preprocess.normalize", "snv", {"method": "snv"})

    assert node.parameters == {
        "method": "snv",
        "std_ddof": 0,
        "scale_method": "max",
    }


@pytest.mark.parametrize(
    "parameters",
    [
        {"method": "max"},
        {"method": "snv", "reference": "median"},
        {"method": "msc"},
        {"method": "scale", "reference": "first"},
        {"method": "snv", "shortcut": "area"},
    ],
)
def test_normalize_rejects_aliases_irrelevant_settings_and_extra_fields(
    parameters: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        node_registry.create_node("preprocess.normalize", "normalize", parameters)


def test_direct_normalize_dispatch_cannot_bypass_the_registered_grammar() -> None:
    data = np.arange(12, dtype=np.float64).reshape(3, 4)

    with pytest.raises(ValueError, match="not admitted"):
        _normalize_dispatch(data, method="max")
    with pytest.raises(ValueError, match="not admitted"):
        _normalize_dispatch(data, method="msc")


@pytest.mark.asyncio
async def test_snv_executes_the_admitted_contract_without_hidden_dispatch() -> None:
    source = SherpaDataset(
        X=np.array([[1.0, 2.0, 4.0, 8.0], [2.0, 5.0, 10.0, 17.0]]),
        backend="numpy",
    )
    node = node_registry.create_node("preprocess.normalize", "snv", {"method": "snv"})

    execution = await node.execute(input_data=source)
    output = execution.outputs["default"]

    np.testing.assert_allclose(np.mean(output.X, axis=1), 0.0, atol=1e-12)
    np.testing.assert_allclose(np.std(output.X, axis=1), 1.0, atol=1e-12)
    assert execution.diagnostics["method"] == "snv"


@pytest.mark.parametrize(
    "parameters",
    [
        {"method": "savitzky_golay", "deriv": "0"},
        {"method": "savitzky_golay", "size": 10},
        {"method": "savitzky_golay", "size": 11.5},
        {"method": "savitzky_golay", "size": 5, "order": 5},
        {"method": "savitzky_golay", "deriv": "2", "order": 1},
        {"method": "savitzky_golay", "gap": 3},
        {"method": "norris_williams", "gap": 2.5},
        {"method": "norris_williams", "gap": 0},
        {"method": "norris_williams", "segment": -1},
        {"method": "norris_williams", "order": 3},
    ],
)
def test_derivative_rejects_smoothing_aliases_coercion_and_irrelevant_settings(
    parameters: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        node_registry.create_node("preprocess.derivative", "derivative", parameters)


def test_direct_derivative_dispatch_cannot_bypass_the_registered_grammar() -> None:
    data = np.arange(42, dtype=np.float64).reshape(2, 21)

    with pytest.raises(ValueError, match="order"):
        _derivative_dispatch(data, deriv="0")
    with pytest.raises(ValueError, match="scientifically admissible"):
        _derivative_dispatch(data, size=10)
    with pytest.raises(ValueError, match="exact integers"):
        _derivative_dispatch(data, size=11.5)
    with pytest.raises(ValueError, match="axis spacing"):
        _derivative_dispatch(data, delta=0.0)
    with pytest.raises(ValueError, match="positive integers"):
        _derivative_dispatch(data, method="norris_williams", gap=0)


def test_norris_williams_kernel_matches_the_published_gap_segment_definition() -> None:
    row = np.array([1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0])

    actual = norris_williams(row, gap=1, segment=2, deriv=1, delta=0.5)

    expected = np.zeros_like(row)
    center_spacing = (2 * 1 + 2 - 1) * 0.5
    for index in range(2, 7):
        left = row[index - 2 : index]
        right = row[index + 1 : index + 3]
        expected[index] = (np.mean(right) - np.mean(left)) / center_spacing
    np.testing.assert_array_equal(actual, expected)

    matrix = np.vstack([row, row + 10.0])
    second = norris_williams(matrix, gap=1, segment=2, deriv=2, delta=0.5)
    assert second.shape == matrix.shape
    np.testing.assert_array_equal(second[0], second[1])


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"gap": 0}, "gap"),
        ({"segment": 0}, "segment"),
        ({"deriv": 3}, "deriv"),
        ({"delta": float("nan")}, "delta"),
    ],
)
def test_norris_williams_kernel_rejects_undefined_parameters(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        norris_williams(np.arange(21, dtype=np.float64), **kwargs)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_derivative_executes_with_physical_axis_spacing_and_declared_output() -> None:
    x = np.arange(0.0, 22.0, 1.0)
    source = SherpaDataset(
        X=np.vstack([x**2, (x + 1.0) ** 2]),
        feature_axis=SpectralAxis(values=x, units="cm-1"),
        backend="numpy",
    )
    node = node_registry.create_node(
        "preprocess.derivative",
        "derivative",
        {"method": "savitzky_golay", "deriv": "1", "size": 5, "order": 2},
    )

    execution = await node.execute(input_data=source)
    output = execution.outputs["default"]

    np.testing.assert_allclose(output.X[0, 2:-2], 2.0 * x[2:-2], atol=1e-10)
    assert execution.diagnostics == {
        "method": "savitzky_golay",
        "derivative_order": 1,
        "axis_delta": 1.0,
    }
    assert output.units == "d/d(cm-1)"


@pytest.mark.asyncio
async def test_derivative_rejects_a_window_larger_than_the_runtime_feature_count() -> None:
    source = SherpaDataset(X=np.arange(9, dtype=np.float64).reshape(1, 9), backend="numpy")
    node = node_registry.create_node(
        "preprocess.derivative",
        "derivative",
        {"method": "savitzky_golay", "deriv": "1", "size": 11, "order": 2},
    )

    with pytest.raises(ValueError, match="feature count"):
        await node.execute(input_data=source)


def test_managed_derivative_workload_completes_within_shared_ceiling() -> None:
    rng = np.random.default_rng(44)
    matrix = rng.normal(size=(200, 1600))

    with PerformanceCeiling("preprocess.derivative", "savgol-200x1600", 5.0).measure():
        derivative = _derivative_dispatch(
            matrix,
            method="savitzky_golay",
            deriv="1",
            size=31,
            order=4,
            gap=5,
            segment=5,
        )

    assert derivative.shape == matrix.shape
    assert np.isfinite(derivative).all()


def test_managed_smoothing_workload_completes_within_shared_ceiling() -> None:
    matrix = np.random.default_rng(20260902).normal(size=(200, 1_600))

    with PerformanceCeiling("preprocess.smooth", "savgol-200x1600", 5.0).measure():
        smoothed = _smooth_dispatch(
            matrix,
            method="savitzky_golay",
            size=31,
            order=4,
        )

    assert smoothed.shape == matrix.shape
    assert np.isfinite(smoothed).all()
