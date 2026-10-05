"""Closed plot-spec and lazy renderer proofs."""

from __future__ import annotations

import asyncio
import importlib
import subprocess
import sys

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401 - register built-ins
from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, SpectralAxis
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.sdk.plot_spec import (
    CANONICAL_PLOT_SPEC_VERSION,
    CanonicalPlotSpec,
    CanonicalPlotSpecError,
)


@pytest.mark.parametrize("visible", [True, False, "legendonly"])
def test_plot_spec_preserves_supported_visibility_and_theme(visible) -> None:
    layout = {"paper_bgcolor": "#1e293b", "plot_bgcolor": "#0f172a", "font": {"color": "#fff"}}
    spec = CanonicalPlotSpec.create(
        plot_type="scatter",
        data=[
            {"type": "scatter", "x": [1], "y": [2], "visible": visible},
        ],
        layout=layout,
    )
    assert CanonicalPlotSpec.from_dict(spec.as_dict()).data[0]["visible"] == visible
    assert spec.layout == layout


@pytest.mark.parametrize("visible", [None, 0, 1, "true", [], {}])
def test_plot_spec_rejects_invalid_visibility(visible) -> None:
    with pytest.raises(CanonicalPlotSpecError, match="visible must be"):
        CanonicalPlotSpec.create(
            plot_type="scatter",
            data=[
                {"type": "scatter", "x": [1], "y": [2], "visible": visible},
            ],
            layout={},
        )


def _dataset() -> SherpaDataset:
    return SherpaDataset(
        X=np.arange(24, dtype=np.float64).reshape(3, 8),
        feature_axis=SpectralAxis(
            values=np.linspace(4000.0, 400.0, 8),
            units="cm-1",
            title="Wavenumber",
        ),
        sample_axis=SampleAxis(labels=["A", "B", "C"]),
        title="Plot contract fixture",
    )


def test_plot_node_emits_the_current_closed_specification() -> None:
    node = node_registry.create_node("output.plot", "plot", {"plot_type": "spectra"})
    payload = asyncio.run(node.execute(input_data=_dataset()))["visualization"]

    assert payload["schema_version"] == CANONICAL_PLOT_SPEC_VERSION
    assert CanonicalPlotSpec.from_dict(payload).as_dict() == payload
    assert len(payload["data"]) == 3
    assert payload["layout"]["xaxis"]["autorange"] == "reversed"


def test_contour_node_emits_the_same_specification_authority() -> None:
    node = node_registry.create_node("output.contour", "contour", {"plot_type": "heatmap"})
    payload = asyncio.run(node.execute(input_data=_dataset()))["visualization"]

    assert payload["schema_version"] == CANONICAL_PLOT_SPEC_VERSION
    assert CanonicalPlotSpec.from_dict(payload).plot_type == "heatmap"


@pytest.mark.parametrize(
    "mutation",
    [
        {"unknown": True},
        {"schema_version": "spectra-canonical-plot-spec/0"},
    ],
)
def test_plot_specification_fails_closed_on_envelope_drift(mutation: dict[str, object]) -> None:
    payload = {
        "schema_version": CANONICAL_PLOT_SPEC_VERSION,
        "plot_type": "scatter",
        "data": [{"type": "scatter", "x": [1.0], "y": [2.0]}],
        "layout": {},
        "metadata": {},
    }
    payload.update(mutation)
    with pytest.raises(CanonicalPlotSpecError):
        CanonicalPlotSpec.from_dict(payload)


def test_plot_specification_rejects_trace_drift_and_nonfinite_data() -> None:
    with pytest.raises(CanonicalPlotSpecError, match="unsupported fields"):
        CanonicalPlotSpec.create(
            plot_type="scatter",
            data=[{"type": "scatter", "x": [1.0], "y": [2.0], "renderer_callback": "unsafe"}],
            layout={},
        )
    with pytest.raises(CanonicalPlotSpecError, match="non-finite"):
        CanonicalPlotSpec.create(
            plot_type="scatter",
            data=[{"type": "scatter", "x": [1.0], "y": [float("nan")]}],
            layout={},
        )


def test_renderer_is_lazy_and_returns_a_noncanonical_figure(monkeypatch: pytest.MonkeyPatch) -> None:
    isolated = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import spectra_sherpa.sdk.plot; "
                "assert not any(name == 'plotly' or name.startswith('plotly.') for name in sys.modules)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert isolated.returncode == 0, isolated.stderr

    sys.modules.pop("spectra_sherpa.sdk.plot", None)
    plot = importlib.import_module("spectra_sherpa.sdk.plot")

    shown: list[str | None] = []
    import plotly.graph_objects as go

    monkeypatch.setattr(go.Figure, "show", lambda self, renderer=None: shown.append(renderer))
    spec = CanonicalPlotSpec.create(
        plot_type="scatter",
        data=[{"type": "scatter", "mode": "lines", "x": [1.0, 2.0], "y": [3.0, 4.0]}],
        layout={"title": "Example"},
    )
    figure = plot.show(spec, renderer="json")

    assert shown == ["json"]
    assert len(figure.data) == 1
    assert "schema_version" not in figure.to_plotly_json()
