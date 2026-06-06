import json

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import SampleAxis, SpectralAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset, TargetContext
from spectra_sherpa.app.lib.synthetic_references import load_synthetic_reference_as_sherpa, synthetic_reference_path
from spectra_sherpa.app.services.dag.nodes.modeling.library_compare_node import CompareVsLibraryNode


@pytest.mark.anyio
async def test_compare_vs_library_ranks_best_hqi_match():
    axis = np.array([1000.0, 1001.0, 1002.0, 1003.0])
    sample = SherpaDataset(
        X=np.array([[0.0, 1.0, 0.5, 0.0]]),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["unknown"]),
        data_role="X_spectra",
    )
    library = SherpaDataset(
        X=np.array(
            [
                [0.0, 1.0, 0.5, 0.0],
                [1.0, 0.0, 0.0, 1.0],
            ]
        ),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["Acetone", "Water"]),
        data_role="X_spectra",
    )

    node = CompareVsLibraryNode("compare_1", {"top_n": 2, "min_overlap_points": 2})
    result = await node.execute(sample=sample, library=library)

    rows = result.outputs["data"]
    assert rows[0]["sample"] == "unknown"
    assert rows[0]["library"] == "Acetone"
    assert rows[0]["hqi"] == pytest.approx(1000.0)
    assert rows[0]["cosine"] == pytest.approx(1.0)
    assert rows[0]["rank"] == 1
    assert rows[0]["hqi_band"] == "excellent"
    assert rows[0]["best_for_sample"] is True
    assert "matched points" in rows[0]["hqi_report"]
    hqi_rows = result.outputs["hqi_report"]["data"]
    assert len(hqi_rows) == 2
    assert hqi_rows[0]["sample"] == "unknown"
    assert hqi_rows[0]["library"] == "Acetone"
    assert hqi_rows[0]["rank"] == 1
    assert hqi_rows[0]["sample_rank"] == 1
    assert hqi_rows[0]["global_rank"] == 1
    assert hqi_rows[0]["hqi"] == pytest.approx(1000.0)
    assert hqi_rows[0]["hqi_band"] == "excellent"
    assert hqi_rows[0]["cosine"] == pytest.approx(1.0)
    assert hqi_rows[0]["pearson"] == pytest.approx(1.0)
    assert hqi_rows[0]["candidate_status"] == "auto_selected"
    assert hqi_rows[0]["overlap_points"] == 4
    assert hqi_rows[0]["coverage_fraction"] == pytest.approx(1.0)
    assert hqi_rows[0]["overlap_sufficient"] is True
    assert hqi_rows[1]["sample_rank"] == 2
    assert hqi_rows[1]["library"] == "Water"
    assert result.outputs["best_matches"]["data"][0]["library"] == "Acetone"
    assert (
        result.outputs["hqi_report"]["metadata"]["description"]
        == "Top library species ranked within each sample spectrum."
    )
    assert result.outputs["metadata"]["hqi_scale"] == "0-1000, squared non-negative uncentered cosine similarity"
    assert result.outputs["metadata"]["overlap_points"] == 4
    assert result.outputs["metadata"]["overlap_sufficient"] is True
    assert result.outputs["metadata"]["coverage_fraction"] == pytest.approx(1.0)
    assert result.diagnostics["top_hqi"] == pytest.approx(1000.0)
    assert result.diagnostics["best_match"] == "Acetone"
    assert result.diagnostics["hqi_band"] == "excellent"
    assert result.diagnostics["raw_hqi_band"] == "excellent"
    assert result.diagnostics["overlap_points"] == 4
    assert result.diagnostics["overlap_sufficient"] is True
    assert result.diagnostics["baseline_suspected"] is False
    assert result.diagnostics["n_auto_selected"] == 1
    assert result.diagnostics["n_auto_rejected"] == 0
    assert "library_compare" in result.outputs["plots"]
    assert result.outputs["plots"]["library_compare"]["layout"]["xaxis"]["autorange"] == "reversed"
    candidates = result.outputs["plots"]["library_compare_candidates"]["data"]
    assert candidates[0]["library"] == "Acetone"
    assert candidates[0]["y_units"] == "Sample response; library scaled"
    assert candidates[0]["sample_trace_index"] == 0
    assert candidates[0]["library_trace_index"] == 0
    assert "sample_x" not in candidates[0]
    traces = result.outputs["plots"]["library_compare_candidates"]
    assert traces["samples"][0]["sample"] == "unknown"
    assert traces["libraries"][0]["library"] == "Acetone"
    assert result.outputs["metadata"]["plot_payload"]["trace_mode"] == "indexed_sample_library_traces"


