"""Closed serializer custody authority for data-free review packages."""

from __future__ import annotations

import pytest

from spectra_sherpa.app.services.dag import node_registry
from spectra_sherpa.app.services.dag.nodes.classification.knn_nodes import KNN_FITTED_STATE_SERIALIZER
from spectra_sherpa.app.services.dag.nodes.classification.plsda_state import (
    FITTED_STATE_SERIALIZER as PLSDA_FITTED_STATE_SERIALIZER,
)
from spectra_sherpa.app.services.dag.nodes.classification.simca_nodes import SIMCA_FITTED_STATE_SERIALIZER
from spectra_sherpa.app.services.dag.nodes.modeling.fitted_pls_node import FITTED_PLS_STATE_SERIALIZER
from spectra_sherpa.sdk.fitted_state_custody import (
    DATA_FREE_APPLICATION_STATE,
    RETAINS_TRAINING_ROWS,
    FittedStateCustodyError,
    fitted_state_custody_capability,
    require_data_free_fitted_state_members,
)

_CONTRACTS = {
    "spectrasherpa.model.fitted_pcr/1": "905cef6cd41f355e0f9a8e6847a03377f4de3c62c262aa8ce718055124b44cb6",
    "spectrasherpa.model.fitted_svr/1": "0daa0a05e555974ab7810bc97ddecc09abb00c24f7b5f6014be8a99aaee1b97b",
    "spectrasherpa.model.fitted_linear_regression/1": (
        "29ba32c09e04d094afdc28724b86615a0d77e3946c3990f5f181a539ca8eff6c"
    ),
    PLSDA_FITTED_STATE_SERIALIZER: "1875107445c8954ec79270de2b84c80507665cd069ea4558a9068fb2866c9cf7",
    SIMCA_FITTED_STATE_SERIALIZER: "fcf0e470363f4723d5c9f7d23e3323575a12ee85d56c085f066340b565182d72",
    FITTED_PLS_STATE_SERIALIZER: "5ae3215d3c522a75b16baecdf35e736537052f411fbf9833509a535320ee27d5",
    "spectra.scale-reference-json.v2": "15bce0eb5aa942173878a911a7eba23cd3638f59fe37aa3c0e54f90506ff7e91",
    KNN_FITTED_STATE_SERIALIZER: "8cab952a6aa59bf4e90b8037514c668a5e4318a017f6a98f870ffd1a77c8850a",
}

_OPERATIONS = {
    "spectrasherpa.model.fitted_pcr/1": "model.fitted_pcr",
    "spectrasherpa.model.fitted_svr/1": "model.fitted_svr",
    "spectrasherpa.model.fitted_linear_regression/1": "model.fitted_linear_regression",
    PLSDA_FITTED_STATE_SERIALIZER: "classification.plsda",
    SIMCA_FITTED_STATE_SERIALIZER: "classification.simca",
    FITTED_PLS_STATE_SERIALIZER: "model.fitted_pls",
    "spectra.scale-reference-json.v2": "preprocess.scale",
    KNN_FITTED_STATE_SERIALIZER: "classification.knn",
}


def test_custody_capabilities_bind_the_current_registered_execution_contracts() -> None:
    observed = {
        serializer: node_registry.get_metadata(operation_id).resolved_execution_contract().digest
        for serializer, operation_id in _OPERATIONS.items()
    }
    assert observed == _CONTRACTS


@pytest.mark.parametrize(
    "serializer",
    (
        PLSDA_FITTED_STATE_SERIALIZER,
        SIMCA_FITTED_STATE_SERIALIZER,
        FITTED_PLS_STATE_SERIALIZER,
        "spectra.scale-reference-json.v2",
        "spectrasherpa.model.fitted_pcr/1",
        "spectrasherpa.model.fitted_linear_regression/1",
    ),
)
def test_campaign_serializers_are_positively_classified_data_free(serializer: str) -> None:
    contract_digest = _CONTRACTS[serializer]
    assert fitted_state_custody_capability(serializer, contract_digest).custody_class == DATA_FREE_APPLICATION_STATE
    require_data_free_fitted_state_members(({"serializer": serializer, "contract_digest": contract_digest},))


