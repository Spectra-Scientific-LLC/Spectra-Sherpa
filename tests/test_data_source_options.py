from __future__ import annotations

from spectra_sherpa.app.services.dag.nodes.data.file_load_node import FileLoadNode


def test_file_load_requires_one_exact_experiment_file() -> None:
    parameters = {parameter.name: parameter for parameter in FileLoadNode.metadata.parameters}

    assert parameters["experiment_id"].required is True
    assert parameters["file_id"].required is True
    assert "source" not in parameters
