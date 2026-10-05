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
