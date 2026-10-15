from __future__ import annotations

import numpy as np
import pytest

from spectra_sherpa.app.lib.axes import FeatureAxis
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.nodes.modeling.pca_nodes import execute_pca_node


@pytest.mark.parametrize("standardized,scaled", [(False, False), (True, False), (False, True)])
def test_pca_variable_correlations_match_pearson_for_every_scaling_mode(
    standardized: bool,
    scaled: bool,
) -> None:
    observations = np.asarray(
        [
            [-2.0, -10.0, 7.0, 3.0],
            [-1.0, -7.0, 8.0, 3.0],
            [0.0, -1.0, 6.0, 3.0],
            [1.0, 4.0, 9.0, 3.0],
            [2.0, 11.0, 5.0, 3.0],
            [3.0, 17.0, 8.0, 3.0],
        ]
    )
    source = SherpaDataset(
        X=observations,
        feature_axis=FeatureAxis(labels=["age", "waist", "height", "constant"]),
        data_role="X_features",
    )
    result = execute_pca_node(
        source,
        node_id="pca",
        parameters={"n_components": "3", "standardized": standardized, "scaled": scaled},
    ).outputs
    correlations = result["variable_correlations"]
    scores = result["scores"].data

    assert correlations.data.shape == (3, 4)
    assert correlations.meta["undefined_feature_indices"] == [3]
    assert correlations.data[:, 3].tolist() == [0.0, 0.0, 0.0]
    assert list(correlations.feature_axis.labels) == ["age", "waist", "height", "constant"]
    for component in range(3):
        for feature in range(3):
            expected = np.corrcoef(observations[:, feature], scores[:, component])[0, 1]
            assert correlations.data[component, feature] == pytest.approx(expected, abs=1e-12)
            assert abs(correlations.data[component, feature]) <= 1.0