@pytest.mark.anyio
async def test_compare_vs_library_plot_payload_preserves_raw_trace_amplitude():
    axis = np.array([1000.0, 1001.0, 1002.0, 1003.0])
    sample = SherpaDataset(
        X=np.array([[0.0, 10.0, 5.0, 0.0]]),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["unknown"]),
        data_role="X_spectra",
    )
    library = SherpaDataset(
        X=np.array([[0.0, 2.0, 1.0, 0.0]]),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["Reference"]),
        data_role="X_spectra",
    )

    node = CompareVsLibraryNode("compare_1", {"top_n": 1, "min_overlap_points": 2})
    result = await node.execute(sample=sample, library=library)

    traces = result.outputs["plots"]["library_compare_candidates"]
    sample_trace = traces["samples"][0]
    library_trace = traces["libraries"][0]
    assert max(value for value in sample_trace["y"] if value is not None) == pytest.approx(10.0)
    assert max(value for value in library_trace["y"] if value is not None) == pytest.approx(2.0)
    assert traces["layout"]["yaxis"]["title"] == "Sample response; library scaled"


@pytest.mark.anyio
async def test_compare_vs_library_plot_payload_preserves_narrow_library_peaks():
    axis = np.arange(2000.0)
    sample_y = np.zeros(axis.size, dtype=float)
    library_y = np.zeros(axis.size, dtype=float)
    sample_y[1234] = 50.0
    library_y[1234] = 2.0
    sample_y[1233] = sample_y[1235] = 5.0
    library_y[1233] = library_y[1235] = 0.2
    sample = SherpaDataset(
        X=sample_y.reshape(1, -1),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["sharp unknown"]),
        data_role="X_spectra",
    )
    library = SherpaDataset(
        X=library_y.reshape(1, -1),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["Sharp Reference"]),
        data_role="X_spectra",
    )

    node = CompareVsLibraryNode("compare_1", {"top_n": 1, "min_overlap_points": 20})
    result = await node.execute(sample=sample, library=library)

    library_trace = result.outputs["plots"]["library_compare_candidates"]["libraries"][0]
    assert len(library_trace["x"]) <= 800
    assert max(value for value in library_trace["y"] if value is not None) == pytest.approx(2.0)
    peak_index = library_trace["y"].index(2.0)
    assert library_trace["x"][peak_index] == pytest.approx(1234.0)


@pytest.mark.anyio
async def test_compare_vs_library_reports_uncentered_cosine_separately_from_pearson():
    axis = np.array([1000.0, 1001.0, 1002.0, 1003.0])
    sample = SherpaDataset(
        X=np.array([[2.0, 3.0, 4.0, 5.0]]),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["offset unknown"]),
        data_role="X_spectra",
    )
    library = SherpaDataset(
        X=np.array([[1.0, 2.0, 3.0, 4.0]]),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["Offset Reference"]),
        data_role="X_spectra",
    )

    node = CompareVsLibraryNode("compare_1", {"top_n": 1, "min_overlap_points": 2})
    result = await node.execute(sample=sample, library=library)

    row = result.outputs["data"][0]
    expected_cosine = float(
        np.dot(sample.data[0], library.data[0]) / (np.linalg.norm(sample.data[0]) * np.linalg.norm(library.data[0]))
    )
    assert row["cosine"] == pytest.approx(expected_cosine)
    assert row["pearson"] == pytest.approx(1.0)
    assert row["cosine"] != pytest.approx(row["pearson"])
    assert row["hqi"] == pytest.approx(1000.0 * expected_cosine**2)


