"""Large-shape refusals happen before scientific results expand into JSON."""

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.presentation_limits import require_bounded_presentation


@pytest.mark.parametrize("shape", [(1, 500001), (500001, 1), (100, 640000)])
def test_table_rejects_large_axes_before_transpose(shape):
    from spectra_sherpa.app.services.dag.nodes.output.data_table_node import DataTableNode

    values = np.broadcast_to(np.zeros((1, 1)), shape)
    node = DataTableNode("table", {"transpose": True})
    with pytest.raises(ValueError, match="display limit"):
        node._build(values)


def test_strings_and_records_cannot_bypass_numeric_limit():
    for payload in ({"description": "x" * (2 * 1024 * 1024 + 1)}, [{"value": 1}] * 100001):
        with pytest.raises(ValueError, match="display limit"):
            require_bounded_presentation(payload, surface="Test")


async def test_model_comparison_refuses_before_any_model_read(monkeypatch):
    from spectra_sherpa.app.services import model_application

    calls = []
    monkeypatch.setattr(model_application, "get_model_store", lambda: calls.append(True))
    with pytest.raises(ValueError, match="display limit"):
        await model_application.compare_models_on_dataset(["a", "b"], SherpaDataset(np.zeros((10001, 10))))
    assert not calls


async def test_peak_detection_refuses_before_scipy(monkeypatch):
    from spectra_sherpa.app.services.dag.nodes.modeling import peak_finding_nodes

    calls = []
    import scipy.signal

    monkeypatch.setattr(scipy.signal, "find_peaks", lambda *a, **kw: calls.append(True))
    node = peak_finding_nodes.PeakFindingNode("peaks", {"prominence": 0.5})
    with pytest.raises(ValueError, match="display limit"):
        await node.execute(SherpaDataset(np.zeros((1001, 1000))))
    assert not calls


async def test_peak_detection_refuses_dense_detections_before_consensus(monkeypatch):
    from spectra_sherpa.app.services.dag.nodes.modeling.peak_finding_nodes import PeakFindingNode

    node = PeakFindingNode("peaks", {"prominence": 0.5, "distance": None})
    calls = []
    monkeypatch.setattr(node, "_bin_consensus_peaks", lambda *a, **kw: calls.append(True))
    values = np.tile([0.0, 1.0], (11, 1000))
    with pytest.raises(ValueError, match="10,000 detections"):
        await node.execute(SherpaDataset(values))
    assert calls == []


@pytest.mark.parametrize("payload", [np.broadcast_to(0.0, (1, 500001)), {"label": "x" * (2 * 1024 * 1024 + 1)}])
def test_plot_refuses_before_building_traces(monkeypatch, payload):
    from spectra_sherpa.app.services.dag.nodes.output.plot_node import PlotNode, build_plot_result

    calls = []
    monkeypatch.setattr(PlotNode, "_build", lambda *a: calls.append(True))
    with pytest.raises(ValueError, match="Plot exceeds its display limit"):
        build_plot_result(payload)
    assert calls == []


def test_existing_large_spectral_plot_keeps_disclosed_projection():
    from spectra_sherpa.app.services.dag.nodes.output.plot_node import build_plot_result

    result = build_plot_result(SherpaDataset(np.zeros((200, 1600))))["visualization"]
    assert result["metadata"]["n_samples"] == 200
    assert result["metadata"]["shown_traces"] == len(result["data"]) == 50


def test_outlier_diagnostics_refuse_before_numeric_materialization(monkeypatch):
    from spectra_sherpa.app.services.dag.nodes import diagnostics

    calls = []
    monkeypatch.setattr(diagnostics, "to_numpy_2d", lambda *a, **kw: calls.append(True))
    with pytest.raises(ValueError, match="PCA outlier diagnostics exceeds its display limit"):
        diagnostics._outlier_dispatch({"scores": np.broadcast_to(0.0, (1, 500001))})
    assert calls == []