def test_previous_scale_contract_remains_admitted_for_replay() -> None:
    previous = "1d575d6ae82824e6a10a9d7c0716584f7c47c22dfbd38a411212b48095c273a4"
    require_data_free_fitted_state_members(
        ({"serializer": "spectra.scale-reference-json.v1", "contract_digest": previous},)
    )


def test_knn_is_explicitly_classified_as_retaining_training_rows() -> None:
    contract_digest = _CONTRACTS[KNN_FITTED_STATE_SERIALIZER]
    assert (
        fitted_state_custody_capability(KNN_FITTED_STATE_SERIALIZER, contract_digest).custody_class
        == RETAINS_TRAINING_ROWS
    )
    with pytest.raises(FittedStateCustodyError, match="retains calibration"):
        require_data_free_fitted_state_members(
            ({"serializer": KNN_FITTED_STATE_SERIALIZER, "contract_digest": contract_digest},)
        )


@pytest.mark.parametrize(
    "serializer",
    [
        "spectrasherpa.model.fitted_svr/1",
        "spectrasherpa.model.fitted_pcr/1",
        "spectrasherpa.model.fitted_linear_regression/1",
    ],
)
def test_new_regression_serializer_contract_drift_is_not_silently_reclassified(serializer):
    with pytest.raises(FittedStateCustodyError, match="no closed custody capability"):
        fitted_state_custody_capability(serializer, "1" * 64)


@pytest.mark.parametrize("kernel", ["linear", "rbf"])
def test_svr_support_vectors_are_training_rows_even_for_linear_kernel(kernel):
    import numpy as np

    from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset

    X = np.random.default_rng(81).normal(size=(15, 4))
    fit = node_registry.create_node("model.fitted_svr", "model", {"kernel": kernel, "scale": False})
    state = fit.fit_fitted_state(SherpaDataset(X=X), X[:, 0] ** 2)
    support = np.asarray(state["state"]["support_vectors"])
    assert len(support) > 0
    assert all(any(np.array_equal(row, original) for original in X) for row in support)
    contract = fit.metadata.resolved_execution_contract()
    assert fitted_state_custody_capability(fit.serializer, contract.digest).custody_class == RETAINS_TRAINING_ROWS
    with pytest.raises(FittedStateCustodyError, match="retains calibration"):
        require_data_free_fitted_state_members(({"serializer": fit.serializer, "contract_digest": contract.digest},))


@pytest.mark.parametrize("serializer", (None, "", "spectrasherpa.future-serializer/1"))
def test_unknown_or_invalid_serializer_refuses_fail_closed(serializer: object) -> None:
    with pytest.raises(FittedStateCustodyError):
        fitted_state_custody_capability(serializer, "1" * 64)


def test_known_serializer_with_changed_contract_refuses_fail_closed() -> None:
    with pytest.raises(FittedStateCustodyError, match="serializer and contract"):
        fitted_state_custody_capability(PLSDA_FITTED_STATE_SERIALIZER, "1" * 64)
    with pytest.raises(FittedStateCustodyError, match="serializer and contract"):
        require_data_free_fitted_state_members(
            ({"serializer": PLSDA_FITTED_STATE_SERIALIZER, "contract_digest": "1" * 64},)
        )


def test_one_unsafe_member_refuses_the_complete_inventory() -> None:
    with pytest.raises(FittedStateCustodyError, match="retains calibration"):
        require_data_free_fitted_state_members(
            (
                {
                    "serializer": PLSDA_FITTED_STATE_SERIALIZER,
                    "contract_digest": _CONTRACTS[PLSDA_FITTED_STATE_SERIALIZER],
                },
                {
                    "serializer": KNN_FITTED_STATE_SERIALIZER,
                    "contract_digest": _CONTRACTS[KNN_FITTED_STATE_SERIALIZER],
                },
            )
        )
