"""Exact saved-state predecessors, never an execution-contract alias table.

The archived source identity stays attached to fitted state. These directional
registrations permit only reading that state with a reviewed current consumer;
they do not authorize a fit, historical graph execution, or receipt migration.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files

from spectra_sherpa.execution_contract_vocabulary import NodeExecutionContract

_CATALOG_SHA256 = "10d3c81c1708bbf8309ebe46b767a1d44498eb11c9aab10ee4f6b22614465a4d"


@lru_cache(maxsize=1)
def _catalog_bytes() -> bytes:
    raw = files("spectra_sherpa.core").joinpath("contract_predecessors_v060.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != _CATALOG_SHA256:
        raise ValueError("trusted contract predecessor catalog digest mismatch")
    return raw


def predecessor_catalog() -> dict:
    """Return detached, integrity-checked data from the packaged authority."""

    return json.loads(_catalog_bytes())


@dataclass(frozen=True)
class SavedStateCompatibility:
    operation_id: str
    predecessor_digest: str
    consumer_digest: str
    serializer: str


# Application-only, exact predecessor pairs for component-evidence output
# additions. The fitted-state serializers and training-row custody did not
# change. The historical catalog and its digest remain immutable.
_COMPONENT_EVIDENCE_PREDECESSORS = (
    SavedStateCompatibility(
        "model.pca",
        "ad9ee0dc72e2a6e9984134d8cfd7da6176ae725641c240f488f31713b57fcf94",
        "def76c765075b59a536e8c6bd72be0418c20d0ea4611f11ce5ec7f1a17ca891b",
        "spectrasherpa.model-artifact.pca/3",
    ),
    SavedStateCompatibility(
        "model.fitted_pls",
        "3543ba77a37677b1b5446a1fa3ff8e012cbfed71a7f6bbb75edf0ca89cbceef4",
        "9db6a10ca3c53faf7b0a69cee4aba35ebef148019ca21bf09ed226d578456997",
        "spectra.sherpa-simpls-regression-json/9",
    ),
    SavedStateCompatibility(
        "classification.plsda",
        "f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb",
        "00d9f4d468b96d949d1941e902bb8af727a16e22dc83cea93f22912a38fa3603",
        "spectrasherpa.sherpa-plsda-state/5",
    ),
    # Sample diagnostic output changes the producer contract while leaving the
    # fitted-state serializer unchanged. Admit both reviewed predecessors
    # directly; compatibility is never inferred transitively.
    SavedStateCompatibility(
        "classification.plsda",
        "00d9f4d468b96d949d1941e902bb8af727a16e22dc83cea93f22912a38fa3603",
        "381926c2a35efa9c40ba364e2ef43f6055ac8133dd5754d32d5478fb916aa580",
        "spectrasherpa.sherpa-plsda-state/5",
    ),
    SavedStateCompatibility(
        "classification.plsda",
        "f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb",
        "381926c2a35efa9c40ba364e2ef43f6055ac8133dd5754d32d5478fb916aa580",
        "spectrasherpa.sherpa-plsda-state/5",
    ),
    SavedStateCompatibility(
        "model.fitted_pcr",
        "a207b7fc520763105b633ca6d99eb267872c38ed54dc6854082b7be1bd1756b8",
        "7a58390a7bfb79ed0e7920dae41c2de5a3d8c6d8ca323754c3000fb9cd6cf4a4",
        "spectrasherpa.model.fitted_pcr/1",
    ),
    SavedStateCompatibility(
        "model.fitted_svr",
        "29942ded909354f2ef273444108c7feb54525539ca8a24f091d7be9e3136decb",
        "d3c36c524644edab0a1076190155baad4340ab549e34fc7a0e67b38f2d4f0a83",
        "spectrasherpa.model.fitted_svr/1",
    ),
    SavedStateCompatibility(
        "model.fitted_linear_regression",
        "04d5ea448432137158df7b412286a17a5fe3498f5589ce53b33414fad2388b2b",
        "a9c2343c3eb8cec79c5e25f14bf57a7793b7bbc7449eba0bc8249ad839c4463b",
        "spectrasherpa.model.fitted_linear_regression/1",
    ),
    # Independently archived pre-v0.6.0 state fixtures were already admitted
    # for application by the pinned catalog. Keep their original digests and
    # bind each directly to this consumer; do not infer compatibility by chain.
    SavedStateCompatibility(
        "model.fitted_pls",
        "5ae3215d3c522a75b16baecdf35e736537052f411fbf9833509a535320ee27d5",
        "9db6a10ca3c53faf7b0a69cee4aba35ebef148019ca21bf09ed226d578456997",
        "spectra.sherpa-simpls-regression-json/9",
    ),
    SavedStateCompatibility(
        "model.fitted_pcr",
        "905cef6cd41f355e0f9a8e6847a03377f4de3c62c262aa8ce718055124b44cb6",
        "7a58390a7bfb79ed0e7920dae41c2de5a3d8c6d8ca323754c3000fb9cd6cf4a4",
        "spectrasherpa.model.fitted_pcr/1",
    ),
    SavedStateCompatibility(
        "model.fitted_svr",
        "0daa0a05e555974ab7810bc97ddecc09abb00c24f7b5f6014be8a99aaee1b97b",
        "d3c36c524644edab0a1076190155baad4340ab549e34fc7a0e67b38f2d4f0a83",
        "spectrasherpa.model.fitted_svr/1",
    ),
    SavedStateCompatibility(
        "model.fitted_linear_regression",
        "29ba32c09e04d094afdc28724b86615a0d77e3946c3990f5f181a539ca8eff6c",
        "a9c2343c3eb8cec79c5e25f14bf57a7793b7bbc7449eba0bc8249ad839c4463b",
        "spectrasherpa.model.fitted_linear_regression/1",
    ),
)

# Cross-block repeatability changes split planning imported by the classifier,
# but not its fitted-state serializer or application math. The previous exact
# producer identities remain readable by this reviewed consumer only.
_CROSS_BLOCK_PLSDA_PREDECESSORS = tuple(
    SavedStateCompatibility(
        "classification.plsda",
        predecessor,
        "5cdcd5f0efd26e824c9c27f854d3feccca3be0018678602ef7882c30a5f645db",
        "spectrasherpa.sherpa-plsda-state/5",
    )
    for predecessor in (
        "f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb",
        "00d9f4d468b96d949d1941e902bb8af727a16e22dc83cea93f22912a38fa3603",
        "381926c2a35efa9c40ba364e2ef43f6055ac8133dd5754d32d5478fb916aa580",
        "bae0976d0412483f985d6ad1e828cf39f8e5df5c82bb6d1284183781c4ce64ea",
        "a42f6b7a15955e08e7ec4c63fd335b17634454e21ff34b02f07a2077bea67cdb",
    )
)

# Reference-quality outputs change producer execution identities without
# changing the saved-state serializers. Each previously qualified producer is
# admitted directly to this exact consumer for application only. The pinned
# historical catalog above remains immutable and grants no graph execution.
_REFERENCE_QUALITY_PREDECESSORS = tuple(
    SavedStateCompatibility(operation, predecessor, consumer, serializer)
    for operation, serializer, consumer, predecessors in (
        (
            "model.fitted_pls",
            "spectra.sherpa-simpls-regression-json/9",
            "3939dc715653c735c11d3993942bd8e8baf5343fd42e21341d5cde130dafdde3",
            (
                "5ae3215d3c522a75b16baecdf35e736537052f411fbf9833509a535320ee27d5",
                "3543ba77a37677b1b5446a1fa3ff8e012cbfed71a7f6bbb75edf0ca89cbceef4",
                "9db6a10ca3c53faf7b0a69cee4aba35ebef148019ca21bf09ed226d578456997",
            ),
        ),
        (
            "classification.plsda",
            "spectrasherpa.sherpa-plsda-state/5",
            "bae0976d0412483f985d6ad1e828cf39f8e5df5c82bb6d1284183781c4ce64ea",
            (
                "f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb",
                "00d9f4d468b96d949d1941e902bb8af727a16e22dc83cea93f22912a38fa3603",
                "381926c2a35efa9c40ba364e2ef43f6055ac8133dd5754d32d5478fb916aa580",
            ),
        ),
        (
            "model.fitted_pcr",
            "spectrasherpa.model.fitted_pcr/1",
            "b0b7e0e32445d63b864b27cc16a6831b9561a35a3614efd19220343902c45b3f",
            (
                "905cef6cd41f355e0f9a8e6847a03377f4de3c62c262aa8ce718055124b44cb6",
                "a207b7fc520763105b633ca6d99eb267872c38ed54dc6854082b7be1bd1756b8",
                "7a58390a7bfb79ed0e7920dae41c2de5a3d8c6d8ca323754c3000fb9cd6cf4a4",
            ),
        ),
        (
            "model.fitted_svr",
            "spectrasherpa.model.fitted_svr/1",
            "321d4a0411f164d20a3904dc438d886b1fb807c19200a2bb640ceaeb6169fc24",
            (
                "0daa0a05e555974ab7810bc97ddecc09abb00c24f7b5f6014be8a99aaee1b97b",
                "29942ded909354f2ef273444108c7feb54525539ca8a24f091d7be9e3136decb",
                "d3c36c524644edab0a1076190155baad4340ab549e34fc7a0e67b38f2d4f0a83",
            ),
        ),
        (
            "model.fitted_linear_regression",
            "spectrasherpa.model.fitted_linear_regression/1",
            "19380f7cbefd4bd7196649760982a8d473d4062d86bfe6f8fdbef24dea042f53",
            (
                "29ba32c09e04d094afdc28724b86615a0d77e3946c3990f5f181a539ca8eff6c",
                "04d5ea448432137158df7b412286a17a5fe3498f5589ce53b33414fad2388b2b",
                "a9c2343c3eb8cec79c5e25f14bf57a7793b7bbc7449eba0bc8249ad839c4463b",
            ),
        ),
    )
    for predecessor in predecessors
)

# The v0.6.1 MLR training-fit effect plot changes the fingerprint of the shared
# regression_nodes module. PCR, SVR and fitted MLR keep the same state serializers
# and application math. Admit only these reviewed producer identities to the
# exact merged-tree consumers, for saved-state application, never graph replay.
_V061_REGRESSION_DIAGNOSTIC_PREDECESSORS = tuple(
    SavedStateCompatibility(operation, predecessor, consumer, serializer)
    for operation, serializer, consumer, predecessors in (
        (
            "model.fitted_pcr",
            "spectrasherpa.model.fitted_pcr/1",
            "7f6040c174cae2889250e6a4bc22620af172207109a1d6ff0fe66ad35937f9de",
            (
                "905cef6cd41f355e0f9a8e6847a03377f4de3c62c262aa8ce718055124b44cb6",
                "a207b7fc520763105b633ca6d99eb267872c38ed54dc6854082b7be1bd1756b8",
                "7a58390a7bfb79ed0e7920dae41c2de5a3d8c6d8ca323754c3000fb9cd6cf4a4",
                "b0b7e0e32445d63b864b27cc16a6831b9561a35a3614efd19220343902c45b3f",
                "18c724b705c6c1331a82a45e7c4f7c2c8a6c4b91fb375385e3e146f3f39b9b11",
            ),
        ),
        (
            "model.fitted_svr",
            "spectrasherpa.model.fitted_svr/1",
            "6015b47482335d0931239f6a52fea6825979c43c055e319c69deb3129b344c67",
            (
                "0daa0a05e555974ab7810bc97ddecc09abb00c24f7b5f6014be8a99aaee1b97b",
                "29942ded909354f2ef273444108c7feb54525539ca8a24f091d7be9e3136decb",
                "d3c36c524644edab0a1076190155baad4340ab549e34fc7a0e67b38f2d4f0a83",
                "321d4a0411f164d20a3904dc438d886b1fb807c19200a2bb640ceaeb6169fc24",
                "f69be607b175147534980ea0afe932a6af4a846b2734d121dc76c9dceed65843",
            ),
        ),
        (
            "model.fitted_linear_regression",
            "spectrasherpa.model.fitted_linear_regression/1",
            "63501135129058b92cd8b6d0db33d5d61d3407c0be4f25a53f984d4a0101e27a",
            (
                "29ba32c09e04d094afdc28724b86615a0d77e3946c3990f5f181a539ca8eff6c",
                "04d5ea448432137158df7b412286a17a5fe3498f5589ce53b33414fad2388b2b",
                "a9c2343c3eb8cec79c5e25f14bf57a7793b7bbc7449eba0bc8249ad839c4463b",
                "19380f7cbefd4bd7196649760982a8d473d4062d86bfe6f8fdbef24dea042f53",
                "d4be993d68d26c1c38e6c09115713fe8111bf5f4ba559f75e9e8dc7d03c86e0e",
            ),
        ),
    )
    for predecessor in predecessors
)


# The v0.6.1 variable-correlation view adds a PCA result port but leaves the
# portable PCA state and its application math unchanged. Bind each reviewed
# predecessor directly to this consumer; do not infer transitive aliases.
_V061_PCA_PRESENTATION_PREDECESSORS = tuple(
    SavedStateCompatibility(
        "model.pca",
        predecessor,
        "c8f6c57e2e5ffe3f7ff3a6f5528cfef28ceea6eabfdac4d2c4572481d391ca75",
        "spectrasherpa.model-artifact.pca/3",
    )
    for predecessor in (
        "ad9ee0dc72e2a6e9984134d8cfd7da6176ae725641c240f488f31713b57fcf94",
        "def76c765075b59a536e8c6bd72be0418c20d0ea4611f11ce5ec7f1a17ca891b",
    )
)


# Persisting the already-validated PCA signal identity changes producer bytes,
# not the fitted state or projection math. These exact predecessors remain
# application-only; never authorize historical graph execution.
_PCA_SIGNAL_CUSTODY_PREDECESSORS = tuple(
    SavedStateCompatibility(
        "model.pca",
        predecessor,
        "2d4457cd7ca9ce699326aad70e1b4a77deb74d6cea88afd08066f106f45df161",
        "spectrasherpa.model-artifact.pca/3",
    )
    for predecessor in (
        "ad9ee0dc72e2a6e9984134d8cfd7da6176ae725641c240f488f31713b57fcf94",
        "def76c765075b59a536e8c6bd72be0418c20d0ea4611f11ce5ec7f1a17ca891b",
        "c8f6c57e2e5ffe3f7ff3a6f5528cfef28ceea6eabfdac4d2c4572481d391ca75",
    )
)


# Legacy admission changes the shared PLS-DA module fingerprint without
# changing native fitted-state serialization or prediction math. Keep each
# reviewed producer explicit; no transitive or graph-execution permission.
_PLSDA_LEGACY_ADMISSION_PREDECESSORS = tuple(
    SavedStateCompatibility(
        "classification.plsda",
        predecessor,
        "a42f6b7a15955e08e7ec4c63fd335b17634454e21ff34b02f07a2077bea67cdb",
        "spectrasherpa.sherpa-plsda-state/5",
    )
    for predecessor in (
        "f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb",
        "00d9f4d468b96d949d1941e902bb8af727a16e22dc83cea93f22912a38fa3603",
        "381926c2a35efa9c40ba364e2ef43f6055ac8133dd5754d32d5478fb916aa580",
        "bae0976d0412483f985d6ad1e828cf39f8e5df5c82bb6d1284183781c4ce64ea",
    )
)


# GUI presentation and SDK sample-axis repairs change shared source hashes,
# not these closed fitted-state schemas or application math. Each predecessor
# is enumerated explicitly; no wildcard, transitive or execution permission.
_GUI_SAMPLE_AUTHORITY_PREDECESSORS = tuple(
    SavedStateCompatibility(operation, predecessor, consumer, serializer)
    for operation, serializer, consumer, predecessors in (
        (
            "model.pca",
            "spectrasherpa.model-artifact.pca/3",
            "eeca5bea6642ec33c4a51c825acd58217d1a8c17784cfa318e4840e4c4ba73a9",
            (
                "ad9ee0dc72e2a6e9984134d8cfd7da6176ae725641c240f488f31713b57fcf94",
                "def76c765075b59a536e8c6bd72be0418c20d0ea4611f11ce5ec7f1a17ca891b",
                "c8f6c57e2e5ffe3f7ff3a6f5528cfef28ceea6eabfdac4d2c4572481d391ca75",
                "2d4457cd7ca9ce699326aad70e1b4a77deb74d6cea88afd08066f106f45df161",
            ),
        ),
        (
            "classification.plsda",
            "spectrasherpa.sherpa-plsda-state/5",
            "d7044e4303ac8a2a1b32e1fff471b06ddfa33fcee0258c3d1576ebcf2b352db9",
            (
                "f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb",
                "00d9f4d468b96d949d1941e902bb8af727a16e22dc83cea93f22912a38fa3603",
                "381926c2a35efa9c40ba364e2ef43f6055ac8133dd5754d32d5478fb916aa580",
                "bae0976d0412483f985d6ad1e828cf39f8e5df5c82bb6d1284183781c4ce64ea",
                "a42f6b7a15955e08e7ec4c63fd335b17634454e21ff34b02f07a2077bea67cdb",
                "5cdcd5f0efd26e824c9c27f854d3feccca3be0018678602ef7882c30a5f645db",
            ),
        ),
        (
            "classification.simca",
            "spectrasherpa.model-artifact.simca/2",
            "fb0f84fec93cc374fbdd00797ea361f8c9a83d22b6021f242815b4e83cecc0f0",
            ("58ae844cdcd14833a6da09a7f658e979ed08d812fc5bed7ef9d230be6e79d72e",),
        ),
        (
            "classification.knn",
            "spectrasherpa.model-artifact.knn/2",
            "7f188a7485c4774ccaa67d7efcf0cd95e35c07682633e9b5265d48f5e568be92",
            ("b75296b1e07af53623dfaf5e859b759d089eb1b4145a415bc555ff59cf4fec8a",),
        ),
        (
            "model.kmeans",
            "spectrasherpa.model.kmeans-state/1",
            "c65f7f11e6d2089abdec190e2c7aee80088eed4f2545ce55c0b92db1b2ebef30",
            (
                "c20e5cfbe10bd8957480c931f3c103684e63eb349415f5e0cd3097c9a4a962de",
                "466e832a2bdf8e856d875cfee2abfdbeff46bea55c77d6d5c005fcc2aeb01879",
            ),
        ),
        (
            "model.parafac",
            "spectrasherpa.model-artifact.parafac/2",
            "3c1525353cb993b328366260f5b751a2275048e2c39322ca424a91692ad24f68",
            (
                "dfcbb2f3a62ca3ea25bb59a62d57689f5ef338a0ca6221e8e8d92bbc38d46b43",
                "869e7edb4ca328e560bc543bfa4e6ed676314f6a8be49e2364985c3fe47a640d",
            ),
        ),
    )
    for predecessor in predecessors
)


# Scientific identity authority: exact application-only pairs. Stable row IDs
# replace display-label comparisons; serializers and application math are unchanged.
# Every previously admitted producer is listed directly, never accepted by chaining.
_SCIENTIFIC_AUTHORITY_PREDECESSORS = tuple(
    SavedStateCompatibility(operation, predecessor, consumer, serializer)
    for operation, serializer, consumer, predecessors in (
        (
            "model.pca",
            "spectrasherpa.model-artifact.pca/3",
            "5e809716a8266c4ddd5fb3902b8a68c264019fd05237bdb1397f664ae31dea10",
            (
                "ad9ee0dc72e2a6e9984134d8cfd7da6176ae725641c240f488f31713b57fcf94",
                "def76c765075b59a536e8c6bd72be0418c20d0ea4611f11ce5ec7f1a17ca891b",
                "c8f6c57e2e5ffe3f7ff3a6f5528cfef28ceea6eabfdac4d2c4572481d391ca75",
                "2d4457cd7ca9ce699326aad70e1b4a77deb74d6cea88afd08066f106f45df161",
                "eeca5bea6642ec33c4a51c825acd58217d1a8c17784cfa318e4840e4c4ba73a9",
            ),
        ),
        (
            "classification.plsda",
            "spectrasherpa.sherpa-plsda-state/5",
            "7e2148763934669f62e9de52982a9e75746e9e118ccfad820afcfd7a9230e4d0",
            (
                "f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb",
                "00d9f4d468b96d949d1941e902bb8af727a16e22dc83cea93f22912a38fa3603",
                "381926c2a35efa9c40ba364e2ef43f6055ac8133dd5754d32d5478fb916aa580",
                "bae0976d0412483f985d6ad1e828cf39f8e5df5c82bb6d1284183781c4ce64ea",
                "a42f6b7a15955e08e7ec4c63fd335b17634454e21ff34b02f07a2077bea67cdb",
                "5cdcd5f0efd26e824c9c27f854d3feccca3be0018678602ef7882c30a5f645db",
                "d7044e4303ac8a2a1b32e1fff471b06ddfa33fcee0258c3d1576ebcf2b352db9",
            ),
        ),
        (
            "classification.simca",
            "spectrasherpa.model-artifact.simca/2",
            "16dfeba33f742c80aad2e8ae2dcccb42d430215b20b2fdfb77179f821db52034",
            (
                "58ae844cdcd14833a6da09a7f658e979ed08d812fc5bed7ef9d230be6e79d72e",
                "fb0f84fec93cc374fbdd00797ea361f8c9a83d22b6021f242815b4e83cecc0f0",
            ),
        ),
        (
            "classification.knn",
            "spectrasherpa.model-artifact.knn/2",
            "8acc66bc0b248e2ebfbd89f041dd0513b3505740fa5a2b5e3b4dbccba81f1206",
            (
                "b75296b1e07af53623dfaf5e859b759d089eb1b4145a415bc555ff59cf4fec8a",
                "7f188a7485c4774ccaa67d7efcf0cd95e35c07682633e9b5265d48f5e568be92",
            ),
        ),
        (
            "model.parafac",
            "spectrasherpa.model-artifact.parafac/2",
            "caa04a3f25923cfc7d83fe38defd47db25fcb10be1375d51d516ebc82b544ac0",
            (
                "dfcbb2f3a62ca3ea25bb59a62d57689f5ef338a0ca6221e8e8d92bbc38d46b43",
                "869e7edb4ca328e560bc543bfa4e6ed676314f6a8be49e2364985c3fe47a640d",
                "3c1525353cb993b328366260f5b751a2275048e2c39322ca424a91692ad24f68",
            ),
        ),
    )
    for predecessor in predecessors
)


# Explicit feature-coordinate declarations only; fitted schemas and numerics
# are unchanged. These are direct application registrations, never graph replay.
_FEATURE_PRESENTATION_PREDECESSORS = tuple(
    SavedStateCompatibility(operation, predecessor, consumer, serializer)
    for operation, serializer, consumer, predecessors in (
        (
            "model.fitted_pls",
            "spectra.sherpa-simpls-regression-json/9",
            "473b586d631d966d9a76a32ec3788f95b7aea3771fb8981256475061d1b52871",
            (
                "3543ba77a37677b1b5446a1fa3ff8e012cbfed71a7f6bbb75edf0ca89cbceef4",
                "3939dc715653c735c11d3993942bd8e8baf5343fd42e21341d5cde130dafdde3",
                "5ae3215d3c522a75b16baecdf35e736537052f411fbf9833509a535320ee27d5",
                "9db6a10ca3c53faf7b0a69cee4aba35ebef148019ca21bf09ed226d578456997",
            ),
        ),
        (
            "classification.plsda",
            "spectrasherpa.sherpa-plsda-state/5",
            "526a54177bad1ec421ec319c031f6ba322fa431e7235cf35604e14d7ecf23f6c",
            (
                "00d9f4d468b96d949d1941e902bb8af727a16e22dc83cea93f22912a38fa3603",
                "381926c2a35efa9c40ba364e2ef43f6055ac8133dd5754d32d5478fb916aa580",
                "5cdcd5f0efd26e824c9c27f854d3feccca3be0018678602ef7882c30a5f645db",
                "7e2148763934669f62e9de52982a9e75746e9e118ccfad820afcfd7a9230e4d0",
                "a42f6b7a15955e08e7ec4c63fd335b17634454e21ff34b02f07a2077bea67cdb",
                "bae0976d0412483f985d6ad1e828cf39f8e5df5c82bb6d1284183781c4ce64ea",
                "d7044e4303ac8a2a1b32e1fff471b06ddfa33fcee0258c3d1576ebcf2b352db9",
                "f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb",
            ),
        ),
    )
    for predecessor in predecessors
)


_FEATURE_PRESENTATION_PREDECESSORS += tuple(
    SavedStateCompatibility(operation, predecessor, consumer, serializer)
    for operation, serializer, consumer, predecessors in (
        (
            "model.fitted_linear_regression",
            "spectrasherpa.model.fitted_linear_regression/1",
            "10b125ffb88229b92cfe1eac67e5717117cfdf57d485b3e370abb2ef8910f6a7",
            (
                "29ba32c09e04d094afdc28724b86615a0d77e3946c3990f5f181a539ca8eff6c",
                "04d5ea448432137158df7b412286a17a5fe3498f5589ce53b33414fad2388b2b",
                "a9c2343c3eb8cec79c5e25f14bf57a7793b7bbc7449eba0bc8249ad839c4463b",
                "19380f7cbefd4bd7196649760982a8d473d4062d86bfe6f8fdbef24dea042f53",
                "d4be993d68d26c1c38e6c09115713fe8111bf5f4ba559f75e9e8dc7d03c86e0e",
                "63501135129058b92cd8b6d0db33d5d61d3407c0be4f25a53f984d4a0101e27a",
            ),
        ),
        (
            "model.fitted_pcr",
            "spectrasherpa.model.fitted_pcr/1",
            "577777179c36fedf0338c84a003e9080aa8879043e2ad0e19e7dccc5f618c201",
            (
                "905cef6cd41f355e0f9a8e6847a03377f4de3c62c262aa8ce718055124b44cb6",
                "a207b7fc520763105b633ca6d99eb267872c38ed54dc6854082b7be1bd1756b8",
                "7a58390a7bfb79ed0e7920dae41c2de5a3d8c6d8ca323754c3000fb9cd6cf4a4",
                "b0b7e0e32445d63b864b27cc16a6831b9561a35a3614efd19220343902c45b3f",
                "18c724b705c6c1331a82a45e7c4f7c2c8a6c4b91fb375385e3e146f3f39b9b11",
                "7f6040c174cae2889250e6a4bc22620af172207109a1d6ff0fe66ad35937f9de",
            ),
        ),
        (
            "model.fitted_svr",
            "spectrasherpa.model.fitted_svr/1",
            "cde922310dc4713ab5349720f865595fee13c8c2a53b60f68708ceed9882bae0",
            (
                "0daa0a05e555974ab7810bc97ddecc09abb00c24f7b5f6014be8a99aaee1b97b",
                "29942ded909354f2ef273444108c7feb54525539ca8a24f091d7be9e3136decb",
                "d3c36c524644edab0a1076190155baad4340ab549e34fc7a0e67b38f2d4f0a83",
                "321d4a0411f164d20a3904dc438d886b1fb807c19200a2bb640ceaeb6169fc24",
                "f69be607b175147534980ea0afe932a6af4a846b2734d121dc76c9dceed65843",
                "6015b47482335d0931239f6a52fea6825979c43c055e319c69deb3129b344c67",
            ),
        ),
    )
    for predecessor in predecessors
)


# Reviewed typed input-refusal classification only. Comparison conditions, fitted
# schemas and numerics are unchanged. Every accepted producer is explicit;
# these registrations never authorize reverse/transitive or historical execution.
_DIAGNOSTIC_REFUSAL_PREDECESSORS = tuple(
    SavedStateCompatibility(operation, predecessor, consumer, serializer)
    for operation, serializer, consumer, predecessors in (
        (
            "classification.knn",
            "spectrasherpa.model-artifact.knn/2",
            "df59b9d414abefb1c93de58ef405f3044ad4c6a02b23dd62cf8cd38c131b58a7",
            (
                "7f188a7485c4774ccaa67d7efcf0cd95e35c07682633e9b5265d48f5e568be92",
                "8acc66bc0b248e2ebfbd89f041dd0513b3505740fa5a2b5e3b4dbccba81f1206",
                "b75296b1e07af53623dfaf5e859b759d089eb1b4145a415bc555ff59cf4fec8a",
            ),
        ),
        (
            "classification.plsda",
            "spectrasherpa.sherpa-plsda-state/5",
            "85b2a1fd3938dee8a3a12f61397a07052883cd3f0bfa4d977151b600fe4992b6",
            (
                "00d9f4d468b96d949d1941e902bb8af727a16e22dc83cea93f22912a38fa3603",
                "381926c2a35efa9c40ba364e2ef43f6055ac8133dd5754d32d5478fb916aa580",
                "526a54177bad1ec421ec319c031f6ba322fa431e7235cf35604e14d7ecf23f6c",
                "5cdcd5f0efd26e824c9c27f854d3feccca3be0018678602ef7882c30a5f645db",
                "7e2148763934669f62e9de52982a9e75746e9e118ccfad820afcfd7a9230e4d0",
                "a42f6b7a15955e08e7ec4c63fd335b17634454e21ff34b02f07a2077bea67cdb",
                "bae0976d0412483f985d6ad1e828cf39f8e5df5c82bb6d1284183781c4ce64ea",
                "d7044e4303ac8a2a1b32e1fff471b06ddfa33fcee0258c3d1576ebcf2b352db9",
                "f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb",
            ),
        ),
        (
            "classification.simca",
            "spectrasherpa.model-artifact.simca/2",
            "2a591ac8626fe115463326b7f6b30b1ad3721c6392e6e4a07af786de13777388",
            (
                "16dfeba33f742c80aad2e8ae2dcccb42d430215b20b2fdfb77179f821db52034",
                "58ae844cdcd14833a6da09a7f658e979ed08d812fc5bed7ef9d230be6e79d72e",
                "fb0f84fec93cc374fbdd00797ea361f8c9a83d22b6021f242815b4e83cecc0f0",
            ),
        ),
        (
            "model.fitted_linear_regression",
            "spectrasherpa.model.fitted_linear_regression/1",
            "a0a31850e5ec62ce5d3d45050af62f715306d1da9d84442d76d70b1b738303f8",
            (
                "04d5ea448432137158df7b412286a17a5fe3498f5589ce53b33414fad2388b2b",
                "10b125ffb88229b92cfe1eac67e5717117cfdf57d485b3e370abb2ef8910f6a7",
                "19380f7cbefd4bd7196649760982a8d473d4062d86bfe6f8fdbef24dea042f53",
                "29ba32c09e04d094afdc28724b86615a0d77e3946c3990f5f181a539ca8eff6c",
                "63501135129058b92cd8b6d0db33d5d61d3407c0be4f25a53f984d4a0101e27a",
                "a9c2343c3eb8cec79c5e25f14bf57a7793b7bbc7449eba0bc8249ad839c4463b",
                "d4be993d68d26c1c38e6c09115713fe8111bf5f4ba559f75e9e8dc7d03c86e0e",
            ),
        ),
        (
            "model.fitted_pcr",
            "spectrasherpa.model.fitted_pcr/1",
            "e76876f01548800f4b3ee2bdf0382359e046793a1e02e61e424e17b552256bf3",
            (
                "18c724b705c6c1331a82a45e7c4f7c2c8a6c4b91fb375385e3e146f3f39b9b11",
                "577777179c36fedf0338c84a003e9080aa8879043e2ad0e19e7dccc5f618c201",
                "7a58390a7bfb79ed0e7920dae41c2de5a3d8c6d8ca323754c3000fb9cd6cf4a4",
                "7f6040c174cae2889250e6a4bc22620af172207109a1d6ff0fe66ad35937f9de",
                "905cef6cd41f355e0f9a8e6847a03377f4de3c62c262aa8ce718055124b44cb6",
                "a207b7fc520763105b633ca6d99eb267872c38ed54dc6854082b7be1bd1756b8",
                "b0b7e0e32445d63b864b27cc16a6831b9561a35a3614efd19220343902c45b3f",
            ),
        ),
        (
            "model.fitted_svr",
            "spectrasherpa.model.fitted_svr/1",
            "a6be415b3b1ed88d25ef0a220d1059031ada900f4c470d2a7cb762c250edf8af",
            (
                "0daa0a05e555974ab7810bc97ddecc09abb00c24f7b5f6014be8a99aaee1b97b",
                "29942ded909354f2ef273444108c7feb54525539ca8a24f091d7be9e3136decb",
                "321d4a0411f164d20a3904dc438d886b1fb807c19200a2bb640ceaeb6169fc24",
                "6015b47482335d0931239f6a52fea6825979c43c055e319c69deb3129b344c67",
                "cde922310dc4713ab5349720f865595fee13c8c2a53b60f68708ceed9882bae0",
                "d3c36c524644edab0a1076190155baad4340ab549e34fc7a0e67b38f2d4f0a83",
                "f69be607b175147534980ea0afe932a6af4a846b2734d121dc76c9dceed65843",
            ),
        ),
        (
            "model.ica",
            "spectrasherpa.model-artifact.fastica/2",
            "96cf3f6dd097f4bbe30b4dcaf2c70f919fdb7abdce90b9d51ba4f25aa4a2427e",
            ("053d4bf663ea8242c2ad400629f7a9436035a826781346966cb62d95a19cac5a",),
        ),
        (
            "model.mcr_als",
            "spectrasherpa.model-artifact.mcr-als/2",
            "bc1c45f468420d8931ff66c71b388abaf32e1d459cc35a6b1d668c819470389e",
            ("ce5de4a28b2258eed1ad44509ae8f0aa9952f7f8b7d5097116ad55f5b21ba9d3",),
        ),
        (
            "model.pca",
            "spectrasherpa.model-artifact.pca/3",
            "85b458d4b762f028fd9e825c47642460faf9f4682122def13416c88082a879f6",
            (
                "2d4457cd7ca9ce699326aad70e1b4a77deb74d6cea88afd08066f106f45df161",
                "5e809716a8266c4ddd5fb3902b8a68c264019fd05237bdb1397f664ae31dea10",
                "ad9ee0dc72e2a6e9984134d8cfd7da6176ae725641c240f488f31713b57fcf94",
                "c8f6c57e2e5ffe3f7ff3a6f5528cfef28ceea6eabfdac4d2c4572481d391ca75",
                "def76c765075b59a536e8c6bd72be0418c20d0ea4611f11ce5ec7f1a17ca891b",
                "eeca5bea6642ec33c4a51c825acd58217d1a8c17784cfa318e4840e4c4ba73a9",
            ),
        ),
    )
    for predecessor in predecessors
)


# Exact application-only continuity after scientific display/CV dependency
# binding. Fitted arrays, serializers and custody are unchanged; no fit or
# historical execution is admitted, and no transitive inference is performed.
_SCIENTIFIC_AUDIT_PREDECESSORS = tuple(
    SavedStateCompatibility(operation, predecessor, consumer, serializer)
    for operation, serializer, consumer, predecessors in (
        (
            "classification.plsda",
            "spectrasherpa.sherpa-plsda-state/5",
            "50f7565a6e8ef6e6ce7b92e730588b9f1d1ef334015a8cf50555a793ed7815a2",
            (
                "00d9f4d468b96d949d1941e902bb8af727a16e22dc83cea93f22912a38fa3603",
                "381926c2a35efa9c40ba364e2ef43f6055ac8133dd5754d32d5478fb916aa580",
                "526a54177bad1ec421ec319c031f6ba322fa431e7235cf35604e14d7ecf23f6c",
                "5cdcd5f0efd26e824c9c27f854d3feccca3be0018678602ef7882c30a5f645db",
                "7e2148763934669f62e9de52982a9e75746e9e118ccfad820afcfd7a9230e4d0",
                "85b2a1fd3938dee8a3a12f61397a07052883cd3f0bfa4d977151b600fe4992b6",
                "a42f6b7a15955e08e7ec4c63fd335b17634454e21ff34b02f07a2077bea67cdb",
                "bae0976d0412483f985d6ad1e828cf39f8e5df5c82bb6d1284183781c4ce64ea",
                "d7044e4303ac8a2a1b32e1fff471b06ddfa33fcee0258c3d1576ebcf2b352db9",
                "f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb",
            ),
        ),
        (
            "model.fitted_linear_regression",
            "spectrasherpa.model.fitted_linear_regression/1",
            "0ba997bbc87209703db011f38850ee82d93027bb72ab28db27aa108a8f9cca9a",
            (
                "04d5ea448432137158df7b412286a17a5fe3498f5589ce53b33414fad2388b2b",
                "10b125ffb88229b92cfe1eac67e5717117cfdf57d485b3e370abb2ef8910f6a7",
                "19380f7cbefd4bd7196649760982a8d473d4062d86bfe6f8fdbef24dea042f53",
                "29ba32c09e04d094afdc28724b86615a0d77e3946c3990f5f181a539ca8eff6c",
                "63501135129058b92cd8b6d0db33d5d61d3407c0be4f25a53f984d4a0101e27a",
                "a0a31850e5ec62ce5d3d45050af62f715306d1da9d84442d76d70b1b738303f8",
                "a9c2343c3eb8cec79c5e25f14bf57a7793b7bbc7449eba0bc8249ad839c4463b",
                "d4be993d68d26c1c38e6c09115713fe8111bf5f4ba559f75e9e8dc7d03c86e0e",
            ),
        ),
        (
            "model.fitted_pcr",
            "spectrasherpa.model.fitted_pcr/1",
            "99359a3588dfe55e29fd32428ce896d1ca503e3472e8b17a5982ed24d72a0d0d",
            (
                "18c724b705c6c1331a82a45e7c4f7c2c8a6c4b91fb375385e3e146f3f39b9b11",
                "577777179c36fedf0338c84a003e9080aa8879043e2ad0e19e7dccc5f618c201",
                "7a58390a7bfb79ed0e7920dae41c2de5a3d8c6d8ca323754c3000fb9cd6cf4a4",
                "7f6040c174cae2889250e6a4bc22620af172207109a1d6ff0fe66ad35937f9de",
                "905cef6cd41f355e0f9a8e6847a03377f4de3c62c262aa8ce718055124b44cb6",
                "a207b7fc520763105b633ca6d99eb267872c38ed54dc6854082b7be1bd1756b8",
                "b0b7e0e32445d63b864b27cc16a6831b9561a35a3614efd19220343902c45b3f",
                "e76876f01548800f4b3ee2bdf0382359e046793a1e02e61e424e17b552256bf3",
            ),
        ),
        (
            "model.fitted_pls",
            "spectra.sherpa-simpls-regression-json/9",
            "ba02705c9868ae460e80af30207f8fa1c60f5ff20e8e6588be267292811472da",
            (
                "3543ba77a37677b1b5446a1fa3ff8e012cbfed71a7f6bbb75edf0ca89cbceef4",
                "3939dc715653c735c11d3993942bd8e8baf5343fd42e21341d5cde130dafdde3",
                "473b586d631d966d9a76a32ec3788f95b7aea3771fb8981256475061d1b52871",
                "5ae3215d3c522a75b16baecdf35e736537052f411fbf9833509a535320ee27d5",
                "9db6a10ca3c53faf7b0a69cee4aba35ebef148019ca21bf09ed226d578456997",
            ),
        ),
        (
            "model.fitted_svr",
            "spectrasherpa.model.fitted_svr/1",
            "b8ba060d1154848d0f96e25a0178c0c5eeff6658a4fc36de6ae3f7c82cb3f7ed",
            (
                "0daa0a05e555974ab7810bc97ddecc09abb00c24f7b5f6014be8a99aaee1b97b",
                "29942ded909354f2ef273444108c7feb54525539ca8a24f091d7be9e3136decb",
                "321d4a0411f164d20a3904dc438d886b1fb807c19200a2bb640ceaeb6169fc24",
                "6015b47482335d0931239f6a52fea6825979c43c055e319c69deb3129b344c67",
                "a6be415b3b1ed88d25ef0a220d1059031ada900f4c470d2a7cb762c250edf8af",
                "cde922310dc4713ab5349720f865595fee13c8c2a53b60f68708ceed9882bae0",
                "d3c36c524644edab0a1076190155baad4340ab549e34fc7a0e67b38f2d4f0a83",
                "f69be607b175147534980ea0afe932a6af4a846b2734d121dc76c9dceed65843",
            ),
        ),
        (
            "model.pca",
            "spectrasherpa.model-artifact.pca/3",
            "bcf69d89f62cb9e9ad1cfb46fc1f32b258c130dd571eb457df73fb535f685f0f",
            (
                "2d4457cd7ca9ce699326aad70e1b4a77deb74d6cea88afd08066f106f45df161",
                "5e809716a8266c4ddd5fb3902b8a68c264019fd05237bdb1397f664ae31dea10",
                "85b458d4b762f028fd9e825c47642460faf9f4682122def13416c88082a879f6",
                "ad9ee0dc72e2a6e9984134d8cfd7da6176ae725641c240f488f31713b57fcf94",
                "c8f6c57e2e5ffe3f7ff3a6f5528cfef28ceea6eabfdac4d2c4572481d391ca75",
                "def76c765075b59a536e8c6bd72be0418c20d0ea4611f11ce5ec7f1a17ca891b",
                "eeca5bea6642ec33c4a51c825acd58217d1a8c17784cfa318e4840e4c4ba73a9",
            ),
        ),
    )
    for predecessor in predecessors
)


@lru_cache(maxsize=1)
def saved_state_compatibilities() -> tuple[SavedStateCompatibility, ...]:
    """Reviewed inference producers only; no application or cohort-only nodes."""

    catalog = predecessor_catalog()
    result = []
    for operation in (
        "model.fitted_pls",
        "model.fitted_pcr",
        "model.fitted_svr",
        "model.fitted_linear_regression",
        "model.kmeans",
        "model.parafac",
    ):
        record = catalog["contracts"][operation]
        contract = NodeExecutionContract.from_dict(record["payload"])
        if contract.digest != record["digest"] or contract.payload["operation_id"] != operation:
            raise ValueError("trusted predecessor contract identity mismatch")
        result.append(
            SavedStateCompatibility(
                operation,
                contract.digest,
                catalog["current_contracts"][operation],
                contract.payload["fitted_state_serializer"],
            )
        )
    return tuple(result)


# Source curation/display hooks change implementation identities, not fitted
# state serializers or application formulas. Each previously admitted producer
# is bound directly to the exact current reader; this grants no old execution.
_WORKFLOW_POPULATION_PREDECESSORS = tuple(
    SavedStateCompatibility(operation, predecessor, consumer, serializer)
    for operation, serializer, consumer, predecessors in (
        (
            "classification.plsda",
            "spectrasherpa.sherpa-plsda-state/5",
            "1775c23851d9ec5231755349dbf04ee2dcade3af8963e2e68e7911657316a236",
            (
                "00d9f4d468b96d949d1941e902bb8af727a16e22dc83cea93f22912a38fa3603",
                "381926c2a35efa9c40ba364e2ef43f6055ac8133dd5754d32d5478fb916aa580",
                "50f7565a6e8ef6e6ce7b92e730588b9f1d1ef334015a8cf50555a793ed7815a2",
                "526a54177bad1ec421ec319c031f6ba322fa431e7235cf35604e14d7ecf23f6c",
                "5cdcd5f0efd26e824c9c27f854d3feccca3be0018678602ef7882c30a5f645db",
                "7e2148763934669f62e9de52982a9e75746e9e118ccfad820afcfd7a9230e4d0",
                "85b2a1fd3938dee8a3a12f61397a07052883cd3f0bfa4d977151b600fe4992b6",
                "a42f6b7a15955e08e7ec4c63fd335b17634454e21ff34b02f07a2077bea67cdb",
                "bae0976d0412483f985d6ad1e828cf39f8e5df5c82bb6d1284183781c4ce64ea",
                "d7044e4303ac8a2a1b32e1fff471b06ddfa33fcee0258c3d1576ebcf2b352db9",
                "f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb",
            ),
        ),
        (
            "model.fitted_pls",
            "spectra.sherpa-simpls-regression-json/9",
            "d1c86b21218f0191716a6c696fc97d737079c6847afbe6fd4fb168b17acf201e",
            (
                "3543ba77a37677b1b5446a1fa3ff8e012cbfed71a7f6bbb75edf0ca89cbceef4",
                "3939dc715653c735c11d3993942bd8e8baf5343fd42e21341d5cde130dafdde3",
                "473b586d631d966d9a76a32ec3788f95b7aea3771fb8981256475061d1b52871",
                "5ae3215d3c522a75b16baecdf35e736537052f411fbf9833509a535320ee27d5",
                "9db6a10ca3c53faf7b0a69cee4aba35ebef148019ca21bf09ed226d578456997",
                "ba02705c9868ae460e80af30207f8fa1c60f5ff20e8e6588be267292811472da",
            ),
        ),
        (
            "model.pca",
            "spectrasherpa.model-artifact.pca/3",
            "7f5425b11e126eb8c8359dd480e9af00c62a1d852fa372bed41e31c08d5cbf60",
            (
                "869a320a282d9484457f4e3237a0a098c26403c65ed1e699482403231630b608",
                "2d4457cd7ca9ce699326aad70e1b4a77deb74d6cea88afd08066f106f45df161",
                "5e809716a8266c4ddd5fb3902b8a68c264019fd05237bdb1397f664ae31dea10",
                "85b458d4b762f028fd9e825c47642460faf9f4682122def13416c88082a879f6",
                "ad9ee0dc72e2a6e9984134d8cfd7da6176ae725641c240f488f31713b57fcf94",
                "bcf69d89f62cb9e9ad1cfb46fc1f32b258c130dd571eb457df73fb535f685f0f",
                "c8f6c57e2e5ffe3f7ff3a6f5528cfef28ceea6eabfdac4d2c4572481d391ca75",
                "def76c765075b59a536e8c6bd72be0418c20d0ea4611f11ce5ec7f1a17ca891b",
                "eeca5bea6642ec33c4a51c825acd58217d1a8c17784cfa318e4840e4c4ba73a9",
            ),
        ),
    )
    for predecessor in predecessors
)


# Reviewed display-only input reuse: unchanged fit/application math and arrays.
# These are direct exact pairs, not transitive admission of arbitrary states.
_PCA_DISPLAY_INPUT_REUSE_PREDECESSORS = tuple(
    SavedStateCompatibility(
        "model.pca",
        predecessor,
        "1f31f0ab7581b4f68319d01574545fb3038f640c171c2f2df2dc68f48ce29b3f",
        "spectrasherpa.model-artifact.pca/3",
    )
    for predecessor in (
        "7f5425b11e126eb8c8359dd480e9af00c62a1d852fa372bed41e31c08d5cbf60",
        *(
            entry.predecessor_digest
            for entry in _WORKFLOW_POPULATION_PREDECESSORS
            if entry.operation_id == "model.pca"
            and entry.serializer == "spectrasherpa.model-artifact.pca/3"
            and entry.consumer_digest == "7f5425b11e126eb8c8359dd480e9af00c62a1d852fa372bed41e31c08d5cbf60"
        ),
    )
)


# Reviewed handoff repair: sample labels/typed IDs change only comparison
# presentation. Fit mathematics and serialized fitted state remain unchanged.
# Explicit pairs preserve known application producers; no transitive inference,
# reverse aliases, historical execution, or MCR truth-scoring alias is granted.
_HANDOFF_PRESENTATION_PREDECESSORS = tuple(
    SavedStateCompatibility(operation, predecessor, consumer, serializer)
    for operation, serializer, consumer, predecessors in (
        (
            "model.fitted_linear_regression",
            "spectrasherpa.model.fitted_linear_regression/1",
            "e67835fc9e93b0a1b5dcc306ed3cfcbbcae86eb515af3f7b730fe48cc1d79782",
            (
                "f28fc334028632f8bfce32aded3019e2d4094846825d0573b743f8b513b4f69f",
                "953c95ef58def16768d7280ee71e94f3837ab7d3d2076d48999804df3e32af23",
                "04d5ea448432137158df7b412286a17a5fe3498f5589ce53b33414fad2388b2b",
                "0ba997bbc87209703db011f38850ee82d93027bb72ab28db27aa108a8f9cca9a",
                "10b125ffb88229b92cfe1eac67e5717117cfdf57d485b3e370abb2ef8910f6a7",
                "19380f7cbefd4bd7196649760982a8d473d4062d86bfe6f8fdbef24dea042f53",
                "29ba32c09e04d094afdc28724b86615a0d77e3946c3990f5f181a539ca8eff6c",
                "63501135129058b92cd8b6d0db33d5d61d3407c0be4f25a53f984d4a0101e27a",
                "a0a31850e5ec62ce5d3d45050af62f715306d1da9d84442d76d70b1b738303f8",
                "a9c2343c3eb8cec79c5e25f14bf57a7793b7bbc7449eba0bc8249ad839c4463b",
                "d4be993d68d26c1c38e6c09115713fe8111bf5f4ba559f75e9e8dc7d03c86e0e",
            ),
        ),
        (
            "model.fitted_pcr",
            "spectrasherpa.model.fitted_pcr/1",
            "25f5e986f615ae0e787dfecbac7b3a544cd2a68583fc6cb213c60773c9639b9e",
            (
                "af58a7e90bc1a7dffae447ab12048fa8b702ec493a86c256711ef0a3ccce2f63",
                "754a5a53c49fda40269196838397458ffa26d6542953b2200c595e8d4a298f2a",
                "18c724b705c6c1331a82a45e7c4f7c2c8a6c4b91fb375385e3e146f3f39b9b11",
                "577777179c36fedf0338c84a003e9080aa8879043e2ad0e19e7dccc5f618c201",
                "7a58390a7bfb79ed0e7920dae41c2de5a3d8c6d8ca323754c3000fb9cd6cf4a4",
                "7f6040c174cae2889250e6a4bc22620af172207109a1d6ff0fe66ad35937f9de",
                "905cef6cd41f355e0f9a8e6847a03377f4de3c62c262aa8ce718055124b44cb6",
                "99359a3588dfe55e29fd32428ce896d1ca503e3472e8b17a5982ed24d72a0d0d",
                "a207b7fc520763105b633ca6d99eb267872c38ed54dc6854082b7be1bd1756b8",
                "b0b7e0e32445d63b864b27cc16a6831b9561a35a3614efd19220343902c45b3f",
                "e76876f01548800f4b3ee2bdf0382359e046793a1e02e61e424e17b552256bf3",
            ),
        ),
        (
            "model.fitted_pls",
            "spectra.sherpa-simpls-regression-json/9",
            "2252dec1ff34b651be6480a68a10662470aeaa566bfb9c179eba04f0d87c83e4",
            (
                "7e577601daba52133d0e63f7496614960747b78a438c03c01297c22b28226012",
                "0544090d89826af9fe58a26321d966d36aeb55d36373e4789b6897ef7752254a",
                "a4c4da78fab49c9c21badb8b0e851ff28d6c0459b267943a6a7e0183f7ed128d",
                "3543ba77a37677b1b5446a1fa3ff8e012cbfed71a7f6bbb75edf0ca89cbceef4",
                "3939dc715653c735c11d3993942bd8e8baf5343fd42e21341d5cde130dafdde3",
                "473b586d631d966d9a76a32ec3788f95b7aea3771fb8981256475061d1b52871",
                "5ae3215d3c522a75b16baecdf35e736537052f411fbf9833509a535320ee27d5",
                "9db6a10ca3c53faf7b0a69cee4aba35ebef148019ca21bf09ed226d578456997",
                "ba02705c9868ae460e80af30207f8fa1c60f5ff20e8e6588be267292811472da",
                "d1c86b21218f0191716a6c696fc97d737079c6847afbe6fd4fb168b17acf201e",
            ),
        ),
        (
            "model.fitted_svr",
            "spectrasherpa.model.fitted_svr/1",
            "fe7266dee9a09f27a7be7fae4ecba2c38af9c643d9f1bd71b67b8884cc49ea1d",
            (
                "598257753f8ef867cf069372e8cdfb88d1a2ba3f6a862b12a8afd12e41b11179",
                "4e8a05f4ca0147570f038542448c3391444ee5df09405c8a37a506599cb66344",
                "0daa0a05e555974ab7810bc97ddecc09abb00c24f7b5f6014be8a99aaee1b97b",
                "29942ded909354f2ef273444108c7feb54525539ca8a24f091d7be9e3136decb",
                "321d4a0411f164d20a3904dc438d886b1fb807c19200a2bb640ceaeb6169fc24",
                "6015b47482335d0931239f6a52fea6825979c43c055e319c69deb3129b344c67",
                "a6be415b3b1ed88d25ef0a220d1059031ada900f4c470d2a7cb762c250edf8af",
                "b8ba060d1154848d0f96e25a0178c0c5eeff6658a4fc36de6ae3f7c82cb3f7ed",
                "cde922310dc4713ab5349720f865595fee13c8c2a53b60f68708ceed9882bae0",
                "d3c36c524644edab0a1076190155baad4340ab549e34fc7a0e67b38f2d4f0a83",
                "f69be607b175147534980ea0afe932a6af4a846b2734d121dc76c9dceed65843",
            ),
        ),
    )
    for predecessor in predecessors
)


# Optional training-fold LV selection leaves the closed saved-state numerical
# application ABI unchanged. These exact directional pairs permit application
# only: old fits are neither relabelled nor replayed with automatic selection.
_AUTOMATIC_PLS_APPLICATION_PREDECESSORS = tuple(
    SavedStateCompatibility(operation, predecessor, consumer, serializer)
    for operation, serializer, consumer, predecessors in (
        (
            "model.fitted_pls",
            "spectra.sherpa-simpls-regression-json/9",
            "806989d7315252bbcf7130ede99ed641d4288b4e1c0ea573633875e868e21963",
            (
                "0544090d89826af9fe58a26321d966d36aeb55d36373e4789b6897ef7752254a",
                "2252dec1ff34b651be6480a68a10662470aeaa566bfb9c179eba04f0d87c83e4",
                "3543ba77a37677b1b5446a1fa3ff8e012cbfed71a7f6bbb75edf0ca89cbceef4",
                "3939dc715653c735c11d3993942bd8e8baf5343fd42e21341d5cde130dafdde3",
                "473b586d631d966d9a76a32ec3788f95b7aea3771fb8981256475061d1b52871",
                "5ae3215d3c522a75b16baecdf35e736537052f411fbf9833509a535320ee27d5",
                "7e577601daba52133d0e63f7496614960747b78a438c03c01297c22b28226012",
                "9db6a10ca3c53faf7b0a69cee4aba35ebef148019ca21bf09ed226d578456997",
                "a4c4da78fab49c9c21badb8b0e851ff28d6c0459b267943a6a7e0183f7ed128d",
                "ba02705c9868ae460e80af30207f8fa1c60f5ff20e8e6588be267292811472da",
                "d1c86b21218f0191716a6c696fc97d737079c6847afbe6fd4fb168b17acf201e",
            ),
        ),
        (
            "model.fitted_pcr",
            "spectrasherpa.model.fitted_pcr/1",
            "a5c5f2391a6d4fe5edb50253b6ddbc28759d4484ab95969e06174c4ed8b25f71",
            (
                "18c724b705c6c1331a82a45e7c4f7c2c8a6c4b91fb375385e3e146f3f39b9b11",
                "25f5e986f615ae0e787dfecbac7b3a544cd2a68583fc6cb213c60773c9639b9e",
                "577777179c36fedf0338c84a003e9080aa8879043e2ad0e19e7dccc5f618c201",
                "754a5a53c49fda40269196838397458ffa26d6542953b2200c595e8d4a298f2a",
                "7a58390a7bfb79ed0e7920dae41c2de5a3d8c6d8ca323754c3000fb9cd6cf4a4",
                "7f6040c174cae2889250e6a4bc22620af172207109a1d6ff0fe66ad35937f9de",
                "905cef6cd41f355e0f9a8e6847a03377f4de3c62c262aa8ce718055124b44cb6",
                "99359a3588dfe55e29fd32428ce896d1ca503e3472e8b17a5982ed24d72a0d0d",
                "a207b7fc520763105b633ca6d99eb267872c38ed54dc6854082b7be1bd1756b8",
                "af58a7e90bc1a7dffae447ab12048fa8b702ec493a86c256711ef0a3ccce2f63",
                "b0b7e0e32445d63b864b27cc16a6831b9561a35a3614efd19220343902c45b3f",
                "e76876f01548800f4b3ee2bdf0382359e046793a1e02e61e424e17b552256bf3",
            ),
        ),
        (
            "model.fitted_svr",
            "spectrasherpa.model.fitted_svr/1",
            "6fd3f58b2f4a69418498edb4979f9dc45c0685b4f84510f779b281dca5afd8b6",
            (
                "0daa0a05e555974ab7810bc97ddecc09abb00c24f7b5f6014be8a99aaee1b97b",
                "29942ded909354f2ef273444108c7feb54525539ca8a24f091d7be9e3136decb",
                "321d4a0411f164d20a3904dc438d886b1fb807c19200a2bb640ceaeb6169fc24",
                "4e8a05f4ca0147570f038542448c3391444ee5df09405c8a37a506599cb66344",
                "598257753f8ef867cf069372e8cdfb88d1a2ba3f6a862b12a8afd12e41b11179",
                "6015b47482335d0931239f6a52fea6825979c43c055e319c69deb3129b344c67",
                "a6be415b3b1ed88d25ef0a220d1059031ada900f4c470d2a7cb762c250edf8af",
                "b8ba060d1154848d0f96e25a0178c0c5eeff6658a4fc36de6ae3f7c82cb3f7ed",
                "cde922310dc4713ab5349720f865595fee13c8c2a53b60f68708ceed9882bae0",
                "d3c36c524644edab0a1076190155baad4340ab549e34fc7a0e67b38f2d4f0a83",
                "f69be607b175147534980ea0afe932a6af4a846b2734d121dc76c9dceed65843",
                "fe7266dee9a09f27a7be7fae4ecba2c38af9c643d9f1bd71b67b8884cc49ea1d",
            ),
        ),
        (
            "model.fitted_linear_regression",
            "spectrasherpa.model.fitted_linear_regression/1",
            "2126706c399de312076750bc4d54f33fb1736e88b3eb70df26b36ab38d25dba6",
            (
                "04d5ea448432137158df7b412286a17a5fe3498f5589ce53b33414fad2388b2b",
                "0ba997bbc87209703db011f38850ee82d93027bb72ab28db27aa108a8f9cca9a",
                "10b125ffb88229b92cfe1eac67e5717117cfdf57d485b3e370abb2ef8910f6a7",
                "19380f7cbefd4bd7196649760982a8d473d4062d86bfe6f8fdbef24dea042f53",
                "29ba32c09e04d094afdc28724b86615a0d77e3946c3990f5f181a539ca8eff6c",
                "63501135129058b92cd8b6d0db33d5d61d3407c0be4f25a53f984d4a0101e27a",
                "953c95ef58def16768d7280ee71e94f3837ab7d3d2076d48999804df3e32af23",
                "a0a31850e5ec62ce5d3d45050af62f715306d1da9d84442d76d70b1b738303f8",
                "a9c2343c3eb8cec79c5e25f14bf57a7793b7bbc7449eba0bc8249ad839c4463b",
                "d4be993d68d26c1c38e6c09115713fe8111bf5f4ba559f75e9e8dc7d03c86e0e",
                "e67835fc9e93b0a1b5dcc306ed3cfcbbcae86eb515af3f7b730fe48cc1d79782",
                "f28fc334028632f8bfce32aded3019e2d4094846825d0573b743f8b513b4f69f",
            ),
        ),
    )
    for predecessor in predecessors
)


# The specimen-independence guard changes optional CV availability only. The
# classifier fit, serialized state, and application mathematics are unchanged.
# Exact reviewed predecessors are granted application, never old execution.
_PLSDA_INDEPENDENCE_READERS = tuple(
    SavedStateCompatibility(
        "classification.plsda",
        predecessor,
        "ff671687b815e9647e7b1b0ead2edab5839422196dcdb150ae1de798b9cd6824",
        "spectrasherpa.sherpa-plsda-state/5",
    )
    for predecessor in (
        "00d9f4d468b96d949d1941e902bb8af727a16e22dc83cea93f22912a38fa3603",
        "1775c23851d9ec5231755349dbf04ee2dcade3af8963e2e68e7911657316a236",
        "381926c2a35efa9c40ba364e2ef43f6055ac8133dd5754d32d5478fb916aa580",
        "50f7565a6e8ef6e6ce7b92e730588b9f1d1ef334015a8cf50555a793ed7815a2",
        "526a54177bad1ec421ec319c031f6ba322fa431e7235cf35604e14d7ecf23f6c",
        "5cdcd5f0efd26e824c9c27f854d3feccca3be0018678602ef7882c30a5f645db",
        "7e2148763934669f62e9de52982a9e75746e9e118ccfad820afcfd7a9230e4d0",
        "85b2a1fd3938dee8a3a12f61397a07052883cd3f0bfa4d977151b600fe4992b6",
        "a42f6b7a15955e08e7ec4c63fd335b17634454e21ff34b02f07a2077bea67cdb",
        "bae0976d0412483f985d6ad1e828cf39f8e5df5c82bb6d1284183781c4ce64ea",
        "d7044e4303ac8a2a1b32e1fff471b06ddfa33fcee0258c3d1576ebcf2b352db9",
        "f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb",
    )
)


# Qualification expands only sample-local preprocessing provenance. Saved-state
# mathematics/serializers are unchanged. Exact application-only readers do not
# authorize historical fits, profile rebinding, or transitive compatibility.
_PREPROCESSING_APPLICATION_PREDECESSORS = tuple(
    SavedStateCompatibility(operation, predecessor, consumer, serializer)
    for operation, serializer, consumer, predecessors in (
        (
            "model.pca",
            "spectrasherpa.model-artifact.pca/3",
            "3832e1488a123217d7068bcf33dae7aa982b5665dec00c402cfb034fd11064c4",
            (
                "1f31f0ab7581b4f68319d01574545fb3038f640c171c2f2df2dc68f48ce29b3f",
                "2d4457cd7ca9ce699326aad70e1b4a77deb74d6cea88afd08066f106f45df161",
                "5e809716a8266c4ddd5fb3902b8a68c264019fd05237bdb1397f664ae31dea10",
                "7f5425b11e126eb8c8359dd480e9af00c62a1d852fa372bed41e31c08d5cbf60",
                "85b458d4b762f028fd9e825c47642460faf9f4682122def13416c88082a879f6",
                "869a320a282d9484457f4e3237a0a098c26403c65ed1e699482403231630b608",
                "ad9ee0dc72e2a6e9984134d8cfd7da6176ae725641c240f488f31713b57fcf94",
                "bcf69d89f62cb9e9ad1cfb46fc1f32b258c130dd571eb457df73fb535f685f0f",
                "c8f6c57e2e5ffe3f7ff3a6f5528cfef28ceea6eabfdac4d2c4572481d391ca75",
                "def76c765075b59a536e8c6bd72be0418c20d0ea4611f11ce5ec7f1a17ca891b",
                "eeca5bea6642ec33c4a51c825acd58217d1a8c17784cfa318e4840e4c4ba73a9",
            ),
        ),
        (
            "model.fitted_pls",
            "spectra.sherpa-simpls-regression-json/9",
            "ec228e11a36dfdab98bf14f8bb1ebf829044325f57ae23f3f24016cb2a0994ac",
            (
                "0544090d89826af9fe58a26321d966d36aeb55d36373e4789b6897ef7752254a",
                "2252dec1ff34b651be6480a68a10662470aeaa566bfb9c179eba04f0d87c83e4",
                "3543ba77a37677b1b5446a1fa3ff8e012cbfed71a7f6bbb75edf0ca89cbceef4",
                "3939dc715653c735c11d3993942bd8e8baf5343fd42e21341d5cde130dafdde3",
                "473b586d631d966d9a76a32ec3788f95b7aea3771fb8981256475061d1b52871",
                "5ae3215d3c522a75b16baecdf35e736537052f411fbf9833509a535320ee27d5",
                "7e577601daba52133d0e63f7496614960747b78a438c03c01297c22b28226012",
                "806989d7315252bbcf7130ede99ed641d4288b4e1c0ea573633875e868e21963",
                "9db6a10ca3c53faf7b0a69cee4aba35ebef148019ca21bf09ed226d578456997",
                "a4c4da78fab49c9c21badb8b0e851ff28d6c0459b267943a6a7e0183f7ed128d",
                "ba02705c9868ae460e80af30207f8fa1c60f5ff20e8e6588be267292811472da",
                "d1c86b21218f0191716a6c696fc97d737079c6847afbe6fd4fb168b17acf201e",
            ),
        ),
        (
            "classification.plsda",
            "spectrasherpa.sherpa-plsda-state/5",
            "65017fa4efd2c518f7f07dbdd12c332cb472b13ee6b734b69f4c9569aa445b7f",
            (
                "00d9f4d468b96d949d1941e902bb8af727a16e22dc83cea93f22912a38fa3603",
                "1775c23851d9ec5231755349dbf04ee2dcade3af8963e2e68e7911657316a236",
                "381926c2a35efa9c40ba364e2ef43f6055ac8133dd5754d32d5478fb916aa580",
                "50f7565a6e8ef6e6ce7b92e730588b9f1d1ef334015a8cf50555a793ed7815a2",
                "526a54177bad1ec421ec319c031f6ba322fa431e7235cf35604e14d7ecf23f6c",
                "5cdcd5f0efd26e824c9c27f854d3feccca3be0018678602ef7882c30a5f645db",
                "7e2148763934669f62e9de52982a9e75746e9e118ccfad820afcfd7a9230e4d0",
                "85b2a1fd3938dee8a3a12f61397a07052883cd3f0bfa4d977151b600fe4992b6",
                "a42f6b7a15955e08e7ec4c63fd335b17634454e21ff34b02f07a2077bea67cdb",
                "bae0976d0412483f985d6ad1e828cf39f8e5df5c82bb6d1284183781c4ce64ea",
                "d7044e4303ac8a2a1b32e1fff471b06ddfa33fcee0258c3d1576ebcf2b352db9",
                "f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb",
                "ff671687b815e9647e7b1b0ead2edab5839422196dcdb150ae1de798b9cd6824",
            ),
        ),
    )
    for predecessor in predecessors
)


# Typed diagnostic identities change only the fit producer source closure.
# Keep direct application-only pairs; no reverse or transitive inference.
_PLSDA_DIAGNOSTIC_IDENTITY_PREDECESSORS = tuple(
    SavedStateCompatibility(
        "classification.plsda",
        predecessor,
        "b4910376c363b3564a1fb959b52ab75ca93b7744f5b15d19caa582258ca43f43",
        "spectrasherpa.sherpa-plsda-state/5",
    )
    for predecessor in (
        "00d9f4d468b96d949d1941e902bb8af727a16e22dc83cea93f22912a38fa3603",
        "1775c23851d9ec5231755349dbf04ee2dcade3af8963e2e68e7911657316a236",
        "381926c2a35efa9c40ba364e2ef43f6055ac8133dd5754d32d5478fb916aa580",
        "50f7565a6e8ef6e6ce7b92e730588b9f1d1ef334015a8cf50555a793ed7815a2",
        "526a54177bad1ec421ec319c031f6ba322fa431e7235cf35604e14d7ecf23f6c",
        "5cdcd5f0efd26e824c9c27f854d3feccca3be0018678602ef7882c30a5f645db",
        "7e2148763934669f62e9de52982a9e75746e9e118ccfad820afcfd7a9230e4d0",
        "85b2a1fd3938dee8a3a12f61397a07052883cd3f0bfa4d977151b600fe4992b6",
        "a42f6b7a15955e08e7ec4c63fd335b17634454e21ff34b02f07a2077bea67cdb",
        "bae0976d0412483f985d6ad1e828cf39f8e5df5c82bb6d1284183781c4ce64ea",
        "d7044e4303ac8a2a1b32e1fff471b06ddfa33fcee0258c3d1576ebcf2b352db9",
        "f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb",
        "ff671687b815e9647e7b1b0ead2edab5839422196dcdb150ae1de798b9cd6824",
        "65017fa4efd2c518f7f07dbdd12c332cb472b13ee6b734b69f4c9569aa445b7f",
    )
)


def saved_state_predecessor_is_compatible(
    predecessor: object,
    consumer: str,
    *,
    operation_id: str | None = None,
    serializer: str | None = None,
) -> bool:
    """Match one exact registration, without reverse or transitive inference.

    The artifact reader has an exact contract pair and serializer but no
    operation argument. That pair must resolve unambiguously to one operation.
    Operation-aware callers separately validate their closed serializer/state.
    """

    matches = [
        entry
        for entry in (
            *saved_state_compatibilities(),
            *_COMPONENT_EVIDENCE_PREDECESSORS,
            *_REFERENCE_QUALITY_PREDECESSORS,
            *_V061_REGRESSION_DIAGNOSTIC_PREDECESSORS,
            *_V061_PCA_PRESENTATION_PREDECESSORS,
            *_PCA_SIGNAL_CUSTODY_PREDECESSORS,
            *_PLSDA_LEGACY_ADMISSION_PREDECESSORS,
            *_CROSS_BLOCK_PLSDA_PREDECESSORS,
            *_GUI_SAMPLE_AUTHORITY_PREDECESSORS,
            *_SCIENTIFIC_AUTHORITY_PREDECESSORS,
            *_FEATURE_PRESENTATION_PREDECESSORS,
            *_DIAGNOSTIC_REFUSAL_PREDECESSORS,
            *_SCIENTIFIC_AUDIT_PREDECESSORS,
            *_WORKFLOW_POPULATION_PREDECESSORS,
            *_PCA_DISPLAY_INPUT_REUSE_PREDECESSORS,
            *_HANDOFF_PRESENTATION_PREDECESSORS,
            *_AUTOMATIC_PLS_APPLICATION_PREDECESSORS,
            *_PREPROCESSING_APPLICATION_PREDECESSORS,
            *_PLSDA_INDEPENDENCE_READERS,
            *_PLSDA_DIAGNOSTIC_IDENTITY_PREDECESSORS,
        )
        if entry.predecessor_digest == predecessor
        and entry.consumer_digest == consumer
        and (operation_id is None or entry.operation_id == operation_id)
        and (serializer is None or entry.serializer == serializer)
    ]
    return len(matches) == 1 and (operation_id is not None or serializer is not None)


def stateless_application_predecessor_is_compatible(operation: str, predecessor: object, consumer: str) -> bool:
    """Exact apply-only reader for unchanged stateless smoothing mathematics.

    Source-axis/display helpers changed the implementation closure. This is
    neither permission to replay historical fits nor a transitive alias.
    """
    return (operation, predecessor, consumer) == (
        "preprocess.smooth",
        "4d405cdbf887713619a462b33e9c941a62abcd281176f590415c46bf606507b6",
        "da86321ad34a334b778e3e3632e542fbfb6374f9283bd92c34657f1e79f1b490",
    )


def inspection_predecessor_catalog(profile_digest: str | None = None) -> dict:
    """Pinned read-only campaign profiles; not saved-state application aliases."""
    if profile_digest == "d82af6a5a5b9922b1c57531d3ce9d121ad6e7c6f80ee3dc6bb24119f6b2f24c9":
        raw = files("spectra_sherpa.core").joinpath("contract_predecessors_plsda_identity.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != "8180787692c1f5162a0e8b0077dca5cfc530bfc8b1bbf7babe0050936dd5364d":
            raise ValueError("trusted pre-diagnostic-identity inspection catalog digest mismatch")
        return json.loads(raw)
    if profile_digest == "a90673771ee6f54d95591e8eb9cd56470dca68dae5a319a58936552d77a96140":
        raw = files("spectra_sherpa.core").joinpath("contract_predecessors_preprocessing.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != "2396b86869d660efd2a0bea2899c231d3ee87300dc750afefee6f6997d05fb14":
            raise ValueError("trusted pre-preprocessing inspection catalog digest mismatch")
        return json.loads(raw)
    if profile_digest == "af74c1883601c4db7943953a864eb319794e19cebf5b303ef3f67ac858714336":
        raw = files("spectra_sherpa.core").joinpath("contract_predecessors_grouped_cv.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != "a3b95a3510226e94cdcee16b50c8eb729ec033c8893bf08711b0548cd59e7619":
            raise ValueError("trusted pre-grouped-CV inspection catalog digest mismatch")
        return json.loads(raw)
    if profile_digest == "eec02d6f13ac5b5fa1af45dfea754b0c054faf1c92d75cf9af88ec74ac066cdb":
        raw = files("spectra_sherpa.core").joinpath("contract_predecessors_staging_20261029.json").read_bytes()
        if hashlib.sha256(raw).hexdigest() != "193ec28fe2034d819b3e12c0d66d5fd7cf618cc50170fcf4facf89828076e641":
            raise ValueError("trusted pre-automatic PLS inspection catalog digest mismatch")
        return json.loads(raw)
    original = predecessor_catalog()
    if profile_digest is None or profile_digest == original["profile"]["profile_digest"]:
        return original
    raw = files("spectra_sherpa.core").joinpath("contract_predecessors_staging_20261011.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != "7bdcbdd1af0d6a86ba6eed4cefb4f0c7438f148c6f81bcdf8ec01e403ad2fc47":
        raise ValueError("trusted inspection predecessor catalog digest mismatch")
    catalog = json.loads(raw)
    if profile_digest != catalog["profile"]["profile_digest"]:
        raise ValueError("unrecognized historical inspection profile")
    return catalog
