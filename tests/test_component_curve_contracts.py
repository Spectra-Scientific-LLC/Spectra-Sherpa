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
            "bcf69d89f62cb9e9ad1cfb46fc1f32b258c130dd571eb457df73fb535f685f0f",
        ),
        (
            "classification.plsda",
            "spectrasherpa.sherpa-plsda-state/5",
            "381926c2a35efa9c40ba364e2ef43f6055ac8133dd5754d32d5478fb916aa580",
            "50f7565a6e8ef6e6ce7b92e730588b9f1d1ef334015a8cf50555a793ed7815a2",
        ),
        (
            "classification.plsda",
            "spectrasherpa.sherpa-plsda-state/5",
            "a42f6b7a15955e08e7ec4c63fd335b17634454e21ff34b02f07a2077bea67cdb",
            "50f7565a6e8ef6e6ce7b92e730588b9f1d1ef334015a8cf50555a793ed7815a2",
        ),
        (
            "classification.plsda",
            "spectrasherpa.sherpa-plsda-state/5",
            "bae0976d0412483f985d6ad1e828cf39f8e5df5c82bb6d1284183781c4ce64ea",
            "50f7565a6e8ef6e6ce7b92e730588b9f1d1ef334015a8cf50555a793ed7815a2",
        ),
        (
            "model.fitted_pls",
            "spectra.sherpa-simpls-regression-json/9",
            "3543ba77a37677b1b5446a1fa3ff8e012cbfed71a7f6bbb75edf0ca89cbceef4",
            "ba02705c9868ae460e80af30207f8fa1c60f5ff20e8e6588be267292811472da",
        ),
        (
            "classification.plsda",
            "spectrasherpa.sherpa-plsda-state/5",
            "f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb",
            "50f7565a6e8ef6e6ce7b92e730588b9f1d1ef334015a8cf50555a793ed7815a2",
        ),
        (
            "classification.plsda",
            "spectrasherpa.sherpa-plsda-state/5",
            "00d9f4d468b96d949d1941e902bb8af727a16e22dc83cea93f22912a38fa3603",
            "50f7565a6e8ef6e6ce7b92e730588b9f1d1ef334015a8cf50555a793ed7815a2",
        ),
        (
            "model.pca",
            "spectrasherpa.model-artifact.pca/3",
            "ad9ee0dc72e2a6e9984134d8cfd7da6176ae725641c240f488f31713b57fcf94",
            "bcf69d89f62cb9e9ad1cfb46fc1f32b258c130dd571eb457df73fb535f685f0f",
        ),
        (
            "model.pca",
            "spectrasherpa.model-artifact.pca/3",
            "def76c765075b59a536e8c6bd72be0418c20d0ea4611f11ce5ec7f1a17ca891b",
            "bcf69d89f62cb9e9ad1cfb46fc1f32b258c130dd571eb457df73fb535f685f0f",
        ),
        (
            "model.fitted_pcr",
            "spectrasherpa.model.fitted_pcr/1",
            "a207b7fc520763105b633ca6d99eb267872c38ed54dc6854082b7be1bd1756b8",
            "99359a3588dfe55e29fd32428ce896d1ca503e3472e8b17a5982ed24d72a0d0d",
        ),
        (
            "model.fitted_pcr",
            "spectrasherpa.model.fitted_pcr/1",
            "b0b7e0e32445d63b864b27cc16a6831b9561a35a3614efd19220343902c45b3f",
            "99359a3588dfe55e29fd32428ce896d1ca503e3472e8b17a5982ed24d72a0d0d",
        ),
        (
            "model.fitted_svr",
            "spectrasherpa.model.fitted_svr/1",
            "29942ded909354f2ef273444108c7feb54525539ca8a24f091d7be9e3136decb",
            "b8ba060d1154848d0f96e25a0178c0c5eeff6658a4fc36de6ae3f7c82cb3f7ed",
        ),
        (
            "model.fitted_svr",
            "spectrasherpa.model.fitted_svr/1",
            "321d4a0411f164d20a3904dc438d886b1fb807c19200a2bb640ceaeb6169fc24",
            "b8ba060d1154848d0f96e25a0178c0c5eeff6658a4fc36de6ae3f7c82cb3f7ed",
        ),
        (
            "model.fitted_linear_regression",
            "spectrasherpa.model.fitted_linear_regression/1",
            "04d5ea448432137158df7b412286a17a5fe3498f5589ce53b33414fad2388b2b",
            "0ba997bbc87209703db011f38850ee82d93027bb72ab28db27aa108a8f9cca9a",
        ),
        (
            "model.fitted_linear_regression",
            "spectrasherpa.model.fitted_linear_regression/1",
            "19380f7cbefd4bd7196649760982a8d473d4062d86bfe6f8fdbef24dea042f53",
            "0ba997bbc87209703db011f38850ee82d93027bb72ab28db27aa108a8f9cca9a",
        ),
    ],
)
def test_exact_application_predecessor_only(operation: str, serializer: str, previous: str, current: str) -> None:
    workflow_consumers = {
        "model.pca": "1f31f0ab7581b4f68319d01574545fb3038f640c171c2f2df2dc68f48ce29b3f",
        "classification.plsda": "1775c23851d9ec5231755349dbf04ee2dcade3af8963e2e68e7911657316a236",
        "model.fitted_pls": "0544090d89826af9fe58a26321d966d36aeb55d36373e4789b6897ef7752254a",
        "model.fitted_linear_regression": "f28fc334028632f8bfce32aded3019e2d4094846825d0573b743f8b513b4f69f",
        "model.fitted_pcr": "af58a7e90bc1a7dffae447ab12048fa8b702ec493a86c256711ef0a3ccce2f63",
        "model.fitted_svr": "598257753f8ef867cf069372e8cdfb88d1a2ba3f6a862b12a8afd12e41b11179",
    }
    consumer = workflow_consumers.get(operation, current)
    assert node_registry.get_metadata(operation).resolved_execution_contract().digest == consumer
    assert saved_state_predecessor_is_compatible(previous, consumer, operation_id=operation, serializer=serializer)
    assert not saved_state_predecessor_is_compatible(consumer, previous, operation_id=operation, serializer=serializer)
    assert not saved_state_predecessor_is_compatible(
        previous, consumer, operation_id="model.other", serializer=serializer
    )
    assert not saved_state_predecessor_is_compatible(previous, consumer, operation_id=operation, serializer="wrong/1")
    # Preserve the historical component-phase pair as a separate assertion;
    # newer current readers do not rewrite its frozen consumer identity.
    assert saved_state_predecessor_is_compatible(previous, current, operation_id=operation, serializer=serializer)
    assert not saved_state_predecessor_is_compatible(current, previous, operation_id=operation, serializer=serializer)
    assert not saved_state_predecessor_is_compatible(
        previous, current, operation_id="model.other", serializer=serializer
    )
    assert not saved_state_predecessor_is_compatible(previous, current, operation_id=operation, serializer="wrong/1")
    if operation not in {"model.pca", "model.fitted_svr"}:
        assert fitted_state_custody_capability(serializer, current).custody_class == DATA_FREE_APPLICATION_STATE
