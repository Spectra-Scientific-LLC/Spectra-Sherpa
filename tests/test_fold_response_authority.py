"""Response-only access preserves authority without exposing held-out targets."""

import numpy as np
import pytest

from spectra_sherpa.app.lib.sherpa_dataset import SampleAxis, SherpaDataset, TargetContext
from spectra_sherpa.app.services.dag.fold_lifecycle import (
    FoldLifecycleContext,
    FoldLifecycleError,
    FoldPartition,
    FullDataRefitContext,
)
from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import FittedPLSV2Node
from spectra_sherpa.app.services.dag.spectral_capability import SpectralDatasetCapability


@pytest.mark.parametrize("names,units,columns", [(["CN"], "index", 1), (["a", "b"], "percent", 2), (None, None, 1)])
def test_fold_and_full_refit_retain_only_response_authority(names, units, columns):
    X = np.arange(48, dtype=float).reshape(8, 6)
    y = np.column_stack([X[:, 0] * (j + 1) for j in range(columns)])
    source = SherpaDataset(
        X=X,
        target=y,
        units="absorbance",
        sample_axis=SampleAxis(labels=[f"specimen-{i}" for i in range(8)]),
        target_context=TargetContext(target_type="continuous", target_names=names, target_units=units),
    )
    capability = SpectralDatasetCapability.from_dataset(source, custody_id="authority-fixture")
    contract = FittedPLSV2Node.metadata.resolved_execution_contract()
    context = FoldLifecycleContext(
        contract, capability, FoldPartition.create([6, 2, 0, 4], [1, 3, 5, 7], sample_count=8)
    )
    response = context.target_dataset("train")
    predictors = context.dataset("train")
    assert predictors.target is None
    assert response.target is None
    assert response.units is None
    assert response.feature_axis is None
    assert (
        response.sample_axis.labels
        == predictors.sample_axis.labels
        == ["specimen-6", "specimen-2", "specimen-0", "specimen-4"]
    )
    node = FittedPLSV2Node("fit", {"n_components": 1})
    state = node.fit_fitted_state(predictors, response)
    assert state["response_identity"] == {"names": names, "units": [units] * columns}
    with pytest.raises(FoldLifecycleError, match="held-out"):
        context.target_dataset("test")
    full = FullDataRefitContext(contract, capability, validation_execution_digest="a" * 64)
    full_state = node.fit_fitted_state(full.dataset(), full.target_dataset())
    assert full_state["response_identity"] == state["response_identity"]
    # Positional input remains explicitly unknown; numerical predictions are unchanged.
    positional = node.fit_fitted_state(predictors, context.target("train"))
    assert positional["response_identity"]["units"] == [None] * columns
    np.testing.assert_allclose(
        node.apply_fitted_state(predictors, state), node.apply_fitted_state(predictors, positional)
    )


def test_selected_response_identity_is_not_borrowed_from_other_columns():
    X = np.arange(48, dtype=float).reshape(8, 6)
    source = SherpaDataset(
        X=X,
        target=X[:, 0],
        target_context=TargetContext(
            target_type="continuous", target_names=["a", "b"], selected_target="b", target_units="percent"
        ),
    )
    capability = SpectralDatasetCapability.from_dataset(source, custody_id="selected-response")
    contract = FittedPLSV2Node.metadata.resolved_execution_contract()
    full = FullDataRefitContext(contract, capability, validation_execution_digest="a" * 64)
    state = FittedPLSV2Node("fit", {"n_components": 1}).fit_fitted_state(full.dataset(), full.target_dataset())
    assert state["response_identity"] == {"names": ["b"], "units": ["percent"]}
