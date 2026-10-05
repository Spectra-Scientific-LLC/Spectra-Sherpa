"""One scientific authority for combined classification application results."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from spectra_sherpa.app.lib.collection_assembly import lossless_sample_table_scalar

APPLICATION_SCHEMA = "spectra-classification-application/1"
CLASS_RESPONSE_SEMANTICS = "class_response_scores_not_probabilities"
CLASSIFICATION_REJECT_LABEL = "unassigned"
MAX_CLASSIFICATION_RESPONSE_ELEMENTS = 20_000_000
_ISSUER = object()


class ClassificationApplicationError(ValueError):
    """A combined classification result contradicted its scientific contract."""


@dataclass(frozen=True, init=False)
class ClassificationApplication:
    """Executor-issued, immutable decision/response application authority."""

    fitted_state_digest: str
    predictions: np.ndarray
    responses: np.ndarray
    classes: tuple[str | int | float | bool, ...]
    margins: np.ndarray
    application_digest: str
    semantics: str
    _authority: object

    def __init__(
        self,
        fitted_state_digest: str,
        predictions: np.ndarray,
        responses: np.ndarray,
        classes: tuple[str | int | float | bool, ...],
        margins: np.ndarray,
        application_digest: str,
        semantics: str,
        *,
        _authority: object,
    ) -> None:
        if _authority is not _ISSUER:
            raise TypeError("classification applications may only be issued by the shared validator")
        object.__setattr__(self, "fitted_state_digest", fitted_state_digest)
        object.__setattr__(self, "predictions", predictions)
        object.__setattr__(self, "responses", responses)
        object.__setattr__(self, "classes", classes)
        object.__setattr__(self, "margins", margins)
        object.__setattr__(self, "application_digest", application_digest)
        object.__setattr__(self, "semantics", semantics)
        object.__setattr__(self, "_authority", _authority)

    def assert_valid(self) -> None:
        """Re-admit this record through the same authority without replaying a model."""

        rebound = validate_classification_application(
            predictions=self.predictions,
            responses=self.responses,
            classes=self.classes,
            fitted_state_digest=self.fitted_state_digest,
            semantics=self.semantics,
        )
        if rebound.application_digest != self.application_digest:
            raise ClassificationApplicationError("classification application digest is stale")


def validate_classification_application(
    *,
    predictions: object,
    responses: object,
    classes: Sequence[object],
    fitted_state_digest: str,
    semantics: str = CLASS_RESPONSE_SEMANTICS,
) -> ClassificationApplication:
    """Validate one combined decision/response result and issue its digest."""

    if not _is_sha256(fitted_state_digest):
        raise ClassificationApplicationError("classification fitted-state identity is malformed")
    if semantics != CLASS_RESPONSE_SEMANTICS:
        raise ClassificationApplicationError("classification response semantics are unsupported")
    if isinstance(classes, np.ndarray):
        if classes.ndim != 1:
            raise ClassificationApplicationError("classification classes are malformed")
        class_values: Sequence[object] = classes.tolist()
    elif isinstance(classes, (str, bytes)) or not isinstance(classes, Sequence):
        raise ClassificationApplicationError("classification classes are malformed")
    else:
        class_values = classes
    try:
        normalized_classes = tuple(lossless_sample_table_scalar(value) for value in class_values)
    except ValueError as exc:
        raise ClassificationApplicationError("classification classes are not lossless JSON scalars") from exc
    if len(normalized_classes) < 2 or any(value is None for value in normalized_classes):
        raise ClassificationApplicationError("classification requires at least two non-null classes")
    if len({_typed_identity(value) for value in normalized_classes}) != len(normalized_classes):
        raise ClassificationApplicationError("classification classes contain duplicate typed identities")

    matrix = np.asarray(responses, dtype=np.float64)
    if (
        matrix.ndim != 2
        or matrix.shape[1] != len(normalized_classes)
        or matrix.size > MAX_CLASSIFICATION_RESPONSE_ELEMENTS
        or not np.isfinite(matrix).all()
    ):
        raise ClassificationApplicationError("classification responses are malformed")
    raw_predictions = np.asarray(predictions, dtype=object)
    if raw_predictions.ndim != 1 or raw_predictions.shape[0] != matrix.shape[0]:
        raise ClassificationApplicationError("classification predictions are malformed")
    try:
        normalized_predictions = tuple(lossless_sample_table_scalar(value) for value in raw_predictions.tolist())
    except ValueError as exc:
        raise ClassificationApplicationError("classification predictions are not lossless JSON scalars") from exc
    if any(value is None for value in normalized_predictions):
        raise ClassificationApplicationError("classification predictions contain null identities")

    class_array = np.asarray(normalized_classes, dtype=object)
    expected = tuple(class_array[np.argmax(matrix, axis=1)].tolist())
    if len(expected) != len(normalized_predictions) or any(
        _typed_identity(actual) != _typed_identity(wanted)
        for actual, wanted in zip(normalized_predictions, expected, strict=True)
    ):
        raise ClassificationApplicationError("classification decisions do not match response argmax")

    sorted_responses = np.sort(matrix, axis=1)
    margins = sorted_responses[:, -1] - sorted_responses[:, -2]
    if not np.isfinite(margins).all() or np.any(margins < 0):
        raise ClassificationApplicationError("classification decision margins are invalid")

    predictions_array = np.asarray(normalized_predictions, dtype=object)
    responses_array = np.array(matrix, dtype=np.float64, copy=True)
    margins_array = np.array(margins, dtype=np.float64, copy=True)
    for array in (predictions_array, responses_array, margins_array):
        array.setflags(write=False)
    digest = _application_digest(
        fitted_state_digest=fitted_state_digest,
        predictions=normalized_predictions,
        responses=responses_array,
        classes=normalized_classes,
    )
    return ClassificationApplication(
        fitted_state_digest,
        predictions_array,
        responses_array,
        normalized_classes,  # type: ignore[arg-type]
        margins_array,
        digest,
        semantics,
        _authority=_ISSUER,
    )


def _application_digest(
    *,
    fitted_state_digest: str,
    predictions: tuple[object, ...],
    responses: np.ndarray,
    classes: tuple[object, ...],
) -> str:
    header = json.dumps(
        {
            "schema_version": APPLICATION_SCHEMA,
            "fitted_state_digest": fitted_state_digest,
            "classes": list(classes),
            "predictions": list(predictions),
            "response_shape": list(responses.shape),
            "response_dtype": responses.dtype.str,
            "semantics": CLASS_RESPONSE_SEMANTICS,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(header + np.ascontiguousarray(responses).tobytes(order="C")).hexdigest()


def _typed_identity(value: object) -> tuple[type[object], object]:
    return type(value), value


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(char in "0123456789abcdef" for char in value)
    )


__all__ = [
    "APPLICATION_SCHEMA",
    "CLASSIFICATION_REJECT_LABEL",
    "CLASS_RESPONSE_SEMANTICS",
    "ClassificationApplication",
    "ClassificationApplicationError",
    "validate_classification_application",
]
