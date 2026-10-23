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
from spectra_sherpa.core.contract_compatibility import predecessor_catalog
from spectra_sherpa.sdk.fitted_state_custody import (
    DATA_FREE_APPLICATION_STATE,
    RETAINS_TRAINING_ROWS,
    FittedStateCustodyError,
    fitted_state_custody_capability,
    require_data_free_fitted_state_members,
)

_CONTRACTS = {
    "spectrasherpa.model.fitted_pcr/1": "27f4c22c6ae6fb575c7e9cb2882de79143b166274356e739346cbe2d6f7f9a22",
    "spectrasherpa.model.fitted_svr/1": "2ac66187fb0e4fc00934d9630e68128888cd8c2c2c2d172194ee5ca550798fbc",
    "spectrasherpa.model.fitted_linear_regression/1": (
        "0249dc0427231232a1b543a5bdce6d1f1eceb5231719b41d0e65d52082bb4026"
    ),
    PLSDA_FITTED_STATE_SERIALIZER: "f8cb93e6a0b919054f55680e6d4e994bd310d122d3dfb0e40b095569cef53ef9",
    SIMCA_FITTED_STATE_SERIALIZER: "bd702d6c67ccd5e0450b7c084ee7c7b0d20a530a3eb364a5e53d1a07caf07bc8",
    FITTED_PLS_STATE_SERIALIZER: "473b586d631d966d9a76a32ec3788f95b7aea3771fb8981256475061d1b52871",
    "spectra.scale-reference-json.v2": "15bce0eb5aa942173878a911a7eba23cd3638f59fe37aa3c0e54f90506ff7e91",
    KNN_FITTED_STATE_SERIALIZER: "45dfeb78fef8ebf91d22edf584342724a5f5d8ca3532649ff86ea7347db0900f",
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
    current = predecessor_catalog()["current_contracts"]
    assert observed == {
        serializer: (
            digest
            if serializer
            in {
                FITTED_PLS_STATE_SERIALIZER,
                PLSDA_FITTED_STATE_SERIALIZER,
                KNN_FITTED_STATE_SERIALIZER,
                SIMCA_FITTED_STATE_SERIALIZER,
                "spectrasherpa.model.fitted_pcr/1",
                "spectrasherpa.model.fitted_svr/1",
                "spectrasherpa.model.fitted_linear_regression/1",
            }
            else current.get(_OPERATIONS[serializer], digest)
        )
        for serializer, digest in _CONTRACTS.items()
    }
    assert current["model.fitted_pls"] == "3543ba77a37677b1b5446a1fa3ff8e012cbfed71a7f6bbb75edf0ca89cbceef4"
    assert current["classification.plsda"] == "f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb"


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