@pytest.mark.anyio
async def test_compare_vs_library_band_limited_hqi_scales_diagnostic_bands():
    axis = np.arange(20.0)
    library_y = np.zeros(axis.size)
    library_y[2:5] = [50.0, 100.0, 50.0]
    library_y[14:17] = [0.5, 1.0, 0.5]
    sample_y = np.zeros(axis.size)
    sample_y[14:17] = [0.5, 1.0, 0.5]
    sample = SherpaDataset(
        X=sample_y.reshape(1, -1),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["weak-band mixture"]),
        data_role="X_spectra",
    )
    library = SherpaDataset(
        X=library_y.reshape(1, -1),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["Two Band Reference"]),
        data_role="X_spectra",
    )

    node = CompareVsLibraryNode(
        "compare_1",
        {
            "top_n": 1,
            "hqi_mode": "band_limited",
            "diagnostic_band_threshold": 0.001,
            "min_overlap_points": 2,
        },
    )
    result = await node.execute(sample=sample, library=library)

    row = result.outputs["data"][0]
    assert row["hqi_mode"] == "band_limited"
    assert row["diagnostic_band_count"] == 2
    assert row["diagnostic_points"] == 6
    assert row["band_limited_hqi"] == pytest.approx(row["hqi"])
    assert row["band_limited_hqi"] > row["whole_hqi"] * 1000
    assert row["whole_hqi"] < 1.0
    assert row["band_limited_hqi"] == pytest.approx(500.0)
    assert "diagnostic bands 2" in row["hqi_report"]
    assert result.outputs["metadata"]["hqi_mode"] == "band_limited"
    assert "library diagnostic bands" in result.outputs["metadata"]["hqi_scale"]
    assert result.diagnostics["top_band_limited_hqi"] == pytest.approx(row["band_limited_hqi"])


@pytest.mark.anyio
async def test_compare_vs_library_thresholds_mark_selection_and_rejection():
    axis = np.array([1000.0, 1001.0, 1002.0, 1003.0])
    sample = SherpaDataset(
        X=np.array(
            [
                [0.0, 1.0, 0.5, 0.0],
                [0.2, 0.0, 0.0, 0.1],
            ]
        ),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["unknown strong", "unknown weak"]),
        data_role="X_spectra",
    )
    library = SherpaDataset(
        X=np.array(
            [
                [0.0, 1.0, 0.5, 0.0],
                [0.0, 0.0, 1.0, 0.0],
            ]
        ),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["Acetone", "Water"]),
        data_role="X_spectra",
    )

    node = CompareVsLibraryNode(
        "compare_1",
        {
            "top_n": 4,
            "hqi_accept_threshold": 900,
            "hqi_reject_threshold": 500,
            "min_overlap_points": 2,
        },
    )
    result = await node.execute(sample=sample, library=library)

    strong = next(
        row for row in result.outputs["data"] if row["sample"] == "unknown strong" and row["library"] == "Acetone"
    )
    weak_rows = [row for row in result.outputs["data"] if row["sample"] == "unknown weak"]
    assert strong["candidate_status"] == "auto_selected"
    assert strong["auto_selected"] is True
    assert weak_rows
    assert all(row["candidate_status"] == "rejected" for row in weak_rows)
    assert all(row["auto_rejected"] is True for row in weak_rows)
    assert result.outputs["metadata"]["hqi_accept_threshold"] == 900
    assert result.outputs["metadata"]["hqi_reject_threshold"] == 500
    assert result.diagnostics["n_auto_selected"] == 1
    assert result.diagnostics["n_auto_rejected"] == len(weak_rows)


