"""Narrow exploratory admission for verified v0.6.0 saved-model artifacts.

An old artifact cannot acquire signal units or measurement mode retroactively.
Even an acknowledged application therefore remains exploratory, never an
independent validation or an upgrade of the signed model itself.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from spectra_sherpa.app.lib.sherpa_dataset import SherpaDataset
from spectra_sherpa.core.axis_semantics import axis_semantics, canonical_axis_unit

_V060_PLSDA = "spectrasherpa.model-artifact.sherpa-plsda/3"
_V060_FASTICA = "spectrasherpa.model-artifact.fastica/1"
_V060_PCA = "spectrasherpa.model-artifact.pca/3"
LEGACY_WARNING = (
    "This saved model predates fitted signal identity. Its ordered feature axis can be checked, "
    "but signal units and measurement mode cannot be authenticated from the model. "
    "Acknowledge exploratory use only, or refit from the original data for verified application."
)


class LegacyAcknowledgementRequired(ValueError):
    """The old artifact is eligible only after explicit exploratory consent."""


def require_legacy_application_acknowledgement(
    manifest: dict[str, Any],
    arrays: dict[str, Any],
    prepared: SherpaDataset,
    *,
    acknowledged: bool,
) -> str | None:
    """Verify the *retained* axis first, then require explicit acknowledgement.

    This is deliberately not a generic missing-identity bypass. A model with
    only positional columns, a different axis, or a current malformed state
    remains inadmissible regardless of the checkbox.
    """
    model_type = manifest.get("model_type")
    serializer = manifest.get("serializer")
    legacy = manifest.get("input_identity") is None and (
        (model_type, serializer) in {("plsda", _V060_PLSDA), ("fastica", _V060_FASTICA), ("pca", _V060_PCA)}
    )
    if not legacy:
        return None
    # The registry also serves the lightweight core profile, which has no app configuration.
    # Resolve product policy only when a legacy artifact is actually being admitted.
    from spectra_sherpa.app.core.mode_policy import is_local

    if not is_local():
        raise ValueError("Legacy exploratory model recovery is available only in local OSS")
    if model_type == "plsda":
        from spectra_sherpa.app.services.dag.nodes.classification.plsda_state import SherpaPLSDAArtifact

        identity = manifest.get("feature_identity")
        if not isinstance(identity, dict) or identity.get("mode") != "typed_axis":
            raise ValueError("Legacy PLS-DA has no exact typed feature axis; refit it before application")
        # The full state and its declared typed axis are validated separately
        # by the saved-model adapter before numerical application.
        artifact = SherpaPLSDAArtifact.from_artifact(manifest, arrays)
        artifact.validate_application_features(
            prepared, feature_mask=manifest.get("feature_mask"), allow_unverified_positional=True
        )
    else:
        _require_exact_legacy_axis(manifest, prepared)
    if not acknowledged:
        raise LegacyAcknowledgementRequired(LEGACY_WARNING)
    return LEGACY_WARNING


def _require_exact_legacy_axis(manifest: dict[str, Any], prepared: SherpaDataset) -> None:
    values = manifest.get("feature_axis")
    axis = prepared.get_feature_axis()
    count = manifest.get("n_features")
    if type(count) is not int or count < 1 or not isinstance(values, list) or len(values) != count:
        raise ValueError("Legacy model has no complete retained numeric feature axis; refit it")
    if axis is None or type(axis).__name__ != manifest.get("feature_axis_class") or axis.values is None:
        raise ValueError("Application data has no matching typed feature axis for the legacy model")
    expected = np.asarray(values, dtype=np.float64)
    actual = np.asarray(axis.values, dtype=np.float64)
    if expected.shape != (count,) or actual.shape != (count,) or not np.isfinite(expected).all():
        raise ValueError("Legacy model feature axis is malformed or incomplete")
    if not np.isfinite(actual).all() or not np.array_equal(expected, actual):
        raise ValueError("Application feature coordinates differ from the legacy fitted axis")
    semantics = axis_semantics(
        axis_class=type(axis).__name__,
        title=getattr(axis, "title", None),
        units=getattr(axis, "units", None),
        quantity=getattr(axis, "quantity", None),
    )
    expected_units = manifest.get("feature_axis_units")
    actual_units = semantics.units
    if canonical_axis_unit(expected_units) != canonical_axis_unit(actual_units):
        raise ValueError("Application feature-axis units differ from the legacy model")
    expected_quantity = manifest.get("feature_axis_quantity")
    actual_quantity = semantics.quantity.value if semantics.quantity is not None else None
    if expected_quantity != actual_quantity:
        raise ValueError("Application feature-axis quantity differs from the legacy model")
