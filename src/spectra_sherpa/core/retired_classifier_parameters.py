"""Import-light authority for retired classifier validation parameters."""

from __future__ import annotations

import math
from typing import Any

RETIRED_CLASSIFIER_VALIDATION_PARAMETER = {
    "classification.knn": "cv_folds",
    "classification.plsda": "cv_folds",
    "classification.simca": "cv_folds",
}

CURRENT_CLASSIFIER_VALIDATION_SEMANTICS = "spectrasherpa-explicit-classifier-validation/1"

_HISTORICAL_CV_FOLDS_MIN = 2
_HISTORICAL_CV_FOLDS_MAX = 20


def historical_classifier_cv_folds(node_type: str, value: Any) -> int:
    """Re-admit one value through its operation's exact retired grammar."""

    if node_type not in RETIRED_CLASSIFIER_VALIDATION_PARAMETER:
        raise ValueError("retired cv_folds validator requires a known classifier operation")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("retired cv_folds must be a non-boolean integer in [2, 20]")
    if node_type == "classification.simca" and type(value) is not int:
        raise ValueError("retired SIMCA cv_folds must be a built-in integer in [2, 20]")
    if isinstance(value, int):
        normalized = value
    else:
        if not math.isfinite(value) or not value.is_integer():
            raise ValueError("retired cv_folds must be a finite integer in [2, 20]")
        normalized = int(value)
    if not _HISTORICAL_CV_FOLDS_MIN <= normalized <= _HISTORICAL_CV_FOLDS_MAX:
        raise ValueError("retired cv_folds must be an integer in [2, 20]")
    return normalized


__all__ = [
    "CURRENT_CLASSIFIER_VALIDATION_SEMANTICS",
    "RETIRED_CLASSIFIER_VALIDATION_PARAMETER",
    "historical_classifier_cv_folds",
]