@pytest.mark.anyio
async def test_compare_vs_library_reports_synthetic_known_answer_presence():
    axis = np.array([1000.0, 1001.0, 1002.0, 1003.0])
    sample = SherpaDataset(
        X=np.array(
            [
                [0.0, 1.0, 0.5, 0.0],
                [1.0, 0.0, 0.0, 1.0],
            ]
        ),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["mixture 1", "mixture 2"]),
        data_role="X_spectra",
        target=np.array(
            [
                [25.0, 0.0],
                [0.0, 80.0],
            ]
        ),
        target_context=TargetContext(
            target_type="continuous",
            target_name="synthetic concentration",
            target_names=["Acetone", "Water"],
            target_units="ppm",
        ),
    )
    library = SherpaDataset(
        X=np.array(
            [
                [0.0, 1.0, 0.5, 0.0],
                [1.0, 0.0, 0.0, 1.0],
            ]
        ),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["Acetone", "Water"]),
        data_role="X_spectra",
    )

    node = CompareVsLibraryNode(
        "compare_1",
        {"top_n": 2, "hqi_accept_threshold": 900, "min_overlap_points": 2},
    )
    result = await node.execute(sample=sample, library=library)

    acetone = next(
        row for row in result.outputs["data"] if row["sample"] == "mixture 1" and row["library"] == "Acetone"
    )
    water = next(row for row in result.outputs["data"] if row["sample"] == "mixture 1" and row["library"] == "Water")
    assert acetone["known_component"] == "Acetone"
    assert acetone["known_concentration"] == pytest.approx(25.0)
    assert acetone["known_present"] is True
    assert water["known_component"] == "Water"
    assert water["known_concentration"] == pytest.approx(0.0)
    assert water["known_present"] is False
    assert "ground truth: known present" in acetone["hqi_report"]
    assert result.outputs["metadata"]["known_answer_available"] is True
    assert result.outputs["metadata"]["best_match_known_present_rate"] == pytest.approx(1.0)
    assert result.outputs["metadata"]["auto_selected_known_present_rate"] == pytest.approx(1.0)
    assert result.diagnostics["known_answer_available"] is True
    assert result.diagnostics["best_match_known_present_rate"] == pytest.approx(1.0)


@pytest.mark.anyio
async def test_compare_vs_library_caps_confidence_on_thin_overlap():
    sample_axis = np.arange(1000.0, 1100.0)
    library_axis = np.arange(1090.0, 1100.0)
    sample = SherpaDataset(
        X=np.ones((1, sample_axis.size)),
        feature_axis=SpectralAxis(values=sample_axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["unknown"]),
        data_role="X_spectra",
    )
    library = SherpaDataset(
        X=np.ones((1, library_axis.size)),
        feature_axis=SpectralAxis(values=library_axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["Tiny Window Reference"]),
        data_role="X_spectra",
    )

    node = CompareVsLibraryNode(
        "compare_1",
        {
            "top_n": 1,
            "hqi_accept_threshold": 900,
            "min_overlap_coverage": 0.5,
            "min_overlap_points": 20,
        },
    )
    result = await node.execute(sample=sample, library=library)

    row = result.outputs["data"][0]
    assert row["hqi"] == pytest.approx(1000.0)
    assert row["raw_hqi_band"] == "excellent"
    assert row["hqi_band"] == "moderate"
    assert row["overlap_sufficient"] is False
    assert row["coverage_fraction"] < 0.5
    assert row["candidate_status"] == "review"
    assert "thin_overlap" in row["confidence_caveats"]
    assert result.diagnostics["overlap_sufficient"] is False
    assert result.diagnostics["coverage_fraction"] == pytest.approx(row["coverage_fraction"])


