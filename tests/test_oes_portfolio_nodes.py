import hashlib
from importlib.resources import files
from types import SimpleNamespace

import h5py
import numpy as np
import pytest

from spectra_sherpa.app.services.dag.nodes.oes_portfolios import (
    PeakCSVNode,
    PortfolioAverageNode,
    PortfolioLoadNode,
    WidePeakTableNode,
)
from spectra_sherpa.app.services.time_series_portfolios import dictionary_hash
from spectra_sherpa.core.execution_runtime import ExecutionRuntime
from spectra_sherpa.core.time_series_portfolio import AcquisitionInterval, StepPartition, TimeSeriesPortfolio
from tests.test_bosch_netcdf import files as native_files


@pytest.mark.parametrize("statistic", ["mean", "median"])
@pytest.mark.asyncio
async def test_streamed_three_modes_equal_acquisition_weights_and_independent_wafers(tmp_path, statistic):
    path, _, codes, _, _ = native_files(tmp_path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    intervals = (
        AcquisitionInterval(first=1, last=2, phase="etch", cycle=1),
        AcquisitionInterval(first=3, last=3, phase="passivation", cycle=1),
        AcquisitionInterval(first=4, last=4, phase="etch", cycle=2),
    )
    parts = tuple(
        StepPartition(
            experiment_id=1,
            file_id=2,
            process_file_id=3,
            source_sha256=digest,
            process_sha256=digest,
            oes_dictionary_sha256=dictionary_hash("Dictionary_OES.nc"),
            process_dictionary_sha256=dictionary_hash("Dictionary_process.nc"),
            segmentation_sha256="a" * 64,
            day="2024-08-05",
            wafer=w,
            asset_id=w,
            step_id="production",
            recipe="BOSCH",
            intervals=intervals,
        )
        for w in ["Wafer_01", "Wafer_02"]
    )
    receipt = TimeSeriesPortfolio(project_id=1, partitions=parts)

    class Resolver:
        async def resolve_time_series_portfolio(self, **kw):
            return receipt.model_dump(mode="json")

        async def resolve_experiment_file(self, **kw):
            return SimpleNamespace(path=str(path))

    runtime = ExecutionRuntime(dataset_source_resolver=Resolver())
    pin = dict(project_id=1, portfolio_id=1, selection_sha256=receipt.sha256())
    load = PortfolioLoadNode("load", pin)
    load.bind_execution_runtime(runtime)
    descriptor = (await load.execute()).outputs["default"]
    with h5py.File(str(files("spectra_sherpa").joinpath("data", "bosch_netcdf", "Dictionary_OES.nc"))) as f:
        expected = f["data"][:][codes]
    for mode, count in [("step", 2), ("phase_across_cycles", 4), ("cycle_phase", 6)]:
        node = PortfolioAverageNode("average", pin | dict(mode=mode, statistic=statistic))
        node.bind_execution_runtime(runtime)
        result = (await node.execute(default=descriptor)).outputs["default"]
        assert result.shape == (count, 3)
        assert len(set(result.sample_axis.sample_table["sample_id"])) == count
        if mode == "step":
            np.testing.assert_allclose(
                result.X[0], (np.median(expected, axis=0) if statistic == "median" else expected.mean(axis=0))
            )
        if mode == "phase_across_cycles":
            np.testing.assert_allclose(
                result.X[0],
                (np.median(expected[[0, 1, 3]], axis=0) if statistic == "median" else expected[[0, 1, 3]].mean(axis=0)),
            )
    # Exercise the same canonical graph as the GUI, including retained export bytes.
    import csv
    import io

    from spectra_sherpa.app.services.dag.executor import DAGExecutor, WorkflowEdge, WorkflowNode

    for mode, count in [("step", 2), ("phase_across_cycles", 4), ("cycle_phase", 6)]:
        graph = DAGExecutor(runtime=runtime)
        nodes = [
            ("load", "data.portfolio_load", pin),
            ("average", "preprocess.portfolio_average", pin | {"mode": mode, "statistic": statistic}),
            ("smooth", "preprocess.smooth", {"method": "savitzky_golay", "size": 3, "order": 1}),
            ("normalize", "preprocess.normalize", {}),
            ("peaks", "analysis.partitioned_peaks", {"reference_positions": ["500"], "matching_tolerance": 1}),
            ("wide", "data.wide_peak_table", {"reference_positions": ["500"], "tolerance": 1}),
            ("csv", "output.peak_csv", {}),
        ]
        for node_id, node_type, parameters in nodes:
            graph.add_node(WorkflowNode(node_id, node_type, parameters))
        for upstream, downstream in zip(nodes, nodes[1:]):
            graph.add_edge(
                WorkflowEdge(
                    upstream[0], downstream[0], from_output="per_spectrum" if upstream[0] == "peaks" else "default"
                )
            )
        outputs = await graph.execute()
        artifact = outputs["csv"]["artifact"]
        assert artifact["shape"] == [1, count]
        rows = list(csv.reader(io.StringIO(artifact["content"])))
        assert len(rows) == 2
        assert len(rows[0]) == count + 1
        assert "Wafer_01" in rows[0][1]
        assert "Wafer_02" in rows[0][-1]

    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="Source bytes differ"):
        await node.execute(default=descriptor)


@pytest.mark.asyncio
async def test_wide_csv_keeps_missing_distinct_from_zero_and_rejects_ambiguous_matches():
    from spectra_sherpa.app.lib.axes import FeatureAxis, SampleAxis
    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

    source = SherpaDataset(
        X=np.array([[1, 0, 1, 0], [np.nan, np.nan, 1, 2]]),
        feature_axis=FeatureAxis(
            labels=["peak_position_1", "magnitude_at_peak_1", "group_position_1", "magnitude_at_group_position_1"]
        ),
        sample_axis=SampleAxis(
            sample_table={
                "sample_id": ["a", "b"],
                "date": ["day1", "day2"],
                "wafer": ["01", "02"],
                "step": ["production", "production"],
            }
        ),
        data_role="X_features",
    )
    source.meta["peak_groups"] = [{"index": 1, "guide_position": 1, "consensus_peak_id": "p1"}]
    wide = (
        await WidePeakTableNode("wide", {"reference_positions": ["1"], "tolerance": 0.1}).execute(default=[source])
    ).outputs["default"]
    artifact = (await PeakCSVNode("csv").execute(default=wide)).outputs["artifact"]
    import csv
    import io

    rows = list(csv.reader(io.StringIO(artifact["content"])))
    assert len(rows[0]) == 3
    assert rows[1] == ["peak@1", "0", ""]
    with pytest.raises(ValueError, match="Duplicate observation"):
        await WidePeakTableNode("wide", {"reference_positions": ["1"]}).execute(default=[source, source])
