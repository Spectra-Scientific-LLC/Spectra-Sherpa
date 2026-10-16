"""Data-role defaults must survive full starter execution on public Wine data."""

from copy import deepcopy

import numpy as np
import pytest
from sklearn.datasets import load_wine

from spectra_sherpa.app.api.v1.routes.workflow_templates import _adapt_starter_scaling_to_bound_role
from spectra_sherpa.app.lib.dataset_compatibility import analysis_profile_from_dataset
from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SampleAxis, SherpaDataset, TargetContext
from spectra_sherpa.app.models.workflow_template import WorkflowTemplate
from tests.test_accessible_template_execution_matrix import _executor, _spectral_fixture, _template_entries


@pytest.mark.parametrize("slug", ["classification_plsda", "knn_classification"])
@pytest.mark.asyncio
async def test_wine_starter_admits_autoscaling_and_preserves_predictions(tmp_path, slug):
    wine = load_wine()
    dataset = SherpaDataset(
        X=wine.data,
        data_role="X_features",
        feature_axis=FeatureAxis(values=np.arange(wine.data.shape[1]), labels=list(wine.feature_names)),
        sample_axis=SampleAxis(labels=[f"wine-{i}" for i in range(len(wine.target))]),
        target=wine.target,
        target_context=TargetContext(target_type="categorical", target_name="class", target_names=["class"]),
    )
    entry = deepcopy(next(item for item in _template_entries() if item["slug"] == slug))
    graph = entry["template_data"]
    template = WorkflowTemplate(**entry)
    profile = analysis_profile_from_dataset(dataset)
    assert profile["primary_role"] == "X_features"
    _adapt_starter_scaling_to_bound_role(
        template=template,
        source_node_id="data_1",
        analysis_profile=profile,
        nodes=graph["nodes"],
        edges=graph["edges"],
    )
    model = next(node for node in graph["nodes"] if node["node_id"] == "model_1")
    assert model["parameters"]["scale"] is True
    executor = _executor(entry, tmp_path / "adapted")
    executor.inject_result("data_1", {"default": dataset, "target": wine.target})
    actual = await executor.execute()
    evaluation = actual["eval_1"]["default"]
    assert evaluation["n_samples"] == 44
    assert evaluation["accuracy"] == pytest.approx(1.0 if slug == "classification_plsda" else 41 / 44)
    assert evaluation["population_authority"]["role"] == "held_out_test"
    comparison = actual["eval_1"]["comparison"]
    assert comparison["metadata"]["sample_identity"] == "provided_labels"
    assert [row["sample"] for row in comparison["data"]] == list(actual["partition_1"]["X_test"].sample_axis.labels)

    spectra, _ = _spectral_fixture(slug)
    spectral_profile = analysis_profile_from_dataset(spectra)
    assert spectral_profile["primary_role"] == "X_spectra"
    _adapt_starter_scaling_to_bound_role(
        template=template,
        source_node_id="data_1",
        analysis_profile=spectral_profile,
        nodes=graph["nodes"],
        edges=graph["edges"],
    )
    assert model["parameters"]["scale"] is False
