"""Canonical contract, parity, fail-closed, and capacity proofs for presentation nodes."""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
import spectra_sherpa.sdk as ss
from spectra_sherpa.app.lib.sherpa_dataset import (
    DatasetSourceIdentity,
    SampleAxis,
    SherpaDataset,
    SpectralAxis,
)
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.output.contour_plot_node import (
    _canonical_contour_parameters,
    build_contour_result,
)
from spectra_sherpa.app.services.dag.nodes.output.data_table_node import (
    _canonical_table_parameters,
    build_data_table_result,
)
from spectra_sherpa.app.services.dag.nodes.output.plot_node import _canonical_plot_parameters, build_plot_result
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


def _dataset(*, n_samples: int = 12, n_features: int = 20) -> SherpaDataset:
    values = np.arange(n_samples * n_features, dtype=np.float64).reshape(n_samples, n_features) / 100.0
    return SherpaDataset(
        X=values,
        feature_axis=SpectralAxis(
            values=np.linspace(4000.0, 400.0, n_features),
            units="cm-1",
            title="Wavenumber",
        ),
        sample_axis=SampleAxis(labels=[f"sample-{index + 1}" for index in range(n_samples)]),
        title="Canonical presentation fixture",
    )


def _spectral_cohort(*, cohort: str, instrument: str, offset: float) -> SherpaDataset:
    values = np.arange(15, dtype=np.float64).reshape(5, 3) + offset
    return SherpaDataset(
        X=values,
        feature_axis=SpectralAxis(
            values=np.array([1000.0, 1001.0, 1002.0]),
            units="cm-1",
            title="Wavenumber",
        ),
        sample_axis=SampleAxis(labels=[f"{cohort}-{index}" for index in range(5)]),
        source_identity=DatasetSourceIdentity(source_format="synthetic-fixture", object_name=cohort),
        extra={
            "reference.cohort": cohort,
            "reference.instrument_view": instrument,
        },
        units="absorbance",
        title=f"{cohort} spectra",
    )


@pytest.mark.parametrize(
    ("node_type", "sample_effect"),
    [
        ("output.plot", "filters_samples"),
        ("output.contour", "preserves_samples"),
        ("output.data_table", "filters_samples"),
    ],
)
def test_presentation_nodes_have_explicit_local_deterministic_contracts(
    node_type: str,
    sample_effect: str,
) -> None:
    metadata = node_registry.get_metadata(node_type)
    contract = metadata.resolved_execution_contract()
    assert contract is not None
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["deterministic"] is True
    assert contract.payload["sample_effect"] == sample_effect
    assert metadata.policy.safe_for_auto_apply is True
    assert metadata.policy.data_egress_risk == "none"


def test_res46_plot_execution_identity_binds_source_context_authority() -> None:
    contract = node_registry.get_metadata("output.plot").resolved_execution_contract()
    assert contract is not None
    component_ids = {component["component_id"] for component in contract.payload["implementation_components"]}
    assert "spectra_sherpa.app.services.dag.nodes.output.stats_summary_node" in component_ids


def test_presentation_parameter_schemas_are_closed_and_bounded() -> None:
    assert _canonical_plot_parameters({}) == {
        "plot_type": "spectra",
        "colorscale": "Viridis",
        "x_axis": 0,
        "y_axis": 1,
        "plot_key": "",
    }
    assert _canonical_contour_parameters({}) == {
        "colorscale": "Viridis",
        "plot_type": "heatmap",
        "reverse_x": False,
        "transpose": False,
    }
    assert _canonical_table_parameters({}) == {
        "max_rows": 100_000,
        "transpose": False,
        "show_index": True,
    }

    invalid_calls = (
        (_canonical_plot_parameters, {"x_axis": 0.5}),
        (_canonical_plot_parameters, {"unknown": True}),
        (_canonical_contour_parameters, {"plot_type": "invented"}),
        (_canonical_table_parameters, {"max_rows": 100_001}),
    )
    for validator, parameters in invalid_calls:
        with pytest.raises(ValueError):
            validator(parameters)

    with pytest.raises(ValueError):
        build_plot_result([[1.0]], parameters={"unknown": True})
    with pytest.raises(ValueError):
        build_contour_result([[1.0]], parameters={"reverse_x": "yes"})
    with pytest.raises(ValueError):
        build_data_table_result([[1.0]], parameters={"max_rows": 1})


@pytest.mark.parametrize(
    ("node_type", "parameters"),
    [
        ("output.plot", {"plot_type": "spectra"}),
        ("output.contour", {"plot_type": "heatmap", "reverse_x": False}),
        ("output.data_table", {"max_rows": 10}),
    ],
)
def test_live_and_generated_presentations_use_the_same_authority(
    node_type: str,
    parameters: dict[str, object],
) -> None:
    dataset = _dataset()
    node = node_registry.create_node(node_type, "presentation", parameters)
    live = asyncio.run(node.execute(input_data=dataset))

    generated = "\n".join(node.generate_python({"default": "dataset"}, indent=""))
    assert "build_" in generated
    assert "plotly.graph_objects" not in generated
    namespace = {"dataset": dataset, "results": {}}
    exec(generated, namespace)  # noqa: S102 - exercising the exported project source
    assert namespace["results"]["presentation"] == live


