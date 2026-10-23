"""Exact read-only compatibility for component-evidence producer changes."""

from __future__ import annotations

import pytest

import spectra_sherpa.app.services.dag.nodes  # noqa: F401
from spectra_sherpa.app.services.dag.node_base import node_registry
from spectra_sherpa.core.contract_compatibility import saved_state_predecessor_is_compatible
from spectra_sherpa.sdk.fitted_state_custody import (
    DATA_FREE_APPLICATION_STATE,
    fitted_state_custody_capability,
)


@pytest.mark.parametrize(
    ("operation", "serializer", "previous", "current"),
    [
        (
            "model.pca",
            "spectrasherpa.model-artifact.pca/3",
            "c8f6c57e2e5ffe3f7ff3a6f5528cfef28ceea6eabfdac4d2c4572481d391ca75",
            "85b458d4b762f028fd9e825c47642460faf9f4682122def13416c88082a879f6",
        ),
        (
            "classification.plsda",
            "spectrasherpa.sherpa-plsda-state/5",
            "381926c2a35efa9c40ba364e2ef43f6055ac8133dd5754d32d5478fb916aa580",
            "85b2a1fd3938dee8a3a12f61397a07052883cd3f0bfa4d977151b600fe4992b6",
        ),
        (
            "classification.plsda",
            "spectrasherpa.sherpa-plsda-state/5",
            "a42f6b7a15955e08e7ec4c63fd335b17634454e21ff34b02f07a2077bea67cdb",
            "85b2a1fd3938dee8a3a12f61397a07052883cd3f0bfa4d977151b600fe4992b6",
        ),
        (
            "classification.plsda",
            "spectrasherpa.sherpa-plsda-state/5",
            "bae0976d0412483f985d6ad1e828cf39f8e5df5c82bb6d1284183781c4ce64ea",
            "85b2a1fd3938dee8a3a12f61397a07052883cd3f0bfa4d977151b600fe4992b6",
        ),
        (
            "model.fitted_pls",
            "spectra.sherpa-simpls-regression-json/9",
            "3543ba77a37677b1b5446a1fa3ff8e012cbfed71a7f6bbb75edf0ca89cbceef4",
            "473b586d631d966d9a76a32ec3788f95b7aea3771fb8981256475061d1b52871",
        ),
        (
            "classification.plsda",
            "spectrasherpa.sherpa-plsda-state/5",
            "f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb",
            "85b2a1fd3938dee8a3a12f61397a07052883cd3f0bfa4d977151b600fe4992b6",
        ),
        (
            "classification.plsda",
            "spectrasherpa.sherpa-plsda-state/5",
            "00d9f4d468b96d949d1941e902bb8af727a16e22dc83cea93f22912a38fa3603",
            "85b2a1fd3938dee8a3a12f61397a07052883cd3f0bfa4d977151b600fe4992b6",
        ),
        (
            "model.pca",
            "spectrasherpa.model-artifact.pca/3",
            "ad9ee0dc72e2a6e9984134d8cfd7da6176ae725641c240f488f31713b57fcf94",
            "85b458d4b762f028fd9e825c47642460faf9f4682122def13416c88082a879f6",
        ),
        (
            "model.pca",
            "spectrasherpa.model-artifact.pca/3",
            "def76c765075b59a536e8c6bd72be0418c20d0ea4611f11ce5ec7f1a17ca891b",
            "85b458d4b762f028fd9e825c47642460faf9f4682122def13416c88082a879f6",
        ),
        (
            "model.fitted_pcr",
            "spectrasherpa.model.fitted_pcr/1",
            "a207b7fc520763105b633ca6d99eb267872c38ed54dc6854082b7be1bd1756b8",
            "e76876f01548800f4b3ee2bdf0382359e046793a1e02e61e424e17b552256bf3",
        ),
        (
            "model.fitted_pcr",
            "spectrasherpa.model.fitted_pcr/1",
            "b0b7e0e32445d63b864b27cc16a6831b9561a35a3614efd19220343902c45b3f",
            "e76876f01548800f4b3ee2bdf0382359e046793a1e02e61e424e17b552256bf3",
        ),
        (
            "model.fitted_svr",
            "spectrasherpa.model.fitted_svr/1",
            "29942ded909354f2ef273444108c7feb54525539ca8a24f091d7be9e3136decb",
            "a6be415b3b1ed88d25ef0a220d1059031ada900f4c470d2a7cb762c250edf8af",
        ),
        (
            "model.fitted_svr",
            "spectrasherpa.model.fitted_svr/1",
            "321d4a0411f164d20a3904dc438d886b1fb807c19200a2bb640ceaeb6169fc24",
            "a6be415b3b1ed88d25ef0a220d1059031ada900f4c470d2a7cb762c250edf8af",
        ),
        (
            "model.fitted_linear_regression",
            "spectrasherpa.model.fitted_linear_regression/1",
            "04d5ea448432137158df7b412286a17a5fe3498f5589ce53b33414fad2388b2b",
            "a0a31850e5ec62ce5d3d45050af62f715306d1da9d84442d76d70b1b738303f8",
        ),
        (
            "model.fitted_linear_regression",
            "spectrasherpa.model.fitted_linear_regression/1",
            "19380f7cbefd4bd7196649760982a8d473d4062d86bfe6f8fdbef24dea042f53",
            "a0a31850e5ec62ce5d3d45050af62f715306d1da9d84442d76d70b1b738303f8",
        ),
    ],
)
def test_exact_application_predecessor_only(operation: str, serializer: str, previous: str, current: str) -> None:
    assert node_registry.get_metadata(operation).resolved_execution_contract().digest == current
    assert saved_state_predecessor_is_compatible(previous, current, operation_id=operation, serializer=serializer)
    assert not saved_state_predecessor_is_compatible(current, previous, operation_id=operation, serializer=serializer)
    assert not saved_state_predecessor_is_compatible(
        previous, current, operation_id="model.other", serializer=serializer
    )
    assert not saved_state_predecessor_is_compatible(previous, current, operation_id=operation, serializer="wrong/1")
    if operation not in {"model.pca", "model.fitted_svr"}:
        assert fitted_state_custody_capability(serializer, current).custody_class == DATA_FREE_APPLICATION_STATE
