from __future__ import annotations

from spectra_sherpa.app.services.dag.nodes.data import DataSourceNode


def test_data_source_primary_source_options_are_simplified() -> None:
    source_param = next(param for param in DataSourceNode.metadata.parameters if param.name == "source")

    assert source_param.options == ["spectrochempy", "sklearn", "eigenvector", "file"]
    assert "experiment" not in source_param.options
    assert "library" not in source_param.options
    assert "synthetic" not in source_param.options
