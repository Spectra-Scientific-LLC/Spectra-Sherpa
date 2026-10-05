"""Deterministic executed values shared by retention and release qualification."""

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import FeatureAxis, SampleAxis, SherpaDataset, TargetContext
from spectra_sherpa.app.services.dag.nodes.classification.plsda_nodes import PLSDANode
from spectra_sherpa.app.services.dag.nodes.modeling.clustering_nodes import HCANode
from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import FittedPLSV2Node
from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import PCANode
from spectra_sherpa.app.services.dag.nodes.preprocessing.scale_node import ScaleNode


def reference_matrix(samples=120, features=700):
    rng = np.random.default_rng(20260910)
    latent = rng.normal(size=(samples, 4))
    matrix = latent @ rng.normal(size=(4, features)) + rng.normal(scale=0.02, size=(samples, features))
    return (
        SherpaDataset(
            X=matrix,
            sample_axis=SampleAxis(labels=[f"sample-{i:04d}" for i in range(samples)]),
            feature_axis=FeatureAxis(
                values=np.linspace(600, 1800, features),
                units="cm-1",
                labels=[f"band-{i:04d}" for i in range(features)],
            ),
            data_role="X_spectra",
        ),
        latent[:, 0] + 0.3 * latent[:, 1],
    )


async def executed_cases():
    dataset, target = reference_matrix()
    pca = await PCANode("pca", {"n_components": "3", "standardized": True, "scaled": False}).execute(input_data=dataset)
    pls_node = FittedPLSV2Node("pls", {"n_components": 3, "scale": True})
    pls = await pls_node.execute(input_data=dataset, y=target)
    classified = dataset.copy()
    labels = np.where(target > 0, "positive", "negative")
    classified.target = labels
    classified.target_context = TargetContext(target_type="categorical", target_names=["class"])
    classification = await PLSDANode("classify", {"n_components": 3, "scale": True}).execute(X=classified, y=labels)
    hca = await HCANode("hca", {"n_clusters": 3, "linkage": "ward", "metric": "euclidean"}).execute(input_data=dataset)
    transformed = await ScaleNode("center", {"method": "mean_center"}).execute(default=dataset)
    state = pls_node.fit_fitted_state(dataset, target)
    predicted = pls_node.apply_fitted_state(dataset, state)
    return {
        "pca": pca.outputs,
        "pls": pls.outputs,
        "classification": classification.outputs,
        "hca": hca.outputs,
        "transformed_data": transformed.outputs,
        "model_application": {"predictions": predicted, "sample_labels": dataset.sample_axis.labels},
    }