def test_res46_plot_compares_independently_bound_cohort_distributions() -> None:
    calibration = _spectral_cohort(cohort="calibration", instrument="instrument-1", offset=0.0)
    external = _spectral_cohort(cohort="external-test", instrument="instrument-1", offset=10.0)
    node = node_registry.create_node("output.plot", "overlay", {"plot_type": "spectra"})

    live = asyncio.run(node.execute(default=[calibration, external]))
    reversed_live = asyncio.run(node.execute(default=[external, calibration]))
    assert reversed_live == live
    visualization = live["visualization"]
    metadata = visualization["metadata"]

    assert len(visualization["data"]) == 6
    assert metadata["comparison_mode"] == "independent_cohort_distribution_overlay"
    assert metadata["distribution_summary"] == "mean_with_25th_to_75th_percentile_envelope"
    assert metadata["pooled_before_plot"] is False
    assert [source["n_samples"] for source in metadata["cohort_sources"]] == [5, 5]
    assert [source["source_context"]["reference"]["reference.cohort"] for source in metadata["cohort_sources"]] == [
        "calibration",
        "external-test",
    ]
    assert [trace["name"] for trace in visualization["data"]] == [
        "calibration / instrument-1 Q1",
        "calibration / instrument-1 interquartile envelope",
        "calibration / instrument-1 mean",
        "external-test / instrument-1 Q1",
        "external-test / instrument-1 interquartile envelope",
        "external-test / instrument-1 mean",
    ]
    assert [visualization["data"][index]["line"]["color"] for index in (2, 5)] == [
        "rgb(31,119,180)",
        "rgb(255,127,14)",
    ]
    for index, dataset in enumerate((calibration, external)):
        trace_offset = index * 3
        lower, upper, mean = visualization["data"][trace_offset : trace_offset + 3]
        np.testing.assert_allclose(lower["y"], np.quantile(dataset.X, 0.25, axis=0))
        np.testing.assert_allclose(upper["y"], np.quantile(dataset.X, 0.75, axis=0))
        np.testing.assert_allclose(mean["y"], np.mean(dataset.X, axis=0))
        assert upper["fill"] == "tonexty"
        assert lower["legendgroup"] == upper["legendgroup"] == mean["legendgroup"]
        assert np.less_equal(lower["y"], upper["y"]).all()

    namespace = {"calibration": calibration, "external": external, "results": {}}
    generated = "\n".join(node.generate_python({"default": ["external", "calibration"]}, indent=""))
    exec(generated, namespace)  # noqa: S102 - exercising exported project source
    assert namespace["results"]["overlay"] == live


def test_res46_plot_rejects_pooled_or_incompatible_comparison_inputs() -> None:
    calibration = _spectral_cohort(cohort="calibration", instrument="instrument-1", offset=0.0)
    external = _spectral_cohort(cohort="external-test", instrument="instrument-1", offset=10.0)

    single = build_plot_result([calibration], parameters={"plot_type": "spectra"})
    assert single == build_plot_result(calibration, parameters={"plot_type": "spectra"})

    with pytest.raises(ValueError, match="between two and eight"):
        build_plot_result([], parameters={"plot_type": "spectra"})

    incompatible = external.copy()
    incompatible.feature_axis = SpectralAxis(
        values=np.array([1000.0, 1001.5, 1002.0]),
        units="cm-1",
        title="Wavenumber",
    )
    with pytest.raises(ValueError, match="identical feature coordinates"):
        build_plot_result([calibration, incompatible], parameters={"plot_type": "spectra"})

    def unlabeled_dataset(name: str, offset: float) -> SherpaDataset:
        return SherpaDataset(
            X=np.arange(15, dtype=np.float64).reshape(5, 3) + offset,
            feature_axis=SpectralAxis(
                values=np.array([1000.0, 1001.0, 1002.0]),
                units="cm-1",
                title="Wavenumber",
            ),
            sample_axis=SampleAxis(labels=[f"{name}-{index}" for index in range(5)]),
            source_identity=DatasetSourceIdentity(source_format="synthetic-fixture", object_name=name),
            units="absorbance",
            title="",
        )

    unlabeled_a = unlabeled_dataset("unlabeled-a", 0.0)
    unlabeled_b = unlabeled_dataset("unlabeled-b", 10.0)
    for inputs in ([unlabeled_a, unlabeled_b], [unlabeled_b, unlabeled_a]):
        with pytest.raises(ValueError, match="require a bounded cohort, instrument, or dataset title label"):
            build_plot_result(inputs, parameters={"plot_type": "spectra"})


def test_res46_plot_order_is_total_for_casefold_colliding_labels() -> None:
    upper = _spectral_cohort(cohort="Alpha", instrument="", offset=0.0)
    lower = _spectral_cohort(cohort="alpha", instrument="", offset=0.0)

    forward = build_plot_result([upper, lower], parameters={"plot_type": "spectra"})
    reverse = build_plot_result([lower, upper], parameters={"plot_type": "spectra"})

    assert reverse == forward
    assert [source["label"] for source in forward["visualization"]["metadata"]["cohort_sources"]] == [
        "Alpha",
        "alpha",
    ]


