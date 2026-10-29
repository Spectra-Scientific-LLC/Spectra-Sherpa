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
    "spectrasherpa.model.fitted_pcr/1": "99359a3588dfe55e29fd32428ce896d1ca503e3472e8b17a5982ed24d72a0d0d",
    "spectrasherpa.model.fitted_svr/1": "b8ba060d1154848d0f96e25a0178c0c5eeff6658a4fc36de6ae3f7c82cb3f7ed",
    "spectrasherpa.model.fitted_linear_regression/1": (
        "0ba997bbc87209703db011f38850ee82d93027bb72ab28db27aa108a8f9cca9a"
    ),
    PLSDA_FITTED_STATE_SERIALIZER: "50f7565a6e8ef6e6ce7b92e730588b9f1d1ef334015a8cf50555a793ed7815a2",
    SIMCA_FITTED_STATE_SERIALIZER: "2a591ac8626fe115463326b7f6b30b1ad3721c6392e6e4a07af786de13777388",
    FITTED_PLS_STATE_SERIALIZER: "ba02705c9868ae460e80af30207f8fa1c60f5ff20e8e6588be267292811472da",
    "spectra.scale-reference-json.v2": "15bce0eb5aa942173878a911a7eba23cd3638f59fe37aa3c0e54f90506ff7e91",
    KNN_FITTED_STATE_SERIALIZER: "df59b9d414abefb1c93de58ef405f3044ad4c6a02b23dd62cf8cd38c131b58a7",
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
    expected = {
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
    expected.update(
        {
            FITTED_PLS_STATE_SERIALIZER: "2252dec1ff34b651be6480a68a10662470aeaa566bfb9c179eba04f0d87c83e4",
            "spectrasherpa.model.fitted_pcr/1": "25f5e986f615ae0e787dfecbac7b3a544cd2a68583fc6cb213c60773c9639b9e",
            "spectrasherpa.model.fitted_svr/1": "fe7266dee9a09f27a7be7fae4ecba2c38af9c643d9f1bd71b67b8884cc49ea1d",
            "spectrasherpa.model.fitted_linear_regression/1": (
                "e67835fc9e93b0a1b5dcc306ed3cfcbbcae86eb515af3f7b730fe48cc1d79782"
            ),
            PLSDA_FITTED_STATE_SERIALIZER: "1775c23851d9ec5231755349dbf04ee2dcade3af8963e2e68e7911657316a236",
            "spectra.scale-reference-json.v2": "5bcce28bb446d20a2a5f1a44b43d10dc5d98c69e1b981d831151885b069b41e8",
        }
    )
    assert observed == expected
    for serializer in expected:
        fitted_state_custody_capability(serializer, expected[serializer])
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
