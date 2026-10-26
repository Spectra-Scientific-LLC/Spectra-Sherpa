"""Scientific membership and execution-boundary regressions from #155 review."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import SampleAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.lib.workflow_population import source_population_outputs
from spectra_sherpa.app.services.dag.executor import DAGExecutor
from spectra_sherpa.app.services.dag.executor_types import WorkflowEdge
from spectra_sherpa.app.services.dag.population_display import (
    DISPLAY_KEY,
    projection_within_budget,
    retain_population_display,
)


def _source():
    return SherpaDataset(
        np.arange(24.0).reshape(6, 4),
        sample_axis=SampleAxis(
            count=6,
            labels=[f"original {i}" for i in range(6)],
            classes=["A", "B", "A", "B", "A", "B"],
            sample_table={"sample_id": [f"id-{i}" for i in range(6)], "class": ["A", "B"] * 3},
        ),
        target=np.arange(6.0),
    )


def _loaded(data, indices=()):
    first = source_population_outputs(data, node_id="load")
    return source_population_outputs(
        data,
        node_id="load",
        exclusions={
            "source_digest": first["exclusions"]["source_digest"],
            "excluded_refs": [first["exclusions"]["rows"][i]["observation_ref"] for i in indices],
        },
    )


@pytest.mark.asyncio
async def test_preloaded_annotations_target_and_values_share_the_exact_active_subset():
    from spectra_sherpa.app.services.dag.nodes.data.file_load_node import FileLoadNode
    from spectra_sherpa.core.execution_runtime import ExecutionRuntime, ResolvedExperimentFile

    data = _source()
    axis = data.sample_axis
    axis.include_mask = [True, False, True, True, True, True]
    data.sample_axis = axis

    class Resolver:
        async def resolve_experiment_file(self, **kwargs):
            return ResolvedExperimentFile(
                path="/must-not-open.npy",
                original_file_path="raw/source.npy",
                created_datetime="2026-10-25T00:00:00+00:00",
                preloaded_dataset=data,
            )

    node = FileLoadNode("load", {"experiment_id": 1, "file_id": 2})
    node.bind_execution_runtime(ExecutionRuntime(dataset_source_resolver=Resolver()))
    first = await node.execute()
    node.parameters["workflow_exclusions"] = {
        "source_digest": first["exclusions"]["source_digest"],
        "excluded_refs": [first["exclusions"]["rows"][4]["observation_ref"]],
    }
    result = await node.execute()
    kept = [0, 2, 3, 5]
    np.testing.assert_array_equal(result["default"].X, data.X[kept])
    np.testing.assert_array_equal(np.asarray(result["target"]).reshape(-1), kept)
    assert result["sample_table"] == {
        key: [values[i] for i in kept] for key, values in data.sample_axis.sample_table.items()
    }
    assert result["sample_table"] == result["default"].sample_axis.sample_table
    assert data.n_samples == 6 and len(data.sample_axis.sample_table["class"]) == 6


@pytest.mark.asyncio
@pytest.mark.parametrize("workflow_excluded", [False, True])
async def test_only_workflow_exclusions_travel_beyond_the_source(workflow_excluded, monkeypatch):
    from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode

    data = _source()
    axis = data.sample_axis
    axis.include_mask = [False, True, True, True, True, True]
    data.sample_axis = axis
    loaded = _loaded(data, [4] if workflow_excluded else [])
    node = ScaleNode("scale", {"method": "mean_center"})
    result = await node.execute(loaded["default"])
    outputs = result.outputs if hasattr(result, "outputs") else result
    dispatch = AsyncMock(side_effect=node.project_population)
    executor = SimpleNamespace(
        nodes={"load": object(), "scale": node},
        results={"load": loaded, "scale": outputs},
        edges=[WorkflowEdge("load", "scale")],
        _run_population_projection=lambda n, o, i: dispatch(o, i),
    )
    await retain_population_display(executor, "load")
    assert loaded[DISPLAY_KEY]["outputs"]["default"].n_samples == 6  # Load Data still shows the source.
    if not workflow_excluded:
        monkeypatch.setattr(
            "spectra_sherpa.app.services.dag.population_display.projection_within_budget",
            lambda *args: pytest.fail("source-only exclusion must not walk or dispatch"),
        )
    await retain_population_display(executor, "scale")
    if workflow_excluded:
        dispatch.assert_awaited_once()
        display = outputs[DISPLAY_KEY]["outputs"]["default"]
        assert display.sample_axis.labels == [f"original {i}" for i in range(1, 6)]
        np.testing.assert_array_equal(display.sample_axis.include_mask, [True, True, True, False, True])
        assert outputs["default"].n_samples == 4
    else:
        dispatch.assert_not_awaited()
        assert DISPLAY_KEY not in outputs


@pytest.mark.asyncio
async def test_undeclared_projection_never_walks_dispatch_payload(monkeypatch):
    data = _source()
    axis = data.sample_axis
    axis.include_mask = [False, True, True, True, True, True]
    data.sample_axis = axis
    loaded = _loaded(data, [4])
    executor = SimpleNamespace(
        nodes={"load": object(), "sink": object()},
        results={"load": loaded, "sink": {}},
        edges=[WorkflowEdge("load", "sink")],
        _run_population_projection=AsyncMock(),
    )
    await retain_population_display(executor, "load")
    monkeypatch.setattr(SherpaDataset, "__getitem__", lambda *args: pytest.fail("undeclared projection must not slice"))
    monkeypatch.setattr(
        "spectra_sherpa.app.services.dag.population_display.projection_within_budget",
        lambda *args: pytest.fail("undeclared projection must not walk payload"),
    )
    await retain_population_display(executor, "sink")
    executor._run_population_projection.assert_not_awaited()
    assert executor.results["sink"][DISPLAY_KEY]["availability"] == "unavailable"


@pytest.mark.parametrize("named", [False, True])
def test_legacy_whole_dictionary_inputs_never_contain_display_companions(named):
    executor = DAGExecutor(process_pool=False)
    executor.nodes["sink"] = SimpleNamespace(uses_named_ports=lambda: named, metadata=None)
    executor.edges = [WorkflowEdge("screen", "sink")]
    retained = {
        "T2": [1, 2],
        "Q": [3, 4],
        "_public": "unchanged",
        DISPLAY_KEY: {"outputs": {"T2": [99]}},
        "__source_population": _source(),
    }
    executor.results["screen"] = retained
    positional, kwargs = executor._get_node_inputs("sink", validate_types=False)
    actual = kwargs["input_0"] if named else positional[0]
    assert actual == {"T2": [1, 2], "Q": [3, 4], "_public": "unchanged"}
    assert DISPLAY_KEY in retained and "__source_population" in retained


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,kwargs",
    [
        ("sample_class", {"pattern": "A", "match_mode": "equals"}),
        ("sample_label", {"pattern": "original [024]", "match_mode": "regex"}),
        ("sample_table", {"pattern": "A", "match_mode": "equals", "sample_table_column": "class"}),
    ],
)
async def test_branch_projection_keeps_only_excluded_observations_matching_the_branch(field, kwargs):
    from spectra_sherpa.app.services.dag.nodes.data.transforms import FilterSamplesNode

    loaded = _loaded(_source(), [4, 5])
    node = FilterSamplesNode("branch", {"field": field, **kwargs, "allow_empty": True})
    active = await node.execute(X=loaded["default"])
    display = await node.project_population(active, {"X": loaded["__source_population"]})
    assert "original 4" in display["default"].sample_axis.labels
    assert "original 5" not in display["default"].sample_axis.labels
    assert not bool(display["default"].sample_axis.include_mask[-1])


def test_dispatch_budget_is_bytes_not_an_object_count():
    data = SherpaDataset(
        np.ones((100_000, 2)),
        sample_axis=SampleAxis(
            count=100_000, labels=[f"sample-{i}" for i in range(100_000)], include_mask=[True] * 100_000
        ),
    )
    assert projection_within_budget({}, {"default": data})
    assert not projection_within_budget({}, {"default": data}, limit=1024)
    cyclic = {}
    cyclic["self"] = cyclic
    assert projection_within_budget(cyclic, {})
    assert not projection_within_budget({}, {"buffer": bytearray(4096)}, limit=1024)
    structured = np.empty(1, dtype=[("payload", object)])
    structured["payload"][0] = bytearray(4096)
    assert not projection_within_budget({}, {"structured": structured}, limit=1024)
    structured = np.empty(3, dtype=[("payload", object)])
    structured["payload"] = [None, None, bytearray(4096)]
    assert not projection_within_budget({}, {"structured": structured}, limit=1024)


@pytest.mark.asyncio
async def test_result_row_index_branch_never_guesses_an_excluded_position():
    from spectra_sherpa.app.services.dag.nodes.data.transforms import FilterSamplesNode

    loaded = _loaded(_source(), [4])
    node = FilterSamplesNode("branch", {"field": "sample_index", "pattern": "1-3"})
    with pytest.raises(ValueError, match="no retained branch result-row index"):
        await node.project_population({}, {"X": loaded["__source_population"]})
