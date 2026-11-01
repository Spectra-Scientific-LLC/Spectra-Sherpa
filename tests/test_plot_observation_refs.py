"""Actual output.plot projections keep navigation on their own observation axis."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SampleAxis, SherpaDataset, TargetContext
from spectra_sherpa.app.services.dag.nodes.output import PlotNode
from spectra_sherpa.sdk.plot_spec import CanonicalPlotSpec, CanonicalPlotSpecError


def dataset(n=3, *, target=None, title="Measured values"):
    ds = SherpaDataset(
        X=np.tile([1.0, 2.0], (n, 1)),
        sample_axis=SampleAxis(
            labels=["Repeated"] * n,
            workflow_observation_refs=[f"load:{'a' * 64}:{i}" for i in reversed(range(n))],
            include_mask=[i % 2 == 0 for i in range(n)],
        ),
        feature_axis=FeatureAxis(labels=["PC1", "PC2"]),
        title=title,
    )
    if target is not None:
        ds.target = np.asarray(target)
        ds.target_context = TargetContext(target_type="categorical", class_names=["A", "B"])
    return ds


def meta(ds, indices):
    return {
        "workflow_observation_refs": [ds.sample_axis.workflow_observation_refs[i] for i in indices],
        "workflow_included": [bool(ds.sample_axis.include_mask[i]) for i in indices],
    }


@pytest.mark.anyio
@pytest.mark.parametrize("plot_type", ["scores", "scatter"])
@pytest.mark.parametrize("target", [None, [1, 0, 1]])
async def test_actual_point_projection_uses_own_reordered_grouped_axis(plot_type, target):
    ds = dataset(target=target)
    before = copy.deepcopy(ds.to_dict())
    traces = (await PlotNode("p", {"plot_type": plot_type}).execute(ds))["visualization"]["data"]
    groups = [list(range(3))] if target is None else ([[0, 2], [1]] if plot_type == "scores" else [[1], [0, 2]])
    assert [t["meta"] for t in traces] == [meta(ds, group) for group in groups]
    assert [t["x"] for t in traces] == [[1.0] * len(group) for group in groups]
    assert ds.to_dict() == before


@pytest.mark.anyio
async def test_actual_continuous_score_colors_keep_navigation():
    ds = dataset()
    ds.target = np.array([0.2, 0.4, 0.9])
    trace = (await PlotNode("p", {"plot_type": "scores"}).execute(ds))["visualization"]["data"][0]
    assert trace["meta"] == meta(ds, range(3))
    assert trace["marker"]["color"] == [0.2, 0.4, 0.9]


@pytest.mark.anyio
async def test_subsampled_spectra_keep_one_exact_row_identity_for_the_whole_trace():
    ds = dataset(53)
    traces = (await PlotNode("p", {}).execute(ds))["visualization"]["data"]
    rows = np.linspace(0, 52, 50, dtype=int)
    assert len(traces) == 50
    for row, trace in zip(rows, traces):
        assert trace["meta"] == {
            "workflow_observation_ref": ds.sample_axis.workflow_observation_refs[row],
            "workflow_included": bool(ds.sample_axis.include_mask[row]),
        }
        assert trace["y"] == [1.0, 2.0]


@pytest.mark.anyio
async def test_profiles_and_biplot_only_identify_observation_points():
    ds = dataset(title="Concentration profiles")
    traces = (await PlotNode("p", {}).execute(ds))["visualization"]["data"]
    assert len(traces) == 2
    assert all(t["meta"] == meta(ds, range(3)) for t in traces)
    traces = (
        await PlotNode("p", {"plot_type": "biplot"}).execute({"scores": ds, "loadings": [[0.1, 0.2], [0.3, 0.4]]})
    )["visualization"]["data"]
    assert traces[0]["meta"] == meta(ds, range(3))
    assert len(traces) == 3
    assert all("meta" not in t for t in traces[1:])


@pytest.mark.anyio
@pytest.mark.parametrize("plot_type", ["spectra", "scores", "scatter", "biplot"])
async def test_labels_and_neighboring_population_never_create_navigation(plot_type):
    ds = dataset()
    ds.sample_axis = SampleAxis(labels=["Repeated"] * 3)
    payload = {"scores": ds, "loadings": dataset()} if plot_type == "biplot" else ds
    traces = (await PlotNode("p", {"plot_type": plot_type}).execute(payload))["visualization"]["data"]
    assert all("meta" not in t for t in traces)


@pytest.mark.anyio
@pytest.mark.parametrize("plot_type", ["spectra", "scores", "scatter", "biplot"])
@pytest.mark.parametrize("bad_field", ["workflow_observation_refs", "include_mask"])
async def test_misaligned_optional_navigation_does_not_discard_computed_plot(plot_type, bad_field):
    ds = dataset()
    control = dataset()
    control_axis = control.sample_axis
    control_axis.workflow_observation_refs = None
    control.sample_axis = control_axis
    # Simulate a stale optional axis left by an upstream projection. The
    # numerical matrix and its scientifically meaningful coordinates stay valid.
    axis = ds._axes[ds._SAMPLE_DIM]
    object.__setattr__(axis, bad_field, getattr(axis, bad_field)[:1])
    assert len(getattr(ds.sample_axis, bad_field)) == 1
    payload = {"scores": ds, "loadings": [[0.1, 0.2], [0.3, 0.4]]} if plot_type == "biplot" else ds
    control_payload = {"scores": control, "loadings": [[0.1, 0.2], [0.3, 0.4]]} if plot_type == "biplot" else control
    before = ds.X.copy()
    result = await PlotNode("p", {"plot_type": plot_type}).execute(payload)
    expected = await PlotNode("p", {"plot_type": plot_type}).execute(control_payload)
    assert result == expected
    assert all("meta" not in trace for trace in result["visualization"]["data"])
    np.testing.assert_array_equal(ds.X, before)


@pytest.mark.anyio
async def test_aggregate_spectral_comparison_has_no_observation_navigation():
    from spectra_sherpa.app.lib.sherpa_dataset import SpectralAxis

    ds = dataset()
    ds.feature_axis = SpectralAxis(values=[1000.0, 1100.0], units="cm-1")
    other = ds.copy()
    other.title = "Other cohort"
    traces = (await PlotNode("p", {}).execute([ds, other]))["visualization"]["data"]
    assert all("meta" not in t for t in traces)


@pytest.mark.parametrize(
    "bad",
    [
        {"sample_ids": ["label"]},
        {"workflow_observation_refs": ["ref"], "workflow_included": [1]},
        {"workflow_observation_refs": ["ref"], "workflow_included": []},
        {"workflow_observation_refs": [""], "workflow_included": [True]},
        {"workflow_observation_refs": ["ref", "other"], "workflow_included": [True, True]},
    ],
)
def test_plot_trace_navigation_is_closed_and_point_aligned(bad):
    with pytest.raises(CanonicalPlotSpecError):
        CanonicalPlotSpec.create(
            plot_type="scatter",
            data=[
                {
                    "type": "scatter",
                    "x": [1],
                    "y": [2],
                    "meta": bad,
                }
            ],
            layout={},
        )


@pytest.mark.anyio
async def test_frontend_quick_plot_fixture_matches_actual_producer():
    ds = dataset(target=[0, 1, 0])
    axis = ds.sample_axis
    axis.include_mask = np.ones(3, dtype=bool)
    ds.sample_axis = axis
    result = await PlotNode("p", {"plot_type": "scores"}).execute(ds)
    fixture = Path(__file__).resolve().parents[1] / "frontend/src/test/fixtures/observation-score-plot.json"
    assert result["visualization"] == json.loads(fixture.read_text())


@pytest.mark.anyio
async def test_real_pca_to_output_plot_does_not_invent_excluded_coordinates():
    from spectra_sherpa.app.lib.workflow_population import source_population_outputs
    from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import PCANode

    ds = SherpaDataset(np.random.default_rng(52).normal(size=(12, 4)), sample_axis=SampleAxis(labels=["Repeated"] * 12))
    initial = source_population_outputs(ds, node_id="load")["exclusions"]
    excluded = initial["rows"][4]["observation_ref"]
    loaded = source_population_outputs(
        ds,
        node_id="load",
        exclusions={
            "source_digest": initial["source_digest"],
            "excluded_refs": [excluded],
        },
    )
    fitted = await PCANode("pca", {"n_components": "2", "standardized": True, "scaled": False}).execute(
        loaded["default"]
    )
    loadings = (await PlotNode("loadings", {"plot_type": "loadings"}).execute(fitted.outputs["loadings"]))[
        "visualization"
    ]["data"]
    assert all("meta" not in trace for trace in loadings)
    scores = fitted.outputs["scores"]
    trace = (await PlotNode("plot", {"plot_type": "scores"}).execute(scores))["visualization"]["data"][0]
    assert len(trace["x"]) == len(trace["meta"]["workflow_observation_refs"]) == 11
    assert excluded not in trace["meta"]["workflow_observation_refs"]
    assert trace["meta"]["workflow_observation_refs"] == scores.sample_axis.workflow_observation_refs
    np.testing.assert_array_equal(trace["x"], scores.X[:, 0])
    np.testing.assert_array_equal(trace["y"], scores.X[:, 1])


@pytest.mark.anyio
async def test_unspecified_inclusion_defaults_to_active_without_changing_rows():
    ds = dataset()
    axis = ds.sample_axis
    axis.include_mask = None
    ds.sample_axis = axis
    trace = (await PlotNode("p", {"plot_type": "scores"}).execute(ds))["visualization"]["data"][0]
    assert trace["meta"]["workflow_included"] == [True, True, True]
    assert trace["meta"]["workflow_observation_refs"] == ds.sample_axis.workflow_observation_refs


@pytest.mark.anyio
async def test_separate_scores_projects_full_pca_display_without_changing_active_result(monkeypatch):
    from types import SimpleNamespace

    from spectra_sherpa.app.lib.workflow_population import source_population_outputs
    from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge
    from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import PCANode
    from spectra_sherpa.app.services.dag.population_display import DISPLAY_KEY, retain_population_display

    ds = SherpaDataset(
        np.random.default_rng(53).normal(size=(178, 4)), sample_axis=SampleAxis(labels=["Repeated"] * 178)
    )
    initial = source_population_outputs(ds, node_id="load")["exclusions"]
    excluded = initial["rows"][17]["observation_ref"]
    loaded = source_population_outputs(
        ds,
        node_id="load",
        exclusions={
            "source_digest": initial["source_digest"],
            "excluded_refs": [excluded],
        },
    )
    pca = PCANode("pca", {"n_components": "2", "standardized": True, "scaled": False})
    fitted = await pca.execute(loaded["default"])
    plot = PlotNode("plot", {"plot_type": "scores"})
    plotted = await plot.execute(fitted.outputs["scores"])
    active_plot = copy.deepcopy(plotted)
    active_scores = fitted.outputs["scores"].X.copy()
    active_state = copy.deepcopy(fitted.outputs["fitted_state"])

    async def project(node, outputs, inputs):
        return await node.project_population(outputs, inputs)

    executor = SimpleNamespace(
        nodes={"load": object(), "pca": pca, "plot": plot},
        _run_population_projection=project,
        results={"load": loaded, "pca": fitted.outputs, "plot": plotted},
        edges=[WorkflowEdge("load", "pca"), WorkflowEdge("pca", "plot", "scores")],
    )
    await retain_population_display(executor, "load")
    await retain_population_display(executor, "pca")
    full = executor.results["pca"][DISPLAY_KEY]["outputs"]["scores"]
    before_full = copy.deepcopy(full.to_dict())

    # Output Plot may only render the already projected coordinates. Even PCA
    # application is forbidden after this point; it must not refit or reevaluate.
    def forbidden(*args, **kwargs):
        pytest.fail("Plot projection attempted a model operation")

    monkeypatch.setattr(pca, "execute", forbidden)
    monkeypatch.setattr(pca, "apply_fitted_state", forbidden)
    await retain_population_display(executor, "plot")
    companion = plotted[DISPLAY_KEY]
    assert companion["availability"] == "available", companion
    trace = companion["outputs"]["visualization"]["data"][0]
    assert len(trace["x"]) == 178
    assert trace["meta"]["workflow_observation_refs"] == full.sample_axis.workflow_observation_refs
    assert trace["meta"]["workflow_included"].count(False) == 1
    assert trace["meta"]["workflow_included"][trace["meta"]["workflow_observation_refs"].index(excluded)] is False
    np.testing.assert_array_equal(trace["x"], full.X[:, 0])
    np.testing.assert_array_equal(trace["y"], full.X[:, 1])
    assert {k: v for k, v in plotted.items() if k != DISPLAY_KEY} == active_plot
    assert len(active_plot["visualization"]["data"][0]["x"]) == 177
    np.testing.assert_array_equal(fitted.outputs["scores"].X, active_scores)
    np.testing.assert_equal(fitted.outputs["fitted_state"], active_state)
    assert full.to_dict() == before_full


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case", ["multi_cohort", "two_ports", "unknown_port", "labels_only", "foreign_refs", "aggregate"]
)
async def test_plot_population_projection_refuses_ambiguous_or_unaligned_inputs(case):
    full = dataset()
    plot = PlotNode("p", {"plot_type": "scores"})
    active = await plot.execute(full[[True, False, True]])
    inputs = {"default": full}
    if case == "multi_cohort":
        inputs = {"default": [full, full.copy()]}
    elif case == "two_ports":
        inputs = {"default": full, "input_data": full}
    elif case == "unknown_port":
        inputs = {"other": full}
    elif case == "labels_only":
        full.sample_axis = SampleAxis(labels=["Repeated"] * 3)
    elif case == "foreign_refs":
        axis = full.sample_axis
        axis.workflow_observation_refs = [f"other:{i}" for i in range(3)]
        full.sample_axis = axis
    elif case == "aggregate":
        active = {"visualization": {"data": [{"type": "scatter", "x": [1, 2], "y": [3, 4]}]}}
    before = copy.deepcopy(active)
    with pytest.raises(ValueError, match="Plot population projection"):
        await plot.project_population(active, inputs)
    assert active == before


@pytest.mark.anyio
async def test_full_spectral_plot_retains_exactly_under_default_output_limit(tmp_path, monkeypatch):
    from dataclasses import replace

    from spectra_sherpa.app.lib.sherpa_dataset import SpectralAxis
    from spectra_sherpa.app.schemas.run_evidence import RunEvidence
    from spectra_sherpa.app.services import run_output_retention as retention

    monkeypatch.setattr(retention, "settings", replace(retention.settings, data_dir=tmp_path))
    ds = SherpaDataset(
        np.random.default_rng(54).normal(size=(50, 4096)),
        sample_axis=SampleAxis(
            labels=["Repeated"] * 50,
            workflow_observation_refs=[f"load:{'a' * 64}:{i}" for i in range(50)],
            include_mask=[i % 2 == 0 for i in range(50)],
        ),
        feature_axis=SpectralAxis(values=np.linspace(4000, 400, 4096), units="cm-1"),
    )
    before = ds.scientific_digest
    result = await PlotNode("p", {}).execute(ds)
    evidence = RunEvidence.model_validate(retention.retain_run_outputs(1, {"p": result}, {}))
    item = evidence.outputs["p"]["visualization"]
    assert item.state == "exact", item
    restored = retention.read_output(1, item)
    assert restored == result["visualization"]
    assert len(restored["data"]) == 50
    for i, trace in enumerate(restored["data"]):
        assert trace["meta"] == {
            "workflow_observation_ref": ds.sample_axis.workflow_observation_refs[i],
            "workflow_included": i % 2 == 0,
        }
        np.testing.assert_array_equal(trace["y"], ds.X[i])
        np.testing.assert_array_equal(trace["x"], ds.feature_axis.values)
    assert ds.scientific_digest == before


@pytest.mark.parametrize(
    "bad",
    [
        {"workflow_observation_ref": "ref", "workflow_observation_refs": ["ref"], "workflow_included": True},
        {"workflow_observation_ref": "ref", "workflow_included": [True]},
        {"workflow_observation_ref": "", "workflow_included": True},
        {"workflow_observation_ref": "ref", "workflow_included": 1},
    ],
)
def test_compact_plot_metadata_refuses_ambiguous_or_invalid_navigation(bad):
    with pytest.raises(CanonicalPlotSpecError):
        CanonicalPlotSpec.create(
            plot_type="spectra",
            data=[
                {
                    "type": "scatter",
                    "x": [1, 2],
                    "y": [3, 4],
                    "meta": bad,
                }
            ],
            layout={},
        )


@pytest.mark.anyio
async def test_frontend_compact_spectrum_fixture_matches_actual_producer():
    from spectra_sherpa.app.lib.sherpa_dataset import SpectralAxis

    ds = dataset()
    ds.feature_axis = SpectralAxis(values=[4000.0, 400.0], units="cm-1")
    result = await PlotNode("p", {}).execute(ds)
    fixture = Path(__file__).resolve().parents[1] / "frontend/src/test/fixtures/observation-spectrum-plot.json"
    assert result["visualization"] == json.loads(fixture.read_text())
    active = await PlotNode("p", {}).execute(ds[[True, False, True]])
    projected = await PlotNode("p", {}).project_population(active, {"default": ds})
    assert projected == result
