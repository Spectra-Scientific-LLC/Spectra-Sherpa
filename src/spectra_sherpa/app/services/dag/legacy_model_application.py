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
_V060_KNN = "spectrasherpa.model-artifact.knn/1"
# SIMCA artifacts have never declared a serializer; a SIMCA manifest without
# input identity can only predate fitted signal identity.
_V060_SIMCA = None
_LEGACY_ARTIFACTS = frozenset(
    {
        ("plsda", _V060_PLSDA),
        ("fastica", _V060_FASTICA),
        ("pca", _V060_PCA),
        ("knn", _V060_KNN),
        ("simca", _V060_SIMCA),
    }
)
LEGACY_WARNING = (
    "This saved model predates fitted signal identity. Its ordered feature axis can be checked, "
    "but signal units and measurement mode cannot be authenticated from the model. "
    "Acknowledge exploratory use only, or refit from the original data for verified application."
)


class LegacyAcknowledgementRequired(ValueError):
    """The old artifact is eligible only after explicit exploratory consent."""


_LEGACY_REFUSAL_REASONS = {
    "local_only": "Legacy exploratory model recovery is available only in local OSS with application permission",
    "plsda_axis_unavailable": "Legacy PLS-DA has no exact typed feature axis; refit it before application",
    "axis_unavailable": "Legacy model has no complete retained numeric feature axis; refit it",
    "axis_type_mismatch": "Application data has no matching typed feature axis for the legacy model",
    "axis_malformed": "Legacy model feature axis is malformed or incomplete",
    "coordinates_mismatch": "Application feature coordinates differ from the legacy fitted axis",
    "units_mismatch": "Application feature-axis units differ from the legacy model",
    "quantity_mismatch": "Application feature-axis quantity differs from the legacy model",
}


def legacy_refusal_reason(code: str) -> str:
    """Return only authority-owned public advice, never an exception message."""
    return _LEGACY_REFUSAL_REASONS[code]


class LegacyInputRefusal(ValueError):
    """A known scientific refusal with a closed, literal public projection."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(legacy_refusal_reason(code))

    def __reduce__(self):
        return type(self), (self.code,), {**self.__dict__, "args": self.args}


def require_legacy_application_acknowledgement(
    manifest: dict[str, Any],
    arrays: dict[str, Any],
    prepared: SherpaDataset,
    *,
    acknowledged: bool,
    local_allowed: bool,
) -> str | None:
    """Verify the *retained* axis first, then require explicit acknowledgement.

    This is deliberately not a generic missing-identity bypass. A model with
    only positional columns, a different axis, or a current malformed state
    remains inadmissible regardless of the checkbox.
    """
    model_type = manifest.get("model_type")
    serializer = manifest.get("serializer")
    legacy = manifest.get("input_identity") is None and (model_type, serializer) in _LEGACY_ARTIFACTS
    if not legacy:
        return None
    if not local_allowed:
        raise LegacyInputRefusal("local_only")
    if model_type == "plsda":
        from spectra_sherpa.app.services.dag.nodes.classification.plsda_state import SherpaPLSDAArtifact

        identity = manifest.get("feature_identity")
        if not isinstance(identity, dict) or identity.get("mode") != "typed_axis":
            raise LegacyInputRefusal("plsda_axis_unavailable")
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
        raise LegacyInputRefusal("axis_unavailable")
    if axis is None or type(axis).__name__ != manifest.get("feature_axis_class") or axis.values is None:
        raise LegacyInputRefusal("axis_type_mismatch")
    expected = np.asarray(values, dtype=np.float64)
    actual = np.asarray(axis.values, dtype=np.float64)
    if expected.shape != (count,) or actual.shape != (count,) or not np.isfinite(expected).all():
        raise LegacyInputRefusal("axis_malformed")
    if not np.isfinite(actual).all() or not np.array_equal(expected, actual):
        raise LegacyInputRefusal("coordinates_mismatch")
    semantics = axis_semantics(
        axis_class=type(axis).__name__,
        title=getattr(axis, "title", None),
        units=getattr(axis, "units", None),
        quantity=getattr(axis, "quantity", None),
    )
    expected_units = manifest.get("feature_axis_units")
    actual_units = semantics.units
    if canonical_axis_unit(expected_units) != canonical_axis_unit(actual_units):
        raise LegacyInputRefusal("units_mismatch")
    expected_quantity = manifest.get("feature_axis_quantity")
    actual_quantity = semantics.quantity.value if semantics.quantity is not None else None
    if expected_quantity != actual_quantity:
        raise LegacyInputRefusal("quantity_mismatch")