@pytest.mark.anyio
async def test_compare_vs_library_flags_baseline_dominated_matches():
    axis = np.array([1000.0, 1001.0, 1002.0, 1003.0])
    sample = SherpaDataset(
        X=np.array([[10.0, 10.0, 10.0, 10.0]]),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["offset unknown"]),
        data_role="X_spectra",
    )
    library = SherpaDataset(
        X=np.array([[1.0, 2.0, 2.0, 2.0]]),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["Offset Reference"]),
        data_role="X_spectra",
    )

    node = CompareVsLibraryNode(
        "compare_1",
        {
            "top_n": 1,
            "hqi_accept_threshold": 900,
            "min_overlap_points": 2,
            "baseline_gap_threshold": 0.25,
        },
    )
    result = await node.execute(sample=sample, library=library)

    row = result.outputs["data"][0]
    assert row["hqi"] >= 900
    assert row["raw_hqi_band"] == "excellent"
    assert row["hqi_band"] == "moderate"
    assert row["baseline_suspected"] is True
    assert row["candidate_status"] == "review"
    assert "baseline_offset" in row["confidence_caveats"]
    assert result.diagnostics["baseline_suspected"] is True
    assert result.diagnostics["n_baseline_suspected"] == 1


@pytest.mark.anyio
async def test_compare_vs_library_uses_per_candidate_overlap_not_global_library_intersection():
    sample_axis = np.arange(600.0, 3301.0, 1.0)
    library_axis = sample_axis.copy()
    sample_y = np.zeros(sample_axis.size)
    methane_mask = (sample_axis >= 3000.0) & (sample_axis <= 3100.0)
    sample_y[methane_mask] = np.sin(np.linspace(0, np.pi, int(np.count_nonzero(methane_mask))))

    methane = np.full(library_axis.size, np.nan)
    methane[methane_mask] = sample_y[methane_mask]
    oxygen = np.full(library_axis.size, np.nan)
    oxygen_mask = (library_axis >= 1300.0) & (library_axis <= 1400.0)
    oxygen[oxygen_mask] = 1.0

    sample = SherpaDataset(
        X=sample_y.reshape(1, -1),
        feature_axis=SpectralAxis(values=sample_axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["unknown methane"]),
        data_role="X_spectra",
    )
    library = SherpaDataset(
        X=np.vstack([methane, oxygen]),
        feature_axis=SpectralAxis(values=library_axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["Methane", "Oxygen"]),
        data_role="X_spectra",
    )

    node = CompareVsLibraryNode("compare_1", {"top_n": 2, "min_overlap_points": 20})
    result = await node.execute(sample=sample, library=library)

    methane_row = next(row for row in result.outputs["data"] if row["library"] == "Methane")
    assert methane_row["overlap_min"] == pytest.approx(3000.0)
    assert methane_row["overlap_max"] == pytest.approx(3100.0)
    assert methane_row["overlap_points"] == 101
    assert methane_row["hqi"] == pytest.approx(1000.0)
    assert result.outputs["metadata"]["overlap_scope"] == "per sample-library pair"
    candidate = next(
        item for item in result.outputs["plots"]["library_compare_candidates"]["data"] if item["library"] == "Methane"
    )
    traces = result.outputs["plots"]["library_compare_candidates"]
    sample_trace = traces["samples"][candidate["sample_trace_index"]]
    library_trace = traces["libraries"][candidate["library_trace_index"]]
    assert min(sample_trace["x"]) == pytest.approx(600.0)
    assert max(sample_trace["x"]) == pytest.approx(3300.0)
    assert min(library_trace["x"]) == pytest.approx(3000.0)
    assert max(library_trace["x"]) == pytest.approx(3100.0)