def test_res46_two_deployment_sources_reach_one_variadic_plot_port() -> None:
    calibration = _spectral_cohort(cohort="calibration", instrument="instrument-1", offset=0.0)
    external = _spectral_cohort(cohort="external-test", instrument="instrument-1", offset=10.0)
    nodes = [
        {
            "node_id": "calibration",
            "node_type": "deploy.input",
            "parameters": {
                "stream_name": "calibration",
                "schema_version": ss.deployment.DEPLOYMENT_INPUT_SCHEMA,
            },
        },
        {
            "node_id": "application",
            "node_type": "deploy.input",
            "parameters": {
                "stream_name": "application",
                "schema_version": ss.deployment.DEPLOYMENT_INPUT_SCHEMA,
            },
        },
        {"node_id": "overlay", "node_type": "output.plot", "parameters": {"plot_type": "spectra"}},
    ]
    calibration_edge = {"from_node_id": "calibration", "to_node_id": "overlay"}
    application_edge = {"from_node_id": "application", "to_node_id": "overlay"}

    results = []
    for edges in ([calibration_edge, application_edge], [application_edge, calibration_edge]):
        workflow = ss.workflow.workflow_spec(nodes=nodes, edges=edges)
        execution = ss.runtime.execute_workflow(
            workflow,
            deployment_inputs={"calibration": calibration, "application": external},
        )
        results.append(execution.results["overlay"])

    assert results[0] == results[1]
    assert results[0] == build_plot_result([external, calibration], parameters={"plot_type": "spectra"})
    visualization = results[0]["visualization"]
    metadata = visualization["metadata"]
    assert metadata["source_count"] == 2
    assert metadata["pooled_before_plot"] is False
    assert [source["label"] for source in metadata["cohort_sources"]] == [
        "calibration / instrument-1",
        "external-test / instrument-1",
    ]
    assert [visualization["data"][index]["line"]["color"] for index in (2, 5)] == [
        "rgb(31,119,180)",
        "rgb(255,127,14)",
    ]
    assert node_registry.get_metadata("output.plot").input_ports[0].variadic is True


def test_res46_variadic_plot_keeps_existing_single_source_workflows() -> None:
    calibration = _spectral_cohort(cohort="calibration", instrument="instrument-1", offset=0.0)
    workflow = ss.workflow.workflow_spec(
        nodes=[
            {
                "node_id": "calibration",
                "node_type": "deploy.input",
                "parameters": {
                    "stream_name": "calibration",
                    "schema_version": ss.deployment.DEPLOYMENT_INPUT_SCHEMA,
                },
            },
            {"node_id": "plot", "node_type": "output.plot", "parameters": {"plot_type": "spectra"}},
        ],
        edges=[{"from_node_id": "calibration", "to_node_id": "plot"}],
    )

    execution = ss.runtime.execute_workflow(workflow, deployment_inputs={"calibration": calibration})

    visualization = execution.results["plot"]["visualization"]
    assert visualization["metadata"]["n_samples"] == calibration.n_samples
    assert visualization["metadata"]["shown_traces"] == calibration.n_samples


def test_res46_variadic_plot_preserves_one_component_numeric_series() -> None:
    result = build_plot_result([0.75], parameters={"plot_type": "explained_variance"})

    assert result["visualization"]["data"][0]["y"] == [75.0]
    assert result["visualization"]["data"][1]["y"] == [75.0]


@pytest.mark.parametrize(
    ("node_type", "payload"),
    [
        ("output.plot", object()),
        ("output.contour", {"unsupported": [1.0, 2.0]}),
        ("output.contour", np.array([[1.0, np.nan]])),
        ("output.data_table", object()),
        ("output.data_table", np.ones((2, 3, 4))),
    ],
)
def test_presentation_nodes_fail_closed_instead_of_fabricating_empty_success(
    node_type: str,
    payload: object,
) -> None:
    node = node_registry.create_node(node_type, "presentation", {})
    with pytest.raises(ValueError):
        asyncio.run(node.execute(input_data=payload))


@pytest.mark.parametrize("node_type", ["output.plot", "output.contour", "output.data_table"])
def test_presentation_nodes_have_representative_capacity_ceilings(node_type: str) -> None:
    dataset = _dataset(n_samples=200, n_features=1600)
    node = node_registry.create_node(node_type, "presentation", {})
    with PerformanceCeiling(node_type, "200x1600-dataset", 5.0).measure():
        result = asyncio.run(node.execute(input_data=dataset))
    assert result["visualization"]["data"]


def test_ready_projects_consume_all_three_presentation_nodes() -> None:
    templates = Path(__file__).parents[1] / "src/spectra_sherpa/data/templates"
    synthetic = (templates / "synthetic_ftir_benchmark.yaml").read_text(encoding="utf-8")
    assert "status: ready" in synthetic
    for node_type in ("output.plot", "output.contour", "output.data_table"):
        assert f"node_type: {node_type}" in synthetic
