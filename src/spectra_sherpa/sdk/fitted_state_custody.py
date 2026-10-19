"""Closed custody capabilities for fitted-state serializers.

Campaign Review Packages make a stronger claim than ordinary fitted-artifact
portability: their retained state must not contain calibration rows or an
external reference set.  Serializer identity is therefore admitted through
this positive authority.  A new or unknown serializer is never assumed safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Literal, Mapping

DATA_FREE_APPLICATION_STATE = "data_free_application_state"
RETAINS_TRAINING_ROWS = "retains_training_rows"

FittedStateCustodyClass = Literal[
    "data_free_application_state",
    "retains_training_rows",
]


class FittedStateCustodyError(ValueError):
    """A fitted-state serializer has no admissible export-custody authority."""


@dataclass(frozen=True)
class FittedStateCustodyCapability:
    """One exact serializer-and-contract custody classification."""

    serializer: str
    contract_digest: str
    custody_class: FittedStateCustodyClass
    rationale: str


_CAPABILITIES: Mapping[tuple[str, str], FittedStateCustodyCapability] = MappingProxyType(
    {
        (
            "spectrasherpa.model-artifact.pca/3",
            "5e809716a8266c4ddd5fb3902b8a68c264019fd05237bdb1397f664ae31dea10",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.pca/3",
            contract_digest="5e809716a8266c4ddd5fb3902b8a68c264019fd05237bdb1397f664ae31dea10",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Identity binding changed; fitted serialization and training-row custody are unchanged.",
        ),
        (
            "spectrasherpa.sherpa-plsda-state/5",
            "7e2148763934669f62e9de52982a9e75746e9e118ccfad820afcfd7a9230e4d0",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.sherpa-plsda-state/5",
            contract_digest="7e2148763934669f62e9de52982a9e75746e9e118ccfad820afcfd7a9230e4d0",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Identity binding changed; fitted serialization and training-row custody are unchanged.",
        ),
        (
            "spectrasherpa.model-artifact.simca/2",
            "16dfeba33f742c80aad2e8ae2dcccb42d430215b20b2fdfb77179f821db52034",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.simca/2",
            contract_digest="16dfeba33f742c80aad2e8ae2dcccb42d430215b20b2fdfb77179f821db52034",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Identity binding changed; fitted serialization and training-row custody are unchanged.",
        ),
        (
            "spectrasherpa.model-artifact.knn/2",
            "8acc66bc0b248e2ebfbd89f041dd0513b3505740fa5a2b5e3b4dbccba81f1206",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.knn/2",
            contract_digest="8acc66bc0b248e2ebfbd89f041dd0513b3505740fa5a2b5e3b4dbccba81f1206",
            custody_class=RETAINS_TRAINING_ROWS,
            rationale="Identity binding changed; fitted serialization and training-row custody are unchanged.",
        ),
        (
            "spectrasherpa.model-artifact.parafac/2",
            "caa04a3f25923cfc7d83fe38defd47db25fcb10be1375d51d516ebc82b544ac0",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.parafac/2",
            contract_digest="caa04a3f25923cfc7d83fe38defd47db25fcb10be1375d51d516ebc82b544ac0",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Identity binding changed; fitted serialization and training-row custody are unchanged.",
        ),
        (
            "spectrasherpa.model-artifact.pca/3",
            "eeca5bea6642ec33c4a51c825acd58217d1a8c17784cfa318e4840e4c4ba73a9",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.pca/3",
            contract_digest="eeca5bea6642ec33c4a51c825acd58217d1a8c17784cfa318e4840e4c4ba73a9",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Shared SDK sample helpers changed; portable PCA state and training-row custody are unchanged.",
        ),
        (
            "spectrasherpa.sherpa-plsda-state/5",
            "d7044e4303ac8a2a1b32e1fff471b06ddfa33fcee0258c3d1576ebcf2b352db9",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.sherpa-plsda-state/5",
            contract_digest="d7044e4303ac8a2a1b32e1fff471b06ddfa33fcee0258c3d1576ebcf2b352db9",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Shared SDK sample helpers changed; PLS-DA state still contains no calibration rows.",
        ),
        (
            "spectrasherpa.model-artifact.simca/2",
            "fb0f84fec93cc374fbdd00797ea361f8c9a83d22b6021f242815b4e83cecc0f0",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.simca/2",
            contract_digest="fb0f84fec93cc374fbdd00797ea361f8c9a83d22b6021f242815b4e83cecc0f0",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Shared SDK sample helpers changed; SIMCA fitted-state custody is unchanged.",
        ),
        (
            "spectrasherpa.model.kmeans-state/1",
            "c65f7f11e6d2089abdec190e2c7aee80088eed4f2545ce55c0b92db1b2ebef30",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.kmeans-state/1",
            contract_digest="c65f7f11e6d2089abdec190e2c7aee80088eed4f2545ce55c0b92db1b2ebef30",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Axis presentation metadata does not add calibration rows to K-means state.",
        ),
        (
            "spectrasherpa.model-artifact.parafac/2",
            "3c1525353cb993b328366260f5b751a2275048e2c39322ca424a91692ad24f68",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.parafac/2",
            contract_digest="3c1525353cb993b328366260f5b751a2275048e2c39322ca424a91692ad24f68",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Shared SDK sample helpers changed; PARAFAC fitted-state custody is unchanged.",
        ),
        (
            "spectrasherpa.model-artifact.knn/2",
            "7f188a7485c4774ccaa67d7efcf0cd95e35c07682633e9b5265d48f5e568be92",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.knn/2",
            contract_digest="7f188a7485c4774ccaa67d7efcf0cd95e35c07682633e9b5265d48f5e568be92",
            custody_class=RETAINS_TRAINING_ROWS,
            rationale="Correcting the displayed distance space does not remove KNN's retained calibration rows.",
        ),
        (
            "spectrasherpa.model.fitted_pcr/1",
            "7f6040c174cae2889250e6a4bc22620af172207109a1d6ff0fe66ad35937f9de",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_pcr/1",
            contract_digest="7f6040c174cae2889250e6a4bc22620af172207109a1d6ff0fe66ad35937f9de",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="MLR effect presentation changes the shared source fingerprint, not PCR fitted-state custody.",
        ),
        (
            "spectrasherpa.model.fitted_svr/1",
            "6015b47482335d0931239f6a52fea6825979c43c055e319c69deb3129b344c67",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_svr/1",
            contract_digest="6015b47482335d0931239f6a52fea6825979c43c055e319c69deb3129b344c67",
            custody_class=RETAINS_TRAINING_ROWS,
            rationale=(
                "MLR effect presentation changes the shared source fingerprint; " "SVR still retains support vectors."
            ),
        ),
        (
            "spectrasherpa.model.fitted_linear_regression/1",
            "63501135129058b92cd8b6d0db33d5d61d3407c0be4f25a53f984d4a0101e27a",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_linear_regression/1",
            contract_digest="63501135129058b92cd8b6d0db33d5d61d3407c0be4f25a53f984d4a0101e27a",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="MLR effect presentation changes the shared source fingerprint, not fitted-state row custody.",
        ),
        (
            "spectrasherpa.model.fitted_pcr/1",
            "18c724b705c6c1331a82a45e7c4f7c2c8a6c4b91fb375385e3e146f3f39b9b11",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_pcr/1",
            contract_digest="18c724b705c6c1331a82a45e7c4f7c2c8a6c4b91fb375385e3e146f3f39b9b11",
            custody_class="data_free_application_state",
            rationale="The revised regression diagnostics do not retain calibration rows in PCR fitted state.",
        ),
        (
            "spectrasherpa.model.fitted_svr/1",
            "f69be607b175147534980ea0afe932a6af4a846b2734d121dc76c9dceed65843",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_svr/1",
            contract_digest="f69be607b175147534980ea0afe932a6af4a846b2734d121dc76c9dceed65843",
            custody_class="retains_training_rows",
            rationale="SVR support vectors remain calibration rows after the diagnostic revision.",
        ),
        (
            "spectrasherpa.model.fitted_linear_regression/1",
            "d4be993d68d26c1c38e6c09115713fe8111bf5f4ba559f75e9e8dc7d03c86e0e",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_linear_regression/1",
            contract_digest="d4be993d68d26c1c38e6c09115713fe8111bf5f4ba559f75e9e8dc7d03c86e0e",
            custody_class="data_free_application_state",
            rationale="The revised regression diagnostics do not retain calibration rows in linear fitted state.",
        ),
        (
            "spectra.sherpa-simpls-regression-json/9",
            "3939dc715653c735c11d3993942bd8e8baf5343fd42e21341d5cde130dafdde3",
        ): FittedStateCustodyCapability(
            serializer="spectra.sherpa-simpls-regression-json/9",
            contract_digest="3939dc715653c735c11d3993942bd8e8baf5343fd42e21341d5cde130dafdde3",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale=(
                "Reference-value evidence is separate from the closed PLS fitted-state bytes; "
                "no training rows were added."
            ),
        ),
        (
            "spectrasherpa.sherpa-plsda-state/5",
            "a42f6b7a15955e08e7ec4c63fd335b17634454e21ff34b02f07a2077bea67cdb",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.sherpa-plsda-state/5",
            contract_digest="a42f6b7a15955e08e7ec4c63fd335b17634454e21ff34b02f07a2077bea67cdb",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale=(
                "Legacy application admission changes the shared module identity; "
                "the native closed fitted-state schema and absence of training rows are unchanged."
            ),
        ),
        (
            "spectrasherpa.sherpa-plsda-state/5",
            "5cdcd5f0efd26e824c9c27f854d3feccca3be0018678602ef7882c30a5f645db",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.sherpa-plsda-state/5",
            contract_digest="5cdcd5f0efd26e824c9c27f854d3feccca3be0018678602ef7882c30a5f645db",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale=(
                "Explicit cross-block split planning changes the shared dependency fingerprint, "
                "not PLS-DA fitted state."
            ),
        ),
        (
            "spectrasherpa.sherpa-plsda-state/5",
            "bae0976d0412483f985d6ad1e828cf39f8e5df5c82bb6d1284183781c4ce64ea",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.sherpa-plsda-state/5",
            contract_digest="bae0976d0412483f985d6ad1e828cf39f8e5df5c82bb6d1284183781c4ce64ea",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale=(
                "Reference-value evidence is separate from the closed PLS-DA fitted-state bytes; "
                "no training rows were added."
            ),
        ),
        (
            "spectrasherpa.model.fitted_pcr/1",
            "b0b7e0e32445d63b864b27cc16a6831b9561a35a3614efd19220343902c45b3f",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_pcr/1",
            contract_digest="b0b7e0e32445d63b864b27cc16a6831b9561a35a3614efd19220343902c45b3f",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Shared modeling source fingerprint changed; PCR fitted-state rows and custody are unchanged.",
        ),
        (
            "spectrasherpa.model.fitted_svr/1",
            "321d4a0411f164d20a3904dc438d886b1fb807c19200a2bb640ceaeb6169fc24",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_svr/1",
            contract_digest="321d4a0411f164d20a3904dc438d886b1fb807c19200a2bb640ceaeb6169fc24",
            custody_class=RETAINS_TRAINING_ROWS,
            rationale="Shared modeling source fingerprint changed; SVR still retains support-vector calibration rows.",
        ),
        (
            "spectrasherpa.model.fitted_linear_regression/1",
            "19380f7cbefd4bd7196649760982a8d473d4062d86bfe6f8fdbef24dea042f53",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_linear_regression/1",
            contract_digest="19380f7cbefd4bd7196649760982a8d473d4062d86bfe6f8fdbef24dea042f53",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Shared modeling source fingerprint changed; linear fitted-state rows and custody are unchanged.",
        ),
        (
            "spectra.sherpa-simpls-regression-json/9",
            "9db6a10ca3c53faf7b0a69cee4aba35ebef148019ca21bf09ed226d578456997",
        ): FittedStateCustodyCapability(
            serializer="spectra.sherpa-simpls-regression-json/9",
            contract_digest="9db6a10ca3c53faf7b0a69cee4aba35ebef148019ca21bf09ed226d578456997",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Component evidence adds an output; the closed PLS fitted state remains data-free.",
        ),
        (
            "spectrasherpa.sherpa-plsda-state/5",
            "00d9f4d468b96d949d1941e902bb8af727a16e22dc83cea93f22912a38fa3603",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.sherpa-plsda-state/5",
            contract_digest="00d9f4d468b96d949d1941e902bb8af727a16e22dc83cea93f22912a38fa3603",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Component evidence adds an output; the closed PLS-DA fitted state remains data-free.",
        ),
        (
            "spectrasherpa.sherpa-plsda-state/5",
            "381926c2a35efa9c40ba364e2ef43f6055ac8133dd5754d32d5478fb916aa580",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.sherpa-plsda-state/5",
            contract_digest="381926c2a35efa9c40ba364e2ef43f6055ac8133dd5754d32d5478fb916aa580",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Sample diagnostic output adds a receipt; the closed PLS-DA fitted state remains data-free.",
        ),
        (
            "spectrasherpa.model.fitted_pcr/1",
            "7a58390a7bfb79ed0e7920dae41c2de5a3d8c6d8ca323754c3000fb9cd6cf4a4",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_pcr/1",
            contract_digest="7a58390a7bfb79ed0e7920dae41c2de5a3d8c6d8ca323754c3000fb9cd6cf4a4",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Shared source fingerprint changed; PCR fitted-state bytes and row custody did not.",
        ),
        (
            "spectrasherpa.model.fitted_svr/1",
            "d3c36c524644edab0a1076190155baad4340ab549e34fc7a0e67b38f2d4f0a83",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_svr/1",
            contract_digest="d3c36c524644edab0a1076190155baad4340ab549e34fc7a0e67b38f2d4f0a83",
            custody_class=RETAINS_TRAINING_ROWS,
            rationale="Shared source fingerprint changed; SVR still retains support-vector calibration rows.",
        ),
        (
            "spectrasherpa.model.fitted_linear_regression/1",
            "a9c2343c3eb8cec79c5e25f14bf57a7793b7bbc7449eba0bc8249ad839c4463b",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_linear_regression/1",
            contract_digest="a9c2343c3eb8cec79c5e25f14bf57a7793b7bbc7449eba0bc8249ad839c4463b",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Shared source fingerprint changed; linear fitted-state bytes and row custody did not.",
        ),
        (
            "spectra.sherpa-simpls-regression-json/9",
            "3543ba77a37677b1b5446a1fa3ff8e012cbfed71a7f6bbb75edf0ca89cbceef4",
        ): FittedStateCustodyCapability(
            serializer="spectra.sherpa-simpls-regression-json/9",
            contract_digest="3543ba77a37677b1b5446a1fa3ff8e012cbfed71a7f6bbb75edf0ca89cbceef4",
            custody_class="data_free_application_state",
            rationale="Scientific correctness fixes preserve this operation's training-row custody.",
        ),
        (
            "spectra.sherpa-simpls-regression-json/9",
            "811429fa6cfba18edfbda6c7a54d7078b0b744f82eba13de39c75efaad647f40",
        ): FittedStateCustodyCapability(
            serializer="spectra.sherpa-simpls-regression-json/9",
            contract_digest="811429fa6cfba18edfbda6c7a54d7078b0b744f82eba13de39c75efaad647f40",
            custody_class="data_free_application_state",
            rationale="Scientific correctness fixes preserve this operation's training-row custody.",
        ),
        (
            "spectrasherpa.model.fitted_pcr/1",
            "a207b7fc520763105b633ca6d99eb267872c38ed54dc6854082b7be1bd1756b8",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_pcr/1",
            contract_digest="a207b7fc520763105b633ca6d99eb267872c38ed54dc6854082b7be1bd1756b8",
            custody_class="data_free_application_state",
            rationale="Scientific correctness fixes preserve this operation's training-row custody.",
        ),
        (
            "spectrasherpa.model.fitted_svr/1",
            "29942ded909354f2ef273444108c7feb54525539ca8a24f091d7be9e3136decb",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_svr/1",
            contract_digest="29942ded909354f2ef273444108c7feb54525539ca8a24f091d7be9e3136decb",
            custody_class="retains_training_rows",
            rationale="Scientific correctness fixes preserve this operation's training-row custody.",
        ),
        (
            "spectrasherpa.model.fitted_linear_regression/1",
            "04d5ea448432137158df7b412286a17a5fe3498f5589ce53b33414fad2388b2b",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_linear_regression/1",
            contract_digest="04d5ea448432137158df7b412286a17a5fe3498f5589ce53b33414fad2388b2b",
            custody_class="data_free_application_state",
            rationale="Scientific correctness fixes preserve this operation's training-row custody.",
        ),
        (
            "spectrasherpa.model.fitted_pcr/1",
            "1aecb57326c2c3a8f71823a035cbcb2f21be34d72a3049daedcc5e67a399f2e9",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_pcr/1",
            contract_digest="1aecb57326c2c3a8f71823a035cbcb2f21be34d72a3049daedcc5e67a399f2e9",
            custody_class="data_free_application_state",
            rationale="Scientific correctness fixes preserve this operation's training-row custody.",
        ),
        (
            "spectrasherpa.model.fitted_svr/1",
            "244fe3defede23aefb869e74d97034600b1a73c9abb63694fb6101ed2fea9c34",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_svr/1",
            contract_digest="244fe3defede23aefb869e74d97034600b1a73c9abb63694fb6101ed2fea9c34",
            custody_class="retains_training_rows",
            rationale="Scientific correctness fixes preserve this operation's training-row custody.",
        ),
        (
            "spectrasherpa.model.fitted_linear_regression/1",
            "9c43658d5b6ac5f8848979832e2eed47f573bb5598ccbe2f882727f7720ed379",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_linear_regression/1",
            contract_digest="9c43658d5b6ac5f8848979832e2eed47f573bb5598ccbe2f882727f7720ed379",
            custody_class="data_free_application_state",
            rationale="Scientific correctness fixes preserve this operation's training-row custody.",
        ),
        (
            "spectra.scale-reference-json.v2",
            "cbe147638d9ba374a04f1f333fb50c81e3cc031c3a62046012c979f0ec2472d7",
        ): FittedStateCustodyCapability(
            serializer="spectra.scale-reference-json.v2",
            contract_digest="cbe147638d9ba374a04f1f333fb50c81e3cc031c3a62046012c979f0ec2472d7",
            custody_class="data_free_application_state",
            rationale="Scientific correctness fixes preserve this operation's training-row custody.",
        ),
        (
            "spectra.scale-reference-json.v2",
            "12bdd8dba156c6af1c94b3ff71b2285673389deabd796677202dd9182457d137",
        ): FittedStateCustodyCapability(
            serializer="spectra.scale-reference-json.v2",
            contract_digest="12bdd8dba156c6af1c94b3ff71b2285673389deabd796677202dd9182457d137",
            custody_class="data_free_application_state",
            rationale="Scientific correctness fixes preserve this operation's training-row custody.",
        ),
        (
            "spectrasherpa.model-artifact.knn/2",
            "b75296b1e07af53623dfaf5e859b759d089eb1b4145a415bc555ff59cf4fec8a",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.knn/2",
            contract_digest="b75296b1e07af53623dfaf5e859b759d089eb1b4145a415bc555ff59cf4fec8a",
            custody_class="retains_training_rows",
            rationale="Scientific correctness fixes preserve this operation's training-row custody.",
        ),
        (
            "spectrasherpa.model-artifact.simca/2",
            "58ae844cdcd14833a6da09a7f658e979ed08d812fc5bed7ef9d230be6e79d72e",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.simca/2",
            contract_digest="58ae844cdcd14833a6da09a7f658e979ed08d812fc5bed7ef9d230be6e79d72e",
            custody_class="data_free_application_state",
            rationale="Scientific correctness fixes preserve this operation's training-row custody.",
        ),
        (
            "spectrasherpa.model-artifact.knn/2",
            "9757abd08095faf85af7acc8772a7d0b8392fc343c4665d94cf73cf9a3114207",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.knn/2",
            contract_digest="9757abd08095faf85af7acc8772a7d0b8392fc343c4665d94cf73cf9a3114207",
            custody_class="retains_training_rows",
            rationale="Scientific correctness fixes preserve this operation's training-row custody.",
        ),
        (
            "spectrasherpa.sherpa-plsda-state/5",
            "5d9c5f8372b5f7647ba2b14abfeee99883572f383e8d8ecb2383baa965e5d22c",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.sherpa-plsda-state/5",
            contract_digest="5d9c5f8372b5f7647ba2b14abfeee99883572f383e8d8ecb2383baa965e5d22c",
            custody_class="data_free_application_state",
            rationale="Scientific correctness fixes preserve this operation's training-row custody.",
        ),
        (
            "spectrasherpa.model-artifact.simca/2",
            "a6223a163b130177257bcacf0ee4bf0a8387b285937bfae80c057afcfa4e5fa5",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.simca/2",
            contract_digest="a6223a163b130177257bcacf0ee4bf0a8387b285937bfae80c057afcfa4e5fa5",
            custody_class="data_free_application_state",
            rationale="Scientific correctness fixes preserve this operation's training-row custody.",
        ),
        (
            "spectrasherpa.sherpa-plsda-state/5",
            "f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.sherpa-plsda-state/5",
            contract_digest="f691b98c691e207f7e3e1d2eed74e0236212465646e244c8c5dff9593254e6eb",
            custody_class="data_free_application_state",
            rationale="Scientific correctness fixes preserve this operation's training-row custody.",
        ),
        (
            "spectra.sherpa-simpls-regression-json/9",
            "d16ff1db7d4b2b04d542bb170328f96ba8792c28509e0a77d1b7afe1a27484c0",
        ): FittedStateCustodyCapability(
            serializer="spectra.sherpa-simpls-regression-json/9",
            contract_digest="d16ff1db7d4b2b04d542bb170328f96ba8792c28509e0a77d1b7afe1a27484c0",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Native admission extraction preserves fitted serialization and training-row custody.",
        ),
        (
            "spectrasherpa.model.fitted_pcr/1",
            "f333f49d9791790f0713fbc18a97d046047dec80be538548df4ac887be7831cd",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_pcr/1",
            contract_digest="f333f49d9791790f0713fbc18a97d046047dec80be538548df4ac887be7831cd",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Native admission extraction preserves fitted serialization and training-row custody.",
        ),
        (
            "spectrasherpa.model.fitted_svr/1",
            "ffc885761a0195064821e9a02dc0189cc1c90344d6ff022cd91d473298e51205",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_svr/1",
            contract_digest="ffc885761a0195064821e9a02dc0189cc1c90344d6ff022cd91d473298e51205",
            custody_class=RETAINS_TRAINING_ROWS,
            rationale="Native admission extraction preserves fitted serialization and training-row custody.",
        ),
        (
            "spectrasherpa.model.fitted_linear_regression/1",
            "a9e3e8ccb5a2033be36d6691cb39a7ff2d2b5d28c821afbf91898e216fdff7ec",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_linear_regression/1",
            contract_digest="a9e3e8ccb5a2033be36d6691cb39a7ff2d2b5d28c821afbf91898e216fdff7ec",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Native admission extraction preserves fitted serialization and training-row custody.",
        ),
        (
            "spectrasherpa.model.fitted_pcr/1",
            "905cef6cd41f355e0f9a8e6847a03377f4de3c62c262aa8ce718055124b44cb6",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_pcr/1",
            contract_digest="905cef6cd41f355e0f9a8e6847a03377f4de3c62c262aa8ce718055124b44cb6",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Core trainer gains portable prediction output; fold-local state and row custody are unchanged.",
        ),
        (
            "spectrasherpa.model.fitted_svr/1",
            "0daa0a05e555974ab7810bc97ddecc09abb00c24f7b5f6014be8a99aaee1b97b",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_svr/1",
            contract_digest="0daa0a05e555974ab7810bc97ddecc09abb00c24f7b5f6014be8a99aaee1b97b",
            custody_class=RETAINS_TRAINING_ROWS,
            rationale="Core trainer gains portable prediction output; fold-local state and row custody are unchanged.",
        ),
        (
            "spectrasherpa.model.fitted_linear_regression/1",
            "29ba32c09e04d094afdc28724b86615a0d77e3946c3990f5f181a539ca8eff6c",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_linear_regression/1",
            contract_digest="29ba32c09e04d094afdc28724b86615a0d77e3946c3990f5f181a539ca8eff6c",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Core trainer gains portable prediction output; fold-local state and row custody are unchanged.",
        ),
        (
            "spectra.sherpa-simpls-regression-json/9",
            "5ae3215d3c522a75b16baecdf35e736537052f411fbf9833509a535320ee27d5",
        ): FittedStateCustodyCapability(
            serializer="spectra.sherpa-simpls-regression-json/9",
            contract_digest="5ae3215d3c522a75b16baecdf35e736537052f411fbf9833509a535320ee27d5",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Saved-model persistence added; the fitted-state payload and training-row custody are unchanged.",
        ),
        (
            "spectrasherpa.model.fitted_pcr/1",
            "a019c82f84b92f636a2daa74cc2426583e4b3f29e6f71e93d3627a28ce690a3d",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_pcr/1",
            contract_digest="a019c82f84b92f636a2daa74cc2426583e4b3f29e6f71e93d3627a28ce690a3d",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Saved-model persistence added; the fitted-state payload and training-row custody are unchanged.",
        ),
        (
            "spectrasherpa.model.fitted_svr/1",
            "56183da23cf622776632f655d390ce655e9fe2bde03c850d309ca52413967f2b",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_svr/1",
            contract_digest="56183da23cf622776632f655d390ce655e9fe2bde03c850d309ca52413967f2b",
            custody_class=RETAINS_TRAINING_ROWS,
            rationale="Saved-model persistence added; the fitted-state payload and training-row custody are unchanged.",
        ),
        (
            "spectrasherpa.model.fitted_linear_regression/1",
            "f37079ea8dd6a263d3a6c922ed17413999841da88a29c5ae84d97874d60ee934",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_linear_regression/1",
            contract_digest="f37079ea8dd6a263d3a6c922ed17413999841da88a29c5ae84d97874d60ee934",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Saved-model persistence added; the fitted-state payload and training-row custody are unchanged.",
        ),
        (
            "spectrasherpa.model.fitted_pcr/1",
            "fde32b57715a15a7b83d455eb82ca5a003ec30b788fbcc415fda43d771dbda99",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_pcr/1",
            contract_digest="fde32b57715a15a7b83d455eb82ca5a003ec30b788fbcc415fda43d771dbda99",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Scientific citations added; numerical serialization and custody are unchanged.",
        ),
        (
            "spectrasherpa.model.fitted_svr/1",
            "66afa7c1f031c28ebaf27b7138fc1ab1cf0b68e6d925bb745be7a4399033836d",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_svr/1",
            contract_digest="66afa7c1f031c28ebaf27b7138fc1ab1cf0b68e6d925bb745be7a4399033836d",
            custody_class=RETAINS_TRAINING_ROWS,
            rationale="Scientific citations added; numerical serialization and custody are unchanged.",
        ),
        (
            "spectrasherpa.model.fitted_linear_regression/1",
            "31d6f3ada847a716c83a0ee2b5dc9374c5ed206a60b1d67e12be441484be6a12",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_linear_regression/1",
            contract_digest="31d6f3ada847a716c83a0ee2b5dc9374c5ed206a60b1d67e12be441484be6a12",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Scientific citations added; numerical serialization and custody are unchanged.",
        ),
        (
            "spectrasherpa.model.fitted_pcr/1",
            "06770b660de2463e11d6c830d07ef06337aba50f8aef5a87e7324d1cfce1b9ea",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_pcr/1",
            contract_digest="06770b660de2463e11d6c830d07ef06337aba50f8aef5a87e7324d1cfce1b9ea",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="PCR retains PCA components, centering/scaling and regression coefficients, not calibration rows",
        ),
        (
            "spectrasherpa.model.fitted_linear_regression/1",
            "2d95c81f4f99e3be1910c9c5fb72b2231234331fdae56141c5ad78dbb35e6377",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_linear_regression/1",
            contract_digest="2d95c81f4f99e3be1910c9c5fb72b2231234331fdae56141c5ad78dbb35e6377",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Linear regression retains coefficients and intercepts with input identity, not calibration rows",
        ),
        (
            "spectrasherpa.model.fitted_svr/1",
            "76b39a2497dbf961d670ef82b2b66050bc9bd7004588f2610a615c5b48fb0032",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model.fitted_svr/1",
            contract_digest="76b39a2497dbf961d670ef82b2b66050bc9bd7004588f2610a615c5b48fb0032",
            custody_class=RETAINS_TRAINING_ROWS,
            rationale="SVR retains support vectors drawn from calibration rows, including for linear kernels",
        ),
        (
            "spectra.sherpa-simpls-regression-json/9",
            "cd6f36f04bb4d0244bbc560f653fedf306a1fa6cc1645cd888f99d2a9170c89e",
        ): FittedStateCustodyCapability(
            serializer="spectra.sherpa-simpls-regression-json/9",
            contract_digest="cd6f36f04bb4d0244bbc560f653fedf306a1fa6cc1645cd888f99d2a9170c89e",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale=(
                "Regression comparison now emits aggregate report statistics; fitted serialization is unchanged. "
                "SIMPLS parameters and aggregate global screening state retain no calibration rows"
            ),
        ),
        (
            "spectrasherpa.sherpa-plsda-state/4",
            "1875107445c8954ec79270de2b84c80507665cd069ea4558a9068fb2866c9cf7",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.sherpa-plsda-state/4",
            contract_digest="1875107445c8954ec79270de2b84c80507665cd069ea4558a9068fb2866c9cf7",
            custody_class="data_free_application_state",
            rationale=(
                "Shared IO regression admission changed; classifier serializer unchanged. "
                "PLS-DA retains parameters and label domain only"
            ),
        ),
        (
            "spectrasherpa.model-artifact.simca/1",
            "fcf0e470363f4723d5c9f7d23e3323575a12ee85d56c085f066340b565182d72",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.simca/1",
            contract_digest="fcf0e470363f4723d5c9f7d23e3323575a12ee85d56c085f066340b565182d72",
            custody_class="data_free_application_state",
            rationale="Shared legacy PLS diagnostics changed; classifier numerical state and custody unchanged",
        ),
        (
            "spectrasherpa.model-artifact.simca/1",
            "421693abf8df317b9f5785fd3a470f575b6820b416f65990932e53e7d6c17279",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.simca/1",
            contract_digest="421693abf8df317b9f5785fd3a470f575b6820b416f65990932e53e7d6c17279",
            custody_class="data_free_application_state",
            rationale=(
                "Shared IO regression admission changed; classifier serializer unchanged. "
                "SIMCA retains class PCA parameters and aggregate evidence only"
            ),
        ),
        (
            "spectrasherpa.model-artifact.knn/1",
            "8cab952a6aa59bf4e90b8037514c668a5e4318a017f6a98f870ffd1a77c8850a",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.knn/1",
            contract_digest="8cab952a6aa59bf4e90b8037514c668a5e4318a017f6a98f870ffd1a77c8850a",
            custody_class="retains_training_rows",
            rationale="Shared legacy PLS diagnostics changed; classifier numerical state and custody unchanged",
        ),
        (
            "spectrasherpa.model-artifact.knn/1",
            "05ea0a22cae184b9c3bfd88be0eb7d83a7a955c009c2190169402a7a2dc10045",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.knn/1",
            contract_digest="05ea0a22cae184b9c3bfd88be0eb7d83a7a955c009c2190169402a7a2dc10045",
            custody_class="retains_training_rows",
            rationale=(
                "Shared IO regression admission changed; classifier serializer unchanged. "
                "KNN retains calibration rows"
            ),
        ),
        (
            "spectra.sherpa-simpls-regression-json/9",
            "a8cf9a42253af99c22a809abc5d6bf68e65fc534c3e7b7396b68a5ffb30f7fa7",
        ): FittedStateCustodyCapability(
            serializer="spectra.sherpa-simpls-regression-json/9",
            contract_digest="a8cf9a42253af99c22a809abc5d6bf68e65fc534c3e7b7396b68a5ffb30f7fa7",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="SIMPLS parameters and aggregate global screening state retain no calibration rows",
        ),
        (
            "spectra.sherpa-simpls-regression-json/8",
            "75fcbf2b46cff25633ad07fa3e3f4778fc15e6c30d8e5f61ef7b344230ea8292",
        ): FittedStateCustodyCapability(
            serializer="spectra.sherpa-simpls-regression-json/8",
            contract_digest="75fcbf2b46cff25633ad07fa3e3f4778fc15e6c30d8e5f61ef7b344230ea8292",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="PLS affine response parameters and fitted input identity retain no calibration rows",
        ),
        (
            "spectra.scale-reference-json.v2",
            "15bce0eb5aa942173878a911a7eba23cd3638f59fe37aa3c0e54f90506ff7e91",
        ): FittedStateCustodyCapability(
            serializer="spectra.scale-reference-json.v2",
            contract_digest="15bce0eb5aa942173878a911a7eba23cd3638f59fe37aa3c0e54f90506ff7e91",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="Scaling means, scales and feature/signal identity retain no reference rows",
        ),
        (
            "spectra.sherpa-simpls-regression-json/7",
            "9b9fd76ac7bb6d590a396a501562f1fbb98a712e1c9304937decf13a47585366",
        ): FittedStateCustodyCapability(
            serializer="spectra.sherpa-simpls-regression-json/7",
            contract_digest="9b9fd76ac7bb6d590a396a501562f1fbb98a712e1c9304937decf13a47585366",
            custody_class="data_free_application_state",
            rationale="PLS affine parameters retain response names and units; no calibration rows",
        ),
        (
            "spectrasherpa.sherpa-plsda-state/4",
            "b4d139dcab92de615964223c89ca547076fcf5a5ae84e11c1c54c8a345096e8a",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.sherpa-plsda-state/4",
            contract_digest="b4d139dcab92de615964223c89ca547076fcf5a5ae84e11c1c54c8a345096e8a",
            custody_class="data_free_application_state",
            rationale=(
                "Sample identity checked before binding; fitted serialization unchanged. "
                "PLS-DA retains feature identity and label-domain parameters without calibration rows"
            ),
        ),
        (
            "spectrasherpa.model-artifact.simca/1",
            "d844f321781da653672f5a0cc78c424b68f018b42af281ddcc8e034c1c174e49",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.simca/1",
            contract_digest="d844f321781da653672f5a0cc78c424b68f018b42af281ddcc8e034c1c174e49",
            custody_class="data_free_application_state",
            rationale=(
                "Sample identity checked before binding; fitted serialization unchanged. "
                "SIMCA retains PCA parameters, limits and aggregate applicability evidence without calibration rows"
            ),
        ),
        (
            "spectrasherpa.model-artifact.knn/1",
            "87ef00dfc10b7ab37d577992eec02758f81cce2650094ff860a4467f09ece3d4",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.knn/1",
            contract_digest="87ef00dfc10b7ab37d577992eec02758f81cce2650094ff860a4467f09ece3d4",
            custody_class="retains_training_rows",
            rationale=(
                "Sample identity checked before binding; fitted serialization unchanged. "
                "KNN application requires the complete calibration matrix and encoded labels"
            ),
        ),
        (
            "spectra.sherpa-simpls-regression-json/6",
            "87a0e85157f008126f53af7f8945c7e730535431f866df628e9a226532440ff6",
        ): FittedStateCustodyCapability(
            serializer="spectra.sherpa-simpls-regression-json/6",
            contract_digest="87a0e85157f008126f53af7f8945c7e730535431f866df628e9a226532440ff6",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale=(
                "comparison presentation admits unqualified evaluation; fitted PLS state remains "
                "affine parameters and feature metadata without calibration rows"
            ),
        ),
        (
            "spectrasherpa.sherpa-plsda-state/4",
            "5f8d08918a1132a16aef3fe5fa82f499b74e12f6d26abccc29f9a48003cabc0a",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.sherpa-plsda-state/4",
            contract_digest="5f8d08918a1132a16aef3fe5fa82f499b74e12f6d26abccc29f9a48003cabc0a",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale=(
                "affine PLS-DA state retains explicit feature identity mode and parameters " "but no calibration rows"
            ),
        ),
        (
            "spectrasherpa.sherpa-plsda-state/4",
            "7b0a2802ab9118f9c63ef596ff99763387b0da4354d77b4e0f59631ea4de123e",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.sherpa-plsda-state/4",
            contract_digest="7b0a2802ab9118f9c63ef596ff99763387b0da4354d77b4e0f59631ea4de123e",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale=(
                "affine PLS-DA state retains explicit feature identity and label-domain parameters "
                "but no calibration rows"
            ),
        ),
        (
            "spectrasherpa.sherpa-plsda-state/3",
            "49a4a9501c6000c046e2eec3b777ff7b8b0d12d6d229bd8fa03532696e3308c6",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.sherpa-plsda-state/3",
            contract_digest="49a4a9501c6000c046e2eec3b777ff7b8b0d12d6d229bd8fa03532696e3308c6",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="affine PLS-DA state retains parameters and class labels but no calibration rows",
        ),
        (
            "spectrasherpa.sherpa-plsda-state/3",
            "76adfad2282f7ea1a6ac883750d45f972706364fcc0b930bbaccefae2d3c3739",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.sherpa-plsda-state/3",
            contract_digest="76adfad2282f7ea1a6ac883750d45f972706364fcc0b930bbaccefae2d3c3739",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="affine PLS-DA state retains parameters and class labels but no calibration rows",
        ),
        (
            "spectrasherpa.sherpa-plsda-state/3",
            "ca9c6b12e262b56fadb1f6d829ef94b6302b680a9b4df80211ee352081d3399e",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.sherpa-plsda-state/3",
            contract_digest="ca9c6b12e262b56fadb1f6d829ef94b6302b680a9b4df80211ee352081d3399e",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="affine PLS-DA state retains parameters and class labels but no calibration rows",
        ),
        (
            "spectrasherpa.model-artifact.simca/1",
            "477a766a66e00634bbc22a5809ffd4e445e9e87099b3f8b6e4bd2208f138e4f8",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.simca/1",
            contract_digest="477a766a66e00634bbc22a5809ffd4e445e9e87099b3f8b6e4bd2208f138e4f8",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="SIMCA state retains class PCA parameters and limits but no calibration rows",
        ),
        (
            "spectrasherpa.model-artifact.simca/1",
            "ed4a72520c738fbecb4c60eea187649ad6fd903635c92ab8f38a7afe1e428199",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.simca/1",
            contract_digest="ed4a72520c738fbecb4c60eea187649ad6fd903635c92ab8f38a7afe1e428199",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="SIMCA state retains class PCA parameters and limits but no calibration rows",
        ),
        (
            "spectrasherpa.model-artifact.simca/1",
            "59a3108692c2bc47e46ef6dc5de06fd7fa75e6951492f42100470ecdd6dc254c",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.simca/1",
            contract_digest="59a3108692c2bc47e46ef6dc5de06fd7fa75e6951492f42100470ecdd6dc254c",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="SIMCA state retains class PCA parameters and limits but no calibration rows",
        ),
        (
            "spectrasherpa.model-artifact.simca/1",
            "34ba7fc9d731b016c4d00b61f10c9955452bdea8799272b9c4cb2fe09be45b1b",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.simca/1",
            contract_digest="34ba7fc9d731b016c4d00b61f10c9955452bdea8799272b9c4cb2fe09be45b1b",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="SIMCA state retains class PCA parameters and limits but no calibration rows",
        ),
        (
            "spectrasherpa.model-artifact.simca/1",
            "ad041822b4ec6a22ab198d0b958e55917d410e6b70ba4f87c77411aa05da1ff5",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.simca/1",
            contract_digest="ad041822b4ec6a22ab198d0b958e55917d410e6b70ba4f87c77411aa05da1ff5",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="SIMCA state retains class PCA parameters and limits but no calibration rows",
        ),
        (
            "spectrasherpa.model-artifact.simca/1",
            "04677597aae03052e1c283b2fdd25baa8c4d038ace581c41f022671605cc2afa",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.simca/1",
            contract_digest="04677597aae03052e1c283b2fdd25baa8c4d038ace581c41f022671605cc2afa",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="SIMCA state retains class PCA parameters and limits but no calibration rows",
        ),
        (
            "spectrasherpa.model-artifact.simca/1",
            "5abf4cbcc9d2976140d0ce3f2b6aaf1bdb61d7db5b00181c815bb553ab6f5dad",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.simca/1",
            contract_digest="5abf4cbcc9d2976140d0ce3f2b6aaf1bdb61d7db5b00181c815bb553ab6f5dad",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="SIMCA state retains class PCA parameters and limits but no calibration rows",
        ),
        (
            "spectrasherpa.model-artifact.simca/1",
            "7e9da69548ecfec1880c071a0cd95bea8ebe45e18f76b395dd208fcb829cf7ec",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.simca/1",
            contract_digest="7e9da69548ecfec1880c071a0cd95bea8ebe45e18f76b395dd208fcb829cf7ec",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale=(
                "SIMCA state retains class PCA parameters, limits, and aggregate applicability evidence "
                "but no calibration rows"
            ),
        ),
        (
            "spectra.sherpa-simpls-regression-json/6",
            "64bdf49b4d1cc289f43edca2e760037b3ce6c82e731bbb3c9aa1b7c7460028a8",
        ): FittedStateCustodyCapability(
            serializer="spectra.sherpa-simpls-regression-json/6",
            contract_digest="64bdf49b4d1cc289f43edca2e760037b3ce6c82e731bbb3c9aa1b7c7460028a8",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="affine fitted PLS state retains model parameters but no calibration rows",
        ),
        (
            "spectra.sherpa-simpls-regression-json/6",
            "ac05f06a069e5551f5cd101dbaec0d40ff352860b360a98e367e1f17dbbaf98d",
        ): FittedStateCustodyCapability(
            serializer="spectra.sherpa-simpls-regression-json/6",
            contract_digest="ac05f06a069e5551f5cd101dbaec0d40ff352860b360a98e367e1f17dbbaf98d",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="affine fitted PLS state retains model parameters but no calibration rows",
        ),
        (
            "spectra.sherpa-simpls-regression-json/6",
            "77ca83c532d71be3d6e409bc1c01bdb96421d104169286f0814dd163f2e53b55",
        ): FittedStateCustodyCapability(
            serializer="spectra.sherpa-simpls-regression-json/6",
            contract_digest="77ca83c532d71be3d6e409bc1c01bdb96421d104169286f0814dd163f2e53b55",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="affine fitted PLS state retains model parameters but no calibration rows",
        ),
        (
            "spectra.scale-reference-json.v1",
            "63775b077703d1f01a3d7b241b7d453c20975a0dff673412d7221e47c3a24b5f",
        ): FittedStateCustodyCapability(
            serializer="spectra.scale-reference-json.v1",
            contract_digest="63775b077703d1f01a3d7b241b7d453c20975a0dff673412d7221e47c3a24b5f",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="scale state retains one feature-wise center and scale vector but no rows",
        ),
        (
            "spectra.scale-reference-json.v1",
            "69fab701605f3deaaeee309dceb58df007adb753382b6cedfdf541fa8de7f933",
        ): FittedStateCustodyCapability(
            serializer="spectra.scale-reference-json.v1",
            contract_digest="69fab701605f3deaaeee309dceb58df007adb753382b6cedfdf541fa8de7f933",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="scale state retains one feature-wise center and scale vector but no rows",
        ),
        (
            "spectra.scale-reference-json.v1",
            "1d575d6ae82824e6a10a9d7c0716584f7c47c22dfbd38a411212b48095c273a4",
        ): FittedStateCustodyCapability(
            serializer="spectra.scale-reference-json.v1",
            contract_digest="1d575d6ae82824e6a10a9d7c0716584f7c47c22dfbd38a411212b48095c273a4",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale="scale state retains one feature-wise center and scale vector but no rows",
        ),
        (
            "spectra.scale-reference-json.v1",
            "1d7a0b2e677679c9bb9e6c2ab255edb8cb151ba1fe4002c51124d8ad6f16d2dd",
        ): FittedStateCustodyCapability(
            serializer="spectra.scale-reference-json.v1",
            contract_digest="1d7a0b2e677679c9bb9e6c2ab255edb8cb151ba1fe4002c51124d8ad6f16d2dd",
            custody_class=DATA_FREE_APPLICATION_STATE,
            rationale=(
                "the updated supervision binder permits a single attached group; "
                "scale state still retains only feature-wise center and scale vectors, not rows"
            ),
        ),
        (
            "spectrasherpa.model-artifact.knn/1",
            "23a7aae65d8cff424a36fd8c4401d66fca707a27a8e786054b5103b33faf16a3",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.knn/1",
            contract_digest="23a7aae65d8cff424a36fd8c4401d66fca707a27a8e786054b5103b33faf16a3",
            custody_class=RETAINS_TRAINING_ROWS,
            rationale="KNN application requires the complete calibration matrix and encoded labels",
        ),
        (
            "spectrasherpa.model-artifact.knn/1",
            "55e1151d097627dd0b54461e2eacca61b48438f1be6414efcf87455de5feb6d3",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.knn/1",
            contract_digest="55e1151d097627dd0b54461e2eacca61b48438f1be6414efcf87455de5feb6d3",
            custody_class=RETAINS_TRAINING_ROWS,
            rationale="KNN application requires the complete calibration matrix and encoded labels",
        ),
        (
            "spectrasherpa.model-artifact.knn/1",
            "ac9d51c9f1058805ff7663018f016b1e73044ed4025a0cd06129835a0b7489d0",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.knn/1",
            contract_digest="ac9d51c9f1058805ff7663018f016b1e73044ed4025a0cd06129835a0b7489d0",
            custody_class=RETAINS_TRAINING_ROWS,
            rationale="KNN application requires the complete calibration matrix and encoded labels",
        ),
        (
            "spectrasherpa.model-artifact.knn/1",
            "25f3b2acf2de08121f074109d4b4af6901bbadeadef4daf5583eba0924e257a3",
        ): FittedStateCustodyCapability(
            serializer="spectrasherpa.model-artifact.knn/1",
            contract_digest="25f3b2acf2de08121f074109d4b4af6901bbadeadef4daf5583eba0924e257a3",
            custody_class=RETAINS_TRAINING_ROWS,
            rationale="KNN application requires the complete calibration matrix and encoded labels",
        ),
    }
)


def fitted_state_custody_capability(
    serializer: object,
    contract_digest: object,
) -> FittedStateCustodyCapability:
    """Return one exact serializer/contract capability, refusing drift."""

    if not isinstance(serializer, str) or not serializer:
        raise FittedStateCustodyError("fitted-state serializer identity is invalid")
    if (
        not isinstance(contract_digest, str)
        or len(contract_digest) != 64
        or any(character not in "0123456789abcdef" for character in contract_digest)
    ):
        raise FittedStateCustodyError("fitted-state execution-contract identity is invalid")
    capability = _CAPABILITIES.get((serializer, contract_digest))
    if capability is None:
        raise FittedStateCustodyError("fitted-state serializer and contract have no closed custody capability")
    return capability


def require_data_free_fitted_state_members(members: Iterable[Mapping[str, object]]) -> None:
    """Require exact serializer/contract pairs consisting only of data-free state."""

    observed = tuple(members)
    if not observed:
        raise FittedStateCustodyError("fitted-state custody inventory is empty")
    for member in observed:
        if not isinstance(member, Mapping):
            raise FittedStateCustodyError("fitted-state custody member is invalid")
        capability = fitted_state_custody_capability(
            member.get("serializer"),
            member.get("contract_digest"),
        )
        if capability.custody_class != DATA_FREE_APPLICATION_STATE:
            raise FittedStateCustodyError("fitted-state serializer retains calibration or reference rows")


__all__ = [
    "DATA_FREE_APPLICATION_STATE",
    "RETAINS_TRAINING_ROWS",
    "FittedStateCustodyCapability",
    "FittedStateCustodyError",
    "fitted_state_custody_capability",
    "require_data_free_fitted_state_members",
]
