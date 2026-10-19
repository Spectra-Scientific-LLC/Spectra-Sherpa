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
    "spectrasherpa.model.fitted_pcr/1": "577777179c36fedf0338c84a003e9080aa8879043e2ad0e19e7dccc5f618c201",
    "spectrasherpa.model.fitted_svr/1": "cde922310dc4713ab5349720f865595fee13c8c2a53b60f68708ceed9882bae0",
    "spectrasherpa.model.fitted_linear_regression/1": (
        "10b125ffb88229b92cfe1eac67e5717117cfdf57d485b3e370abb2ef8910f6a7"
    ),
    PLSDA_FITTED_STATE_SERIALIZER: "526a54177bad1ec421ec319c031f6ba322fa431e7235cf35604e14d7ecf23f6c",
    SIMCA_FITTED_STATE_SERIALIZER: "16dfeba33f742c80aad2e8ae2dcccb42d430215b20b2fdfb77179f821db52034",
    FITTED_PLS_STATE_SERIALIZER: "473b586d631d966d9a76a32ec3788f95b7aea3771fb8981256475061d1b52871",
    "spectra.scale-reference-json.v2": "15bce0eb5aa942173878a911a7eba23cd3638f59fe37aa3c0e54f90506ff7e91",
    KNN_FITTED_STATE_SERIALIZER: "8acc66bc0b248e2ebfbd89f041dd0513b3505740fa5a2b5e3b4dbccba81f1206",
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
