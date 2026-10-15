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
            "model.fitted_pls",
            "spectra.sherpa-simpls-regression-json/9",
            "3543ba77a37677b1b5446a1fa3ff8e012cbfed71a7f6bbb75edf0ca89cbceef4",
            "3939dc715653c735c11d3993942bd8e8baf5343fd42e21341d5cde130dafdde3",
        ),
        (
            "classification.plsda",
            "spectrasherpa.sherpa-plsda-state/5",
            "f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb",
            "bae0976d0412483f985d6ad1e828cf39f8e5df5c82bb6d1284183781c4ce64ea",
        ),
        (
            "classification.plsda",
            "spectrasherpa.sherpa-plsda-state/5",
            "00d9f4d468b96d949d1941e902bb8af727a16e22dc83cea93f22912a38fa3603",
            "bae0976d0412483f985d6ad1e828cf39f8e5df5c82bb6d1284183781c4ce64ea",
        ),
        (
            "model.pca",
            "spectrasherpa.model-artifact.pca/3",
            "ad9ee0dc72e2a6e9984134d8cfd7da6176ae725641c240f488f31713b57fcf94",
            "c8f6c57e2e5ffe3f7ff3a6f5528cfef28ceea6eabfdac4d2c4572481d391ca75",
        ),
        (
            "model.pca",
            "spectrasherpa.model-artifact.pca/3",
            "def76c765075b59a536e8c6bd72be0418c20d0ea4611f11ce5ec7f1a17ca891b",
            "c8f6c57e2e5ffe3f7ff3a6f5528cfef28ceea6eabfdac4d2c4572481d391ca75",
        ),
        (
            "model.fitted_pcr",
            "spectrasherpa.model.fitted_pcr/1",
            "a207b7fc520763105b633ca6d99eb267872c38ed54dc6854082b7be1bd1756b8",
            "7f6040c174cae2889250e6a4bc22620af172207109a1d6ff0fe66ad35937f9de",
        ),
        (
            "model.fitted_pcr",
            "spectrasherpa.model.fitted_pcr/1",
            "b0b7e0e32445d63b864b27cc16a6831b9561a35a3614efd19220343902c45b3f",
            "7f6040c174cae2889250e6a4bc22620af172207109a1d6ff0fe66ad35937f9de",
        ),
        (
            "model.fitted_svr",
            "spectrasherpa.model.fitted_svr/1",
            "29942ded909354f2ef273444108c7feb54525539ca8a24f091d7be9e3136decb",
            "6015b47482335d0931239f6a52fea6825979c43c055e319c69deb3129b344c67",
        ),
        (
            "model.fitted_svr",
            "spectrasherpa.model.fitted_svr/1",
            "321d4a0411f164d20a3904dc438d886b1fb807c19200a2bb640ceaeb6169fc24",
            "6015b47482335d0931239f6a52fea6825979c43c055e319c69deb3129b344c67",
        ),
        (
            "model.fitted_linear_regression",
            "spectrasherpa.model.fitted_linear_regression/1",
            "04d5ea448432137158df7b412286a17a5fe3498f5589ce53b33414fad2388b2b",
            "63501135129058b92cd8b6d0db33d5d61d3407c0be4f25a53f984d4a0101e27a",
        ),
        (
            "model.fitted_linear_regression",
            "spectrasherpa.model.fitted_linear_regression/1",
            "19380f7cbefd4bd7196649760982a8d473d4062d86bfe6f8fdbef24dea042f53",
            "63501135129058b92cd8b6d0db33d5d61d3407c0be4f25a53f984d4a0101e27a",
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
