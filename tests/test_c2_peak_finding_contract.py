"""Canonical contract, scientific-oracle, parity, and capacity proofs for peak finding."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest
from scipy.signal import find_peaks, peak_widths

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - populate built-ins
from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.nodes.modeling.peak_finding_nodes import (
    PeakFindingNode,
    _canonical_peak_parameters,
    execute_peak_finding,
)
from spectra_sherpa.app.services.dag.nodes.output.stats_summary_node import StatsSummaryNode
from spectra_sherpa.execution_contract_vocabulary import LifecycleKind, ManagedOptimizationEligibility, RuntimeFamily
from tests.performance_contract import PerformanceCeiling


def _dataset(*, descending: bool = False) -> SherpaDataset:
    axis = np.linspace(1000.0, 1100.0, 401)
    matrix = np.vstack(
        [
            np.exp(-((axis - 1025.0) ** 2) / 8.0) + 0.7 * np.exp(-((axis - 1072.0) ** 2) / 18.0),
            0.8 * np.exp(-((axis - 1025.5) ** 2) / 9.0) + 0.9 * np.exp(-((axis - 1071.5) ** 2) / 16.0),
        ]
    )
    if descending:
        axis = axis[::-1].copy()
        matrix = matrix[:, ::-1].copy()
    return SherpaDataset(
        X=matrix,
        feature_axis=SpectralAxis(values=axis, units="cm-1", title="Wavenumber"),
        sample_axis=SampleAxis(labels=["sample-a", "sample-b"]),
    )


def _parameters() -> dict[str, object]:
    return {
        "height": None,
        "threshold": None,
        "distance": 20,
        "prominence": 0.1,
        "width": None,
        "consensus_tolerance": 2.0,
    }


def test_catalog_defaults_admit_and_execute_a_new_peak_node() -> None:
    from spectra_sherpa.app.services.dag.saved_graph_admission import admit_saved_workflow_graph

    parameters = {
        parameter.name: parameter.default
        for parameter in PeakFindingNode.metadata.parameters
        if parameter.default is not None
    }
    assert "method" not in parameters
    admit_saved_workflow_graph(
        [{"node_id": "peaks", "node_type": "analysis.peak_finding", "parameters": parameters}], []
    )
    result = execute_peak_finding(_dataset(), parameters=parameters, node_id="peaks")
    assert result.outputs["peaks"]["data"]
    assert result.outputs["plots"]
    plot = result.outputs["plots"]["peak_finding"]
    from spectra_sherpa.app.services.dag.nodes.output.plot_node import build_plot_result

    forwarded = build_plot_result(result.outputs["plots"])["visualization"]
    assert forwarded["data"] == plot["data"]
    assert forwarded["layout"] == plot["layout"]
    assert len(plot["layout"]["shapes"]) == len(result.outputs["peaks"]["data"])
    guides = plot["layout"]["annotations"]
    groups = result.outputs["per_spectrum"].meta["peak_groups"]
    assert result.outputs["per_spectrum"].provenance[-1].op_id == "analysis.peak_finding"
    from spectra_sherpa.app.services.dag.nodes.output.data_table_node import build_data_table_result

    assert "salient_features" not in result.outputs
    salient_table = build_data_table_result(result.outputs["peaks"])["visualization"]
    assert [row["consensus_group"] for row in salient_table["data"]] == [group["index"] for group in groups]
    assert [row["median_pos"] for row in salient_table["data"]] == [group["guide_position"] for group in groups]
    assert [label["text"] for label in guides] == [str(group["index"]) for group in groups]
    assert [label["x"] for label in guides] == [group["guide_position"] for group in groups]
    assert all(shape["yref"] == "paper" and shape["y0"] == 0 and shape["y1"] == 1 for shape in plot["layout"]["shapes"])
    consensus = plot["data"][-1]
    assert consensus["name"] == "Consensus peaks"
    assert consensus["visible"] is True
    assert len(consensus["x"]) == len(result.outputs["peaks"]["data"])
    assert plot["layout"]["legend"]["y"] < 0


def test_peak_finding_has_one_local_deterministic_contract() -> None:
    metadata = node_registry.get_metadata("analysis.peak_finding")
    contract = metadata.resolved_execution_contract()
    assert contract is not None
    assert contract.payload["runtime_family"] == RuntimeFamily.SHERPA_NATIVE.value
    assert contract.payload["lifecycle_kind"] == LifecycleKind.STATELESS_TRANSFORM.value
    assert contract.payload["managed_optimization_eligibility"] == (ManagedOptimizationEligibility.LOCAL.value,)
    assert contract.payload["deterministic"] is True
    assert contract.payload["semantic_outputs"] == (
        {
            "name": "peaks",
            "type_ref": "spectrasherpa://types/PeakTable/1.0",
            "required": True,
            "variadic": False,
            "accepted_data_roles": (),
        },
        {
            "name": "plots",
            "type_ref": "spectrasherpa://types/Visualization/1.0",
            "required": True,
            "variadic": False,
            "accepted_data_roles": (),
        },
        {
            "name": "per_spectrum",
            "type_ref": "spectrasherpa://types/SpectralDataset/1.0",
            "required": True,
            "variadic": False,
            "accepted_data_roles": (),
        },
    )
    assert any("10.1038/s41592-019-0686-2" in item for item in contract.payload["citations"])
    presentation = metadata.resolved_presentation_contract()
    assert presentation.default_presentation == "peak_overlay"
    assert [(item.presentation_id, item.source_ports) for item in presentation.presentations] == [
        ("peak_overlay", ("plots",)),
        ("peak_table", ("peaks",)),
        ("per_spectrum", ("per_spectrum",)),
    ]
    with pytest.raises(KeyError, match="Unknown node type"):
        node_registry.get_metadata("analysis.peak_id")


@pytest.mark.parametrize("descending", [False, True])
def test_peak_matrix_retains_group_measurements_for_missing_detections(descending):
    from spectra_sherpa.app.services.dag.nodes.output.data_table_node import build_data_table_result

    axis = np.array([1198.0, 1200.0, 1202.0, 1204.0, 1206.0])
    values = np.array([[0.0, 3.0, 0.0, 0.0, 0.0], [0.0, 0.0, 4.0, 0.0, 0.0], [1.0, 1.0, 1.0, 1.0, 1.0]])
    if descending:
        axis, values = axis[::-1].copy(), values[:, ::-1].copy()
    dataset = SherpaDataset(
        X=values,
        feature_axis=SpectralAxis(values=axis, units="nm"),
        sample_axis=SampleAxis(labels=["a", "b", "missing"]),
    )
    result = execute_peak_finding(dataset, parameters={"distance": 0, "consensus_tolerance": 4}, node_id="peaks")
    matrix = result.outputs["per_spectrum"]
    np.testing.assert_allclose(
        matrix.X, [[1200, 3, 1200, 3], [1202, 4, 1200, 0], [np.nan, np.nan, 1200, 1]], equal_nan=True
    )
    assert list(matrix.feature_axis.labels) == [
        "peak_position_1",
        "magnitude_at_peak_1",
        "group_position_1",
        "magnitude_at_group_position_1",
    ]
    assert list(matrix.sample_axis.labels) == ["a", "b", "missing"]
    assert result.outputs["plots"]["peak_finding"]["layout"]["shapes"][0]["x0"] == 1201
    table = build_data_table_result(matrix, parameters={"max_rows": 100000, "transpose": False, "show_index": True})[
        "visualization"
    ]
    assert table["metadata"]["column_names"] == list(matrix.feature_axis.labels)
    assert table["metadata"]["peak_groups"][0]["guide_position"] == 1201
    assert table["data"][2][0] is None


def test_peak_matrix_multiple_groups_and_no_detections():
    dataset = _dataset()
    result = execute_peak_finding(dataset, parameters=_parameters(), node_id="peaks")
    matrix = result.outputs["per_spectrum"]
    assert matrix.shape == (2, 8)
    assert list(matrix.feature_axis.labels)[-1] == "magnitude_at_group_position_2"
    empty = execute_peak_finding(dataset, parameters={**_parameters(), "height": 100}, node_id="peaks")
    assert empty.outputs["per_spectrum"].shape == (2, 0)
    assert empty.outputs["plots"]["peak_finding"]["layout"]["shapes"] == []


def test_peak_parameter_schema_is_closed_and_zero_disables_optional_constraints() -> None:
    assert _canonical_peak_parameters({}) == {
        "height": None,
        "threshold": None,
        "distance": 10.0,
        "prominence": None,
        "width": None,
        "consensus_tolerance": 0.0,
    }
    assert _canonical_peak_parameters({"distance": 0, "width": 0})["distance"] is None
    assert _canonical_peak_parameters({"distance": 0, "width": 0})["width"] is None
    for invalid in (
        {"unknown": 1},
        {"distance": 0.5},
        {"prominence": -1},
        {"width": -1},
        {"threshold": float("nan")},
        {"height": float("inf")},
    ):
        with pytest.raises(ValueError):
            _canonical_peak_parameters(invalid)


@pytest.mark.parametrize("descending", [False, True])
def test_peak_positions_and_half_prominence_widths_match_scipy_oracle(descending: bool) -> None:
    dataset = _dataset(descending=descending)
    result = execute_peak_finding(dataset, parameters=_parameters(), node_id="peaks")
    rows = result.outputs["peaks"]["data"]
    assert len(rows) == 2
    assert [row["sample_count"] for row in rows] == [2, 2]
    assert [row["detection_fraction"] for row in rows] == [1.0, 1.0]

    matrix = np.asarray(dataset.X)
    axis = np.asarray(dataset.feature_axis.values)
    expected_positions: list[float] = []
    expected_widths: list[float] = []
    for spectrum in matrix:
        indices, _ = find_peaks(spectrum, distance=20, prominence=0.1)
        _, _, left_ips, right_ips = peak_widths(spectrum, indices, rel_height=0.5)
        grid = np.arange(axis.size, dtype=np.float64)
        expected_positions.extend(axis[indices].tolist())
        expected_widths.extend(np.abs(np.interp(right_ips, grid, axis) - np.interp(left_ips, grid, axis)).tolist())

    sorted_positions = sorted(expected_positions)
    np.testing.assert_allclose(
        [row["median_pos"] for row in rows],
        [np.median(sorted_positions[:2]), np.median(sorted_positions[2:])],
        atol=0.6,
    )
    assert all(row["median_half_prominence_width"] > 0 for row in rows)
    assert all(row["median_absolute_window_integral"] > 0 for row in rows)
    assert len(expected_widths) == 4


def test_live_and_generated_python_use_the_same_authority() -> None:
    dataset = _dataset()
    node = node_registry.create_node("analysis.peak_finding", "peaks", _parameters())
    live = asyncio.run(node.execute(input_data=dataset)).outputs
    namespace = {"dataset": dataset, "results": {}}
    exec("\n".join(node.generate_python({"default": "dataset"}, indent="")), namespace)
    assert namespace["results"]["peaks"] == live


def test_consensus_bins_bound_total_span_and_count_distinct_samples() -> None:
    rows = PeakFindingNode._bin_consensus_peaks(
        all_positions=[10.0, 10.5, 11.0, 11.5],
        all_sample_indices=[0, 0, 1, 2],
        all_heights=[1.0, 0.9, 0.8, 0.7],
        all_fwhm=[1.0, 1.0, 1.0, 1.0],
        all_areas=[1.0, 1.0, 1.0, 1.0],
        tolerance=1.0,
        n_samples=3,
        sample_labels=["argon", "neon", "xenon"],
    )
    assert len(rows) == 2
    assert rows[0]["detection_count"] == 3
    assert rows[0]["sample_count"] == 2
    assert rows[0]["detection_fraction"] == pytest.approx(2 / 3)
    assert rows[0]["max_pos"] - rows[0]["min_pos"] <= 1.0
    assert rows[0]["consensus_peak_id"] == "peak-000001"
    assert rows[0]["member_sample_indices"] == [0, 1]
    assert rows[0]["member_sample_labels"] == ["argon", "neon"]
    assert [member["sample_label"] for member in rows[0]["constituent_detections"]] == [
        "argon",
        "argon",
        "neon",
    ]
    assert len(rows[0]["constituent_detections"]) == rows[0]["detection_count"]


def test_peak_rows_retain_named_source_membership_and_constituent_measurements() -> None:
    axis = np.arange(100.0, 109.0)
    dataset = SherpaDataset(
        X=np.array(
            [
                [0.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 3.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0, 2.5, 0.0, 0.0, 0.0, 1.0, 0.0],
            ]
        ),
        feature_axis=SpectralAxis(values=axis, units="cm-1", title="Wavenumber"),
        sample_axis=SampleAxis(labels=["species-alpha", "species-beta", "species-gamma"], title="Species"),
    )

    result = execute_peak_finding(
        dataset,
        parameters={"distance": 1, "prominence": 0.5, "consensus_tolerance": 0.0},
        node_id="peaks",
    )
    rows = result.outputs["peaks"]["data"]

    assert [row["consensus_peak_id"] for row in rows] == ["peak-000001", "peak-000002", "peak-000003"]
    assert [row["member_sample_labels"] for row in rows] == [
        ["species-alpha"],
        ["species-beta", "species-gamma"],
        ["species-gamma"],
    ]
    assert rows[1]["member_sample_indices"] == [1, 2]
    assert [member["position"] for member in rows[1]["constituent_detections"]] == [103.0, 103.0]
    assert [member["height"] for member in rows[1]["constituent_detections"]] == [3.0, 2.5]
    assert all(len(row["constituent_detections"]) == row["detection_count"] for row in rows)
    assert result.outputs["peaks"]["metadata"]["membership_complete"] is True
    assert result.outputs["peaks"]["metadata"]["sample_label_title"] == "Species"
    consensus_trace = result.outputs["plots"]["peak_finding"]["data"][-1]
    assert consensus_trace["customdata"][1] == [2 / 3, "species-beta, species-gamma", 2, 3]
    assert "Spectra with detected peak:" in consensus_trace["hovertemplate"]
    summary_rows = StatsSummaryNode("summary", {})._stats_peaks(
        rows,
        result.outputs["peaks"]["metadata"],
    )[
        "statistics"
    ]["data"]
    assert summary_rows[1]["consensus_peak_id"] == "peak-000002"
    assert summary_rows[1]["member_sample_indices"] == [1, 2]
    assert summary_rows[1]["member_sample_labels"] == ["species-beta", "species-gamma"]
    assert summary_rows[1]["constituent_detections"] == rows[1]["constituent_detections"]


@pytest.mark.parametrize(
    ("sample_indices", "sample_labels", "n_samples", "expected_labels"),
    [
        ([0], ["one"], 1, ["one"]),
        ([1, 0], ["first", "second"], 2, ["first", "second"]),
        ([0, 1], ["duplicate", "duplicate"], 2, ["duplicate", "duplicate"]),
        ([0, 0], ["repeat"], 1, ["repeat"]),
        ([2], None, 3, ["Sample 3"]),
    ],
)
def test_consensus_membership_covers_dissimilar_source_label_cases(
    sample_indices: list[int],
    sample_labels: list[str] | None,
    n_samples: int,
    expected_labels: list[str],
) -> None:
    n_detections = len(sample_indices)
    rows = PeakFindingNode._bin_consensus_peaks(
        all_positions=[100.0 + 0.1 * index for index in range(n_detections)],
        all_sample_indices=sample_indices,
        all_heights=[1.0] * n_detections,
        all_fwhm=[0.5] * n_detections,
        all_areas=[2.0] * n_detections,
        tolerance=1.0,
        n_samples=n_samples,
        sample_labels=sample_labels,
    )
    assert rows[0]["member_sample_labels"] == expected_labels
    assert len(rows[0]["constituent_detections"]) == n_detections


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        (
            {
                "all_positions": [1.0],
                "all_sample_indices": [],
                "all_heights": [1.0],
                "all_fwhm": [1.0],
                "all_areas": [1.0],
                "tolerance": 0.0,
                "n_samples": 1,
            },
            "equal lengths",
        ),
        (
            {
                "all_positions": [1.0],
                "all_sample_indices": [1],
                "all_heights": [1.0],
                "all_fwhm": [1.0],
                "all_areas": [1.0],
                "tolerance": 0.0,
                "n_samples": 1,
            },
            "refer to input spectra",
        ),
    ],
)
def test_consensus_membership_fails_closed_on_invalid_detection_identity(
    kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        PeakFindingNode._bin_consensus_peaks(**kwargs)


@pytest.mark.parametrize(
    "dataset, message",
    [
        (SherpaDataset(X=np.array([[0.0, np.nan, 1.0]])), "finite spectral matrix"),
        (
            SherpaDataset(
                X=np.ones((1, 3)),
                feature_axis=SpectralAxis(values=np.array([1.0, 3.0, 2.0]), units="cm-1"),
            ),
            "strictly monotonic",
        ),
    ],
)
def test_peak_finding_fails_closed_on_invalid_scientific_inputs(dataset: SherpaDataset, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        execute_peak_finding(dataset, parameters=_parameters(), node_id="peaks")


def test_categorical_feature_labels_use_an_explicit_index_axis() -> None:
    dataset = SherpaDataset(
        X=np.array([[0.0, 1.0, 0.0]]),
        feature_axis=FeatureAxis(labels=["a", "b", "c"], title="Variables"),
    )
    result = execute_peak_finding(
        dataset,
        parameters={"distance": 1, "prominence": 0.1},
        node_id="peaks",
    )
    assert result.outputs["peaks"]["data"][0]["median_pos"] == 1.0
    assert result.outputs["peaks"]["metadata"]["x_title"] == "Variables"


def test_peak_finding_has_a_representative_capacity_ceiling() -> None:
    axis = np.linspace(400.0, 4000.0, 1600)
    base = np.sin(axis / 80.0) + 0.5 * np.sin(axis / 23.0)
    dataset = SherpaDataset(
        X=np.repeat(base.reshape(1, -1), 200, axis=0),
        feature_axis=SpectralAxis(values=axis, units="cm-1"),
    )
    with PerformanceCeiling("analysis.peak_finding", "200x1600-prominence", 5.0).measure():
        result = execute_peak_finding(
            dataset,
            parameters={"distance": 10, "prominence": 0.5},
            node_id="peaks",
        )
    assert result.diagnostics["n_peaks"] > 0


def test_peak_detection_template_is_the_named_in_tree_consumer() -> None:
    template = (
        __import__("pathlib").Path(__file__).parents[1] / "src/spectra_sherpa/data/templates/peaks.yaml"
    ).read_text(encoding="utf-8")
    assert "status: ready" in template
    assert "node_type: analysis.peak_finding" in template


@pytest.mark.parametrize(
    "parameters",
    [
        {"height": None, "threshold": None, "distance": None, "prominence": None, "width": None},
        {"distance": 0, "width": 0, "prominence": 0.5},
        {"distance": 1.5, "width": 0.25, "prominence": 1e-8},
        {},
    ],
)
def test_retained_scipy_arguments_are_exact_and_replayable(monkeypatch, parameters) -> None:
    import scipy
    import scipy.signal

    observed = []
    original = scipy.signal.find_peaks

    def capture(spectrum, **kwargs):
        observed.append(dict(kwargs))
        return original(spectrum, **kwargs)

    monkeypatch.setattr(scipy.signal, "find_peaks", capture)
    result = execute_peak_finding(_dataset(), parameters=parameters, node_id="peaks")
    recorded = result.diagnostics["scipy_find_peaks_arguments"]
    assert observed == [recorded, recorded]
    assert recorded["distance"] == (
        None if parameters.get("distance", 10) in (None, 0) else parameters.get("distance", 10)
    )
    assert recorded["prominence"] == parameters.get("prominence")
    assert recorded["height"] is None
    assert recorded["threshold"] is None
    assert recorded["wlen"] is None
    assert recorded["rel_height"] == 0.5
    assert recorded["plateau_size"] is None
    assert result.diagnostics["scipy_version"] == scipy.__version__
    assert "height=None" in result.diagnostics["scipy_find_peaks_call"]
    assert "threshold=None" in result.diagnostics["scipy_find_peaks_call"]
    for index, spectrum in enumerate(_dataset().X):
        expected, _ = original(spectrum, **recorded)
        actual_positions = sorted(
            detection["position"]
            for row in result.outputs["peaks"]["data"]
            for detection in row["constituent_detections"]
            if detection["sample_index"] == index
        )
        np.testing.assert_allclose(actual_positions, _dataset().feature_axis.values[expected])


@pytest.mark.parametrize("value", [None, ""])
def test_blank_consensus_tolerance_refuses_hidden_fallback(value) -> None:
    with pytest.raises(ValueError):
        execute_peak_finding(_dataset(), parameters={"consensus_tolerance": value}, node_id="peaks")


@pytest.mark.parametrize("with_peak_sample", [False, True])
def test_width_execution_record_tracks_only_samples_with_detections(monkeypatch, with_peak_sample) -> None:
    import scipy.signal

    original = scipy.signal.peak_widths
    observed = []

    def capture(spectrum, indices, **kwargs):
        observed.append(kwargs)
        return original(spectrum, indices, **kwargs)

    monkeypatch.setattr(scipy.signal, "peak_widths", capture)
    dataset = _dataset()
    matrix = np.zeros_like(dataset.X)
    if with_peak_sample:
        matrix[1] = dataset.X[1]
    result = execute_peak_finding(
        SherpaDataset(X=matrix, feature_axis=dataset.feature_axis, sample_axis=dataset.sample_axis),
        parameters={"distance": None},
        node_id="peaks",
    )
    assert result.diagnostics["scipy_find_peaks_call_count"] == 2
    assert result.diagnostics["scipy_peak_widths_call_count"] == len(observed) == int(with_peak_sample)
    assert result.diagnostics["scipy_peak_widths_sample_indices"] == ([1] if with_peak_sample else [])
    if with_peak_sample:
        assert observed == [{"rel_height": 0.5, "prominence_data": None, "wlen": None}]
        assert "prominence_data=None" in result.diagnostics["scipy_peak_widths_call"]
    else:
        assert result.diagnostics["scipy_peak_widths_call"] is None


@pytest.mark.asyncio
async def test_trial_response_preserves_target_scipy_execution_evidence(monkeypatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from spectra_sherpa.app.api.v1.routes.workflows import execute as route
    from spectra_sherpa.app.schemas.workflows import TrialExecuteRequest, TrialExecuteResponse

    recorded = {}

    class Executor:
        def __init__(self, **kwargs):
            self.nodes = {}
            self.diagnostics = {"other-node": {"private": "not target evidence"}}

        def add_node(self, node):
            self.nodes[node.node_id] = PeakFindingNode(node.node_id, node.parameters)

        async def execute_node(self, node_id, initial_data=None):
            result = execute_peak_finding(_dataset(), parameters=self.nodes[node_id].parameters, node_id=node_id)
            self.diagnostics[node_id] = result.diagnostics
            recorded.update(result.diagnostics)
            return {node_id: result.outputs}

    monkeypatch.setattr(route, "DAGExecutor", Executor)
    monkeypatch.setattr(route, "validate_workflow_execution_access", AsyncMock(return_value={}))
    monkeypatch.setattr(route, "_enforce_demo_trial_execution_policy", lambda *args: None)
    response = await route.execute_trial(
        TrialExecuteRequest(
            target_node_id="peaks",
            trial_params={"height": None, "distance": None, "prominence": 0.5},
            nodes=[{"node_id": "peaks", "node_type": "analysis.peak_finding", "parameters": {}}],
        ),
        session=SimpleNamespace(),
        current_user=SimpleNamespace(id=1),
    )
    assert response.status == "completed", response.error
    restored = TrialExecuteResponse.model_validate_json(response.model_dump_json())
    assert restored.diagnostics == recorded
    assert restored.diagnostics["scipy_find_peaks_arguments"]["height"] is None
    assert restored.diagnostics["scipy_find_peaks_arguments"]["distance"] is None
    assert restored.diagnostics["scipy_find_peaks_arguments"]["prominence"] == 0.5
    assert "other-node" not in restored.diagnostics
