"""Closed Sherpa-native PLS-DA fitted-state and artifact authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from spectra_sherpa.app.services.dag.nodes.modeling.pls_core import apply_pls_affine_state
from spectra_sherpa.core.axis_semantics import axis_semantics
from spectra_sherpa.core.model_artifact import (
    CANONICAL_MODEL_ARTIFACT_AUTHORITY,
    require_model_artifact_authority,
)

from ..modeling.pls_core import ALGORITHM_ID, ALGORITHM_VERSION, PLSFit

FITTED_STATE_SERIALIZER = "spectrasherpa.sherpa-plsda-state/4"
ARTIFACT_SERIALIZER = "spectrasherpa.model-artifact.sherpa-plsda/3"
LEGACY_FITTED_STATE_SERIALIZER = "spectrasherpa.sherpa-plsda-state/3"
LEGACY_ARTIFACT_SERIALIZER = "spectrasherpa.model-artifact.sherpa-plsda/2"
DECISION_RULE = "maximum_predicted_dummy_response"
OUTPUT_SEMANTICS = "class_response_scores_not_probabilities"
CANONICAL_MODEL_ORIGIN = CANONICAL_MODEL_ARTIFACT_AUTHORITY


def canonical_model_validation_required(metadata: object) -> bool:
    """Return whether the closed persisted-artifact authority is canonical."""

    if not isinstance(metadata, dict):
        raise ValueError("model artifact manifest must be a mapping")
    return require_model_artifact_authority(metadata) == CANONICAL_MODEL_ARTIFACT_AUTHORITY


def _finite_array(value: object, *, name: str, shape: tuple[int, ...]) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.shape != shape or not np.isfinite(array).all():
        raise ValueError(f"Sherpa PLS-DA {name} does not match its fitted-state contract")
    return np.array(array, copy=True)


def _feature_identity(
    source: object,
    features: int,
    *,
    feature_mask: object | None = None,
) -> dict[str, object]:
    """Capture the ordered typed feature axis, or mark an array positional."""

    axis_getter = getattr(source, "get_feature_axis", None)
    axis = axis_getter() if callable(axis_getter) else None
    if axis is None:
        return {"mode": "positional", "count": features}
    # Spectral identity is the physical coordinate plus units/quantity. A
    # parser's display labels are not a second scientific feature name and may
    # be dropped by a lossless variable-selection step.
    raw_labels = None if type(axis).__name__ == "SpectralAxis" else getattr(axis, "labels", None)
    labels = None if raw_labels is None else [str(value) for value in raw_labels]
    raw_values = getattr(axis, "values", None)
    mask = None if feature_mask is None else np.asarray(feature_mask, dtype=bool)
    apply_mask = False
    if mask is not None:
        if mask.ndim != 1 or int(mask.sum()) != features:
            raise ValueError("Sherpa PLS-DA feature mask does not match its fitted feature count")
        axis_lengths = [len(labels)] if labels is not None else []
        if raw_values is not None:
            axis_lengths.append(int(np.asarray(raw_values).size))
        if axis_lengths and all(length == mask.size for length in axis_lengths):
            apply_mask = True
        elif not axis_lengths or not all(length == features for length in axis_lengths):
            raise ValueError("Sherpa PLS-DA feature mask does not align to the supplied feature axis")
        if labels is not None and apply_mask:
            labels = np.asarray(labels, dtype=object)[mask].tolist()
    if labels is not None:
        if len(labels) != features or any(not value for value in labels) or len(set(labels)) != len(labels):
            raise ValueError("Sherpa PLS-DA feature labels must be ordered, non-empty, and unique")
    values = None
    if raw_values is not None:
        coordinates = np.asarray(raw_values, dtype=np.float64)
        if mask is not None and apply_mask:
            coordinates = coordinates[mask]
        if coordinates.shape != (features,) or not np.isfinite(coordinates).all():
            raise ValueError("Sherpa PLS-DA feature coordinates must be finite and align to X")
        values = coordinates.tolist()
    if labels is None and values is None:
        return {"mode": "positional", "count": features}
    semantics = axis_semantics(
        axis_class=type(axis).__name__,
        title=getattr(axis, "title", None),
        units=getattr(axis, "units", None),
        quantity=getattr(axis, "quantity", None),
    )
    quantity = None if semantics.quantity is None else semantics.quantity.value
    return {
        "mode": "typed_axis",
        "count": features,
        "axis_type": type(axis).__name__,
        "labels": labels,
        "values": values,
        "units": semantics.units,
        "quantity": None if quantity is None else str(quantity),
    }


def _validate_feature_identity(value: object, features: int) -> dict[str, object]:
    if not isinstance(value, dict) or value.get("count") != features:
        raise ValueError("Sherpa PLS-DA feature identity does not match its fitted feature count")
    if value.get("mode") == "positional" and set(value) == {"mode", "count"}:
        return dict(value)
    expected = {"mode", "count", "axis_type", "labels", "values", "units", "quantity"}
    if value.get("mode") != "typed_axis" or set(value) != expected:
        raise ValueError("Sherpa PLS-DA feature identity has an unsupported schema")
    labels = value["labels"]
    if labels is not None and (
        not isinstance(labels, list)
        or len(labels) != features
        or any(not isinstance(item, str) or not item for item in labels)
        or len(set(labels)) != len(labels)
    ):
        raise ValueError("Sherpa PLS-DA feature identity labels are invalid")
    values = value["values"]
    if values is not None:
        _finite_array(values, name="feature coordinates", shape=(features,))
    if labels is None and values is None:
        raise ValueError("Sherpa PLS-DA typed feature identity has no labels or coordinates")
    for field in ("axis_type", "units", "quantity"):
        if value[field] is not None and not isinstance(value[field], str):
            raise ValueError("Sherpa PLS-DA feature identity text fields are invalid")
    return dict(value)


@dataclass(frozen=True)
class SherpaPLSDAArtifact:
    """Portable PLS2 dummy-response model with an explicit argmax decision."""

    requested_n_components: int
    effective_n_components: int
    scale: bool
    classes: tuple[str, ...]
    coefficients: np.ndarray
    x_offset: np.ndarray
    y_offset: np.ndarray
    x_loadings: np.ndarray
    y_loadings: np.ndarray
    x_explained_variance: np.ndarray
    y_explained_variance: np.ndarray
    feature_identity: dict[str, object] | None = None
    algorithm_id: str = ALGORITHM_ID
    algorithm_version: str = ALGORITHM_VERSION

    @classmethod
    def from_fit(cls, fit: PLSFit, classes: object, feature_source: object | None = None) -> SherpaPLSDAArtifact:
        labels = tuple(str(value) for value in np.asarray(classes, dtype=object).tolist())
        return cls(
            requested_n_components=fit.requested_n_components,
            effective_n_components=fit.n_components,
            scale=fit.scale,
            classes=labels,
            coefficients=np.array(fit.coefficients, copy=True),
            x_offset=np.array(fit.x_offset, copy=True),
            y_offset=np.array(fit.y_offset, copy=True),
            x_loadings=np.array(fit.x_loadings.T, copy=True),
            y_loadings=np.array(fit.y_loadings.T, copy=True),
            x_explained_variance=np.array(fit.x_explained_variance, copy=True),
            y_explained_variance=np.array(fit.y_explained_variance, copy=True),
            feature_identity=_feature_identity(feature_source, fit.coefficients.shape[0]),
        ).validated()

    @property
    def features(self) -> int:
        return int(np.asarray(self.coefficients).shape[0])

    def validated(self) -> SherpaPLSDAArtifact:
        if self.algorithm_id != ALGORITHM_ID or self.algorithm_version != ALGORITHM_VERSION:
            raise ValueError("Sherpa PLS-DA fitted state has an unsupported algorithm identity")
        if (
            type(self.requested_n_components) is not int
            or self.requested_n_components < 1
            or type(self.effective_n_components) is not int
            or not 1 <= self.effective_n_components <= self.requested_n_components
            or type(self.scale) is not bool
        ):
            raise ValueError("Sherpa PLS-DA fitted state has invalid fitting parameters")
        if len(self.classes) < 2 or len(set(self.classes)) != len(self.classes):
            raise ValueError("Sherpa PLS-DA fitted state requires distinct class labels")
        if not all(isinstance(label, str) and label for label in self.classes):
            raise ValueError("Sherpa PLS-DA fitted state class labels must be non-empty strings")
        coefficients = np.asarray(self.coefficients, dtype=np.float64)
        if coefficients.ndim != 2 or coefficients.shape[0] < 1 or coefficients.shape[1] != len(self.classes):
            raise ValueError("Sherpa PLS-DA coefficients do not match the class contract")
        features = int(coefficients.shape[0])
        _validate_feature_identity(self.feature_identity or {"mode": "positional", "count": features}, features)
        components = self.effective_n_components
        _finite_array(coefficients, name="coefficients", shape=(features, len(self.classes)))
        _finite_array(self.x_offset, name="X offset", shape=(features,))
        _finite_array(self.y_offset, name="Y offset", shape=(len(self.classes),))
        _finite_array(self.x_loadings, name="X loadings", shape=(components, features))
        _finite_array(self.y_loadings, name="Y loadings", shape=(components, len(self.classes)))
        x_explained = _finite_array(
            self.x_explained_variance,
            name="explained X variance",
            shape=(components,),
        )
        y_explained = _finite_array(
            self.y_explained_variance,
            name="explained Y variance",
            shape=(components,),
        )
        tolerance = 64.0 * np.finfo(np.float64).eps
        for name, values in (("X", x_explained), ("Y", y_explained)):
            if np.any(values < -tolerance) or float(np.sum(values)) > 1.0 + tolerance:
                raise ValueError(f"Sherpa PLS-DA explained {name} variance is outside [0, 1]")
        return self

    @property
    def feature_identity_mode(self) -> str:
        identity = _validate_feature_identity(
            self.feature_identity or {"mode": "positional", "count": self.features}, self.features
        )
        return str(identity["mode"])

    def _predict_matrix(self, X: object) -> tuple[np.ndarray, np.ndarray]:
        """Numerical kernel; callers must validate feature identity first."""

        self.validated()
        matrix = np.asarray(X, dtype=np.float64)
        if matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        if matrix.ndim != 2 or matrix.shape[1] != self.features or not np.isfinite(matrix).all():
            raise ValueError("Sherpa PLS-DA application input does not match its fitted feature contract")
        responses = apply_pls_affine_state(
            matrix,
            coefficients=self.coefficients,
            feature_offset=self.x_offset,
            prediction_offset=self.y_offset,
        )
        labels = np.asarray(self.classes, dtype=object)[np.argmax(responses, axis=1)]
        return labels, np.asarray(responses, dtype=np.float64)

    def predict(
        self,
        source: object,
        *,
        allow_unverified_positional: bool = False,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Apply through the typed feature-identity boundary."""

        self.validate_application_features(
            source,
            allow_unverified_positional=allow_unverified_positional,
        )
        matrix = source.X if hasattr(source, "X") else source
        return self._predict_matrix(matrix)

    def validate_application_features(
        self,
        source: object,
        *,
        feature_mask: object | None = None,
        allow_unverified_positional: bool = False,
    ) -> None:
        """Reject same-width feature reordering before numerical extraction."""

        expected = _validate_feature_identity(
            self.feature_identity or {"mode": "positional", "count": self.features}, self.features
        )
        if expected["mode"] == "positional":
            if not allow_unverified_positional:
                raise ValueError(
                    "Sherpa PLS-DA application has unverified positional feature identity; "
                    "explicit legacy recovery opt-in is required"
                )
            return
        actual = _feature_identity(source, self.features, feature_mask=feature_mask)
        if actual["mode"] != "typed_axis":
            raise ValueError("Sherpa PLS-DA application requires the fitted typed feature axis")
        if actual != expected:
            changed = sorted(key for key in set(actual) | set(expected) if actual.get(key) != expected.get(key))
            raise ValueError(
                "Sherpa PLS-DA application feature identity differs from the fitted model: " + ", ".join(changed)
            )

    def to_artifact(self) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
        self.validated()
        metadata: dict[str, Any] = {
            "model_type": "plsda",
            "serializer": ARTIFACT_SERIALIZER,
            "algorithm_id": self.algorithm_id,
            "algorithm_version": self.algorithm_version,
            "requested_n_components": self.requested_n_components,
            "effective_n_components": self.effective_n_components,
            "scale": self.scale,
            "classes": list(self.classes),
            "decision_rule": DECISION_RULE,
            "output_semantics": OUTPUT_SEMANTICS,
            "features": self.features,
            "feature_identity": _validate_feature_identity(
                self.feature_identity or {"mode": "positional", "count": self.features}, self.features
            ),
        }
        arrays = {
            "coefficients": np.asarray(self.coefficients, dtype=np.float64),
            "x_offset": np.asarray(self.x_offset, dtype=np.float64),
            "y_offset": np.asarray(self.y_offset, dtype=np.float64),
            "x_loadings": np.asarray(self.x_loadings, dtype=np.float64),
            "y_loadings": np.asarray(self.y_loadings, dtype=np.float64),
            "x_explained_variance": np.asarray(self.x_explained_variance, dtype=np.float64),
            "y_explained_variance": np.asarray(self.y_explained_variance, dtype=np.float64),
        }
        return metadata, arrays

    @classmethod
    def from_artifact(cls, metadata: object, arrays: object) -> SherpaPLSDAArtifact:
        common_metadata = {
            "model_type",
            "serializer",
            "algorithm_id",
            "algorithm_version",
            "requested_n_components",
            "effective_n_components",
            "scale",
            "classes",
            "decision_rule",
            "output_semantics",
            "features",
        }
        if not isinstance(metadata, dict) or not common_metadata <= set(metadata):
            raise ValueError("Sherpa PLS-DA artifact metadata does not match its closed schema")
        serializer = metadata.get("serializer")
        if serializer == ARTIFACT_SERIALIZER:
            if "feature_identity" not in metadata:
                raise ValueError("Sherpa PLS-DA artifact metadata does not match its closed schema")
            feature_identity = _validate_feature_identity(metadata["feature_identity"], metadata["features"])
        elif serializer == LEGACY_ARTIFACT_SERIALIZER:
            feature_identity = {"mode": "positional", "count": metadata["features"]}
        else:
            raise ValueError("Sherpa PLS-DA artifact has an unsupported serializer")
        if (
            metadata["model_type"] != "plsda"
            or metadata["decision_rule"] != DECISION_RULE
            or metadata["output_semantics"] != OUTPUT_SEMANTICS
            or type(metadata["features"]) is not int
            or metadata["features"] < 1
            or not isinstance(metadata["classes"], list)
        ):
            raise ValueError("Sherpa PLS-DA artifact has an invalid scientific identity")
        if not isinstance(arrays, dict) or set(arrays) != {
            "coefficients",
            "x_offset",
            "y_offset",
            "x_loadings",
            "y_loadings",
            "x_explained_variance",
            "y_explained_variance",
        }:
            raise ValueError("Sherpa PLS-DA artifact arrays do not match its closed schema")
        restored = cls(
            algorithm_id=metadata["algorithm_id"],
            algorithm_version=metadata["algorithm_version"],
            requested_n_components=metadata["requested_n_components"],
            effective_n_components=metadata["effective_n_components"],
            scale=metadata["scale"],
            classes=tuple(metadata["classes"]),
            coefficients=np.asarray(arrays["coefficients"], dtype=np.float64),
            x_offset=np.asarray(arrays["x_offset"], dtype=np.float64),
            y_offset=np.asarray(arrays["y_offset"], dtype=np.float64),
            x_loadings=np.asarray(arrays["x_loadings"], dtype=np.float64),
            y_loadings=np.asarray(arrays["y_loadings"], dtype=np.float64),
            x_explained_variance=np.asarray(arrays["x_explained_variance"], dtype=np.float64),
            y_explained_variance=np.asarray(arrays["y_explained_variance"], dtype=np.float64),
            feature_identity=feature_identity,
        ).validated()
        if restored.features != metadata["features"]:
            raise ValueError("Sherpa PLS-DA artifact feature count contradicts its state")
        return restored

    def to_fitted_state(self) -> dict[str, object]:
        metadata, arrays = self.to_artifact()
        return {
            "serializer": FITTED_STATE_SERIALIZER,
            "metadata": metadata,
            "arrays": {name: value.tolist() for name, value in arrays.items()},
        }

    @classmethod
    def from_fitted_state(cls, state: object) -> SherpaPLSDAArtifact:
        if not isinstance(state, dict) or set(state) != {"serializer", "metadata", "arrays"}:
            raise ValueError("Sherpa PLS-DA fitted state must contain exact serializer, metadata, and arrays")
        if state["serializer"] not in {FITTED_STATE_SERIALIZER, LEGACY_FITTED_STATE_SERIALIZER}:
            raise ValueError("Sherpa PLS-DA fitted state has an unsupported serializer")
        metadata = state["metadata"]
        if not isinstance(metadata, dict):
            raise ValueError("Sherpa PLS-DA fitted-state metadata must be a mapping")
        expected_artifact_serializer = (
            ARTIFACT_SERIALIZER if state["serializer"] == FITTED_STATE_SERIALIZER else LEGACY_ARTIFACT_SERIALIZER
        )
        if metadata.get("serializer") != expected_artifact_serializer:
            raise ValueError("Sherpa PLS-DA fitted-state and artifact serializers contradict each other")
        arrays = state["arrays"]
        if not isinstance(arrays, dict):
            raise ValueError("Sherpa PLS-DA fitted-state arrays must be a mapping")
        return cls.from_artifact(metadata, {name: np.asarray(value) for name, value in arrays.items()})


def apply_fitted_state(
    input_data: object,
    state: object,
    *,
    allow_unverified_positional: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Apply one native PLS-DA state without importing the training node."""

    artifact = SherpaPLSDAArtifact.from_fitted_state(state)
    return artifact.predict(
        input_data,
        allow_unverified_positional=allow_unverified_positional,
    )


def feature_identity_diagnostics(state: object) -> dict[str, object]:
    """Report whether a fitted state carries a verifiable typed feature axis."""

    mode = SherpaPLSDAArtifact.from_fitted_state(state).feature_identity_mode
    return {"feature_identity_mode": mode, "feature_identity_verified": mode == "typed_axis"}


__all__ = [
    "ARTIFACT_SERIALIZER",
    "CANONICAL_MODEL_ORIGIN",
    "DECISION_RULE",
    "FITTED_STATE_SERIALIZER",
    "OUTPUT_SEMANTICS",
    "SherpaPLSDAArtifact",
    "apply_fitted_state",
    "canonical_model_validation_required",
    "feature_identity_diagnostics",
]
