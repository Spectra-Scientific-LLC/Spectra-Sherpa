from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.app.services.dag.executor_types import WorkflowNode
from spectra_sherpa.app.services.dag.fold_graph_executor import execute_supervised_validation_fold
from spectra_sherpa.app.services.dag.fold_lifecycle import FoldPartition
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability
from spectra_sherpa.app.services.dag.validation_graph import admit_validation_graph
from spectra_sherpa.app.types import type_registry

MODELS = [("pcr", {"n_components": 2}), ("svr", {"kernel": "rbf"}), ("linear_regression", {"fit_intercept": True})]


@pytest.fixture(autouse=True)
def registry():
    if not type_registry.is_loaded:
        type_registry.load(Path(__file__).resolve().parents[1] / "src/spectra_sherpa/app/types")


@pytest.mark.parametrize("family,parameters", MODELS)
@pytest.mark.asyncio
async def test_each_model_is_fit_inside_fold_and_never_learns_heldout_targets(family, parameters):
    rng = np.random.default_rng(51)
    X = rng.normal(size=(18, 4))
    y = X[:, 0] * 3 + X[:, 1]
    partition = FoldPartition.create(list(range(12)), list(range(12, 18)), sample_count=18)
    graph = admit_validation_graph([WorkflowNode("fit", f"model.fitted_{family}", parameters)], [])

    def capability(target, features=X):
        return SpectralDatasetCapability.from_dataset(SherpaDataset(X=features, target=target), custody_id="test")

    first = await execute_supervised_validation_fold(graph, capability(y), partition)
    poisoned = y.copy()
    poisoned[12:] += 1e8
    second = await execute_supervised_validation_fold(graph, capability(poisoned), partition)
    np.testing.assert_array_equal(first.test_predictions, second.test_predictions)
    node = node_registry.create_node(f"model.fitted_{family}", "reference", parameters)
    state = node.fit_fitted_state(SherpaDataset(X=X[:12]), y[:12])
    expected = node.apply_fitted_state(SherpaDataset(X=X[12:]), state)
    np.testing.assert_allclose(first.test_predictions, expected)
    # Poisoning held-out X must also leave fitted training predictions unchanged.
    poisoned_X = X.copy()
    poisoned_X[12:] += 1e4
    shifted = await execute_supervised_validation_fold(graph, capability(y, poisoned_X), partition)
    np.testing.assert_array_equal(first.train_predictions, shifted.train_predictions)


@pytest.mark.parametrize("family,parameters", MODELS)
@pytest.mark.asyncio
async def test_explicit_workflow_fit_apply_and_generated_code_share_state(family, parameters):
    X = SherpaDataset(X=np.random.default_rng(53).normal(size=(16, 4)))
    y = X.X[:, 0] + X.X[:, 2]
    fit = node_registry.create_node(f"model.fitted_{family}", "fit", parameters)
    apply = node_registry.create_node(f"model.apply_fitted_{family}", "apply", {})
    trained = await fit.execute(X, y)
    predictions = await apply.execute(X, trained.outputs["fitted_state"])
    np.testing.assert_allclose(predictions.outputs["default"], trained.outputs["default"])
    scope = {"X": X, "y": y, "results": {}}
    exec("\n".join(fit.generate_python({"default": "X", "y": "y"}, indent="")), scope)
    exec(
        "\n".join(apply.generate_python({"default": "X", "fitted_state": "results['fit']['fitted_state']"}, indent="")),
        scope,
    )
    np.testing.assert_allclose(scope["results"]["apply"]["default"], predictions.outputs["default"])
    wrong = deepcopy(trained.outputs["fitted_state"])
    wrong["operation_id"] = "different_model"
    with pytest.raises(ValueError, match="different model"):
        await apply.execute(X, wrong)


@pytest.mark.parametrize("family,parameters", MODELS)
def test_nonfinite_training_rows_are_not_silently_dropped(family, parameters):
    fit = node_registry.create_node(f"model.fitted_{family}", "fit", parameters)
    with pytest.raises(ValueError, match="no rows are silently removed"):
        fit.fit_fitted_state(SherpaDataset(X=np.ones((8, 4))), np.array([1, 2, 3, 4, 5, 6, 7, np.nan]))