@pytest.mark.anyio
async def test_compare_vs_library_does_not_count_or_plot_across_library_gaps():
    axis = np.arange(1000.0, 2101.0, 1.0)
    left_band = (axis >= 1000.0) & (axis <= 1100.0)
    right_band = (axis >= 2000.0) & (axis <= 2100.0)
    measured_bands = left_band | right_band
    sample_y = np.zeros(axis.size)
    sample_y[measured_bands] = 1.0
    library_y = np.full(axis.size, np.nan)
    library_y[measured_bands] = 1.0

    sample = SherpaDataset(
        X=sample_y.reshape(1, -1),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["unknown two-band"]),
        data_role="X_spectra",
    )
    library = SherpaDataset(
        X=library_y.reshape(1, -1),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["Two Band Reference"]),
        data_role="X_spectra",
    )

    node = CompareVsLibraryNode("compare_1", {"top_n": 1, "min_overlap_points": 20})
    result = await node.execute(sample=sample, library=library)

    row = result.outputs["data"][0]
    assert row["hqi"] == pytest.approx(1000.0)
    assert row["overlap_min"] == pytest.approx(1000.0)
    assert row["overlap_max"] == pytest.approx(2100.0)
    assert row["overlap_points"] == 202
    assert row["overlap_span"] == pytest.approx(200.0)
    assert row["library_coverage"] == pytest.approx(1.0)
    assert row["sample_coverage"] == pytest.approx(200.0 / 1100.0)

    library_trace = result.outputs["plots"]["library_compare_candidates"]["libraries"][0]
    assert None in library_trace["x"]
    gap_index = library_trace["x"].index(None)
    assert library_trace["y"][gap_index] is None


@pytest.mark.anyio
async def test_compare_vs_library_plots_on_aligned_scoring_axis():
    sample_axis = np.linspace(600.0, 3300.0, 5401)
    library_axis = np.arange(900.25, 1800.26, 1.0)

    def peak(x: np.ndarray) -> np.ndarray:
        return np.exp(-((x - 1260.0) ** 2) / (2 * 16.0**2))

    sample_y = peak(sample_axis)
    library_y = peak(library_axis)
    sample = SherpaDataset(
        X=sample_y.reshape(1, -1),
        feature_axis=SpectralAxis(values=sample_axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["unknown full-range"]),
        data_role="X_spectra",
    )
    library = SherpaDataset(
        X=library_y.reshape(1, -1),
        feature_axis=SpectralAxis(values=library_axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["Reference Peak"]),
        data_role="X_spectra",
    )

    node = CompareVsLibraryNode("compare_1", {"top_n": 1, "min_overlap_points": 20})
    result = await node.execute(sample=sample, library=library)

    row = result.outputs["data"][0]
    assert row["interpolation"] == "single_pass_pchip_to_sample_grid"
    assert row["grid_aligned"] is True
    assert row["hqi"] > 999.0
    traces = result.outputs["plots"]["library_compare_candidates"]
    candidate = traces["data"][0]
    sample_trace = traces["samples"][candidate["sample_trace_index"]]
    library_trace = traces["libraries"][candidate["library_trace_index"]]
    assert len(sample_trace["x"]) <= 800
    assert min(sample_trace["x"]) == pytest.approx(900.5)
    assert max(sample_trace["x"]) == pytest.approx(1800.0)
    assert min(library_trace["x"]) == pytest.approx(900.5)
    assert max(library_trace["x"]) == pytest.approx(1800.0)
    assert traces["metadata"]["grid_aligned"] is True


@pytest.mark.anyio
async def test_compare_vs_library_reports_aligned_half_wavenumber_grid():
    axis = np.arange(600.0, 3300.0 + 0.25, 0.5)
    peak = np.exp(-((axis - 1304.5) ** 2) / (2 * 2.0**2))
    sample = SherpaDataset(
        X=peak.reshape(1, -1),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["unknown aligned"]),
        data_role="X_spectra",
    )
    library = SherpaDataset(
        X=peak.reshape(1, -1),
        feature_axis=SpectralAxis(values=axis, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=["Aligned Reference"]),
        data_role="X_spectra",
    )

    node = CompareVsLibraryNode("compare_1", {"top_n": 1, "min_overlap_points": 20})
    result = await node.execute(sample=sample, library=library)

    row = result.outputs["data"][0]
    assert row["hqi"] == pytest.approx(1000.0)
    assert row["sample_spacing"] == pytest.approx(0.5)
    assert row["library_spacing"] == pytest.approx(0.5)
    assert row["alignment_spacing"] == pytest.approx(0.5)
    assert row["grid_aligned"] is True
    assert row["resample_warning"] is False
    candidate = result.outputs["plots"]["library_compare_candidates"]["data"][0]
    assert candidate["grid_aligned"] is True
    assert candidate["alignment_spacing"] == pytest.approx(0.5)


@pytest.mark.anyio
async def test_atmospheric_benchmark_supplied_components_self_match_high_hqi():
    payload = np.load(synthetic_reference_path("Synthetic_atmospheric-6"), allow_pickle=False)
    ground_truth = json.loads(str(payload["ground_truth_json"].item()))
    component_names = [str(name) for name in ground_truth["component_names"]]
    selected_names = ["Water", "Carbon dioxide", "Methane"]
    selected_indices = [component_names.index(name) for name in selected_names]
    wavenumber = np.asarray(payload["wavenumber"], dtype=float)
    pure_spectra = np.asarray(payload["S"], dtype=float)[selected_indices]
    pure = SherpaDataset(
        X=pure_spectra,
        feature_axis=SpectralAxis(values=wavenumber, title="Wavenumber", units="cm-1"),
        sample_axis=SampleAxis(labels=selected_names),
        data_role="X_spectra",
    )

    node = CompareVsLibraryNode("compare_1", {"top_n": len(selected_names), "min_overlap_points": 20})
    result = await node.execute(sample=pure, library=pure)

    for name in selected_names:
        row = next(item for item in result.outputs["data"] if item["sample"] == name and item["library"] == name)
        assert row["hqi"] == pytest.approx(1000.0)
        assert row["sample_rank"] == 1
        assert row["hqi_band"] == "excellent"


@pytest.mark.anyio
async def test_atmospheric_benchmark_mixture_identifies_present_hitran_components():
    sample = load_synthetic_reference_as_sherpa("Synthetic_atmospheric-6")
    library = load_synthetic_reference_as_sherpa("Library_atmospheric-9")

    node = CompareVsLibraryNode(
        "compare_1",
        {
            "top_n": 9,
            "min_overlap_points": 20,
            "hqi_mode": "band_limited",
            "diagnostic_band_threshold": 0.2,
        },
    )
    result = await node.execute(sample=sample, library=library)

    metadata = result.outputs["metadata"]
    assert metadata["sample_spacing"] == pytest.approx(0.5)
    assert metadata["library_spacing"] == pytest.approx(0.5)
    assert metadata["alignment_spacing"] == pytest.approx(0.5)
    assert metadata["grid_aligned"] is True
    assert metadata["resample_warning"] is False

    sample_rows = {row["library"]: row for row in result.outputs["data"] if row["sample_index"] == 0}
    expected_min_hqi = {
        "Nitrous oxide": 990.0,
        "Carbon dioxide": 990.0,
        "Water": 900.0,
        "Nitrogen dioxide": 900.0,
        "Carbon monoxide": 750.0,
    }
    for library_name, min_hqi in expected_min_hqi.items():
        row = sample_rows[library_name]
        assert row["known_present"] is True
        assert row["hqi"] >= min_hqi
        assert row["grid_aligned"] is True

    absent_methane = sample_rows["Methane"]
    assert absent_methane["known_present"] is False
    assert absent_methane["hqi"] < 250.0

    traces = result.outputs["plots"]["library_compare_candidates"]
    assert traces["metadata"]["grid_aligned"] is True
    co2_candidate = next(
        item for item in traces["data"] if item["sample_index"] == 0 and item["library"] == "Carbon dioxide"
    )
    sample_trace = traces["samples"][co2_candidate["sample_trace_index"]]
    library_trace = traces["libraries"][co2_candidate["library_trace_index"]]
    assert all(
        abs(((value - 600.0) / 0.5) - round((value - 600.0) / 0.5)) < 1e-8
        for value in sample_trace["x"]
        if value is not None
    )
    assert all(
        abs(((value - 600.0) / 0.5) - round((value - 600.0) / 0.5)) < 1e-8
        for value in library_trace["x"]
        if value is not None
    )
    assert max(value for value in library_trace["y"] if value is not None) > 0
