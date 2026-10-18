"""Optional goal classifier for the Starter planner.

OSS plans goals with keyword rules only. A deployment with a language model
can register a classifier that reads the goal text, picks one of the offered
intents and, optionally, the dataset to start from. The classifier never
writes steps: the planner validates both choices against what it offered and
builds the plan itself, so a model answer can only change which supported
starter and which compatible dataset are suggested.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_CLASSIFIER_TIMEOUT_SECONDS = 20.0


@dataclass(frozen=True)
class GoalClassification:
    intent: str
    confidence: float
    summary: str | None = None
    dataset_key: str | None = None
    dataset_reason: str | None = None


GoalClassifier = Callable[..., Awaitable[GoalClassification | None]]

_classifier: GoalClassifier | None = None
_is_available: Callable[[], bool] | None = None
_timeout_seconds = DEFAULT_CLASSIFIER_TIMEOUT_SECONDS


def set_goal_classifier(
    classifier: GoalClassifier | None,
    *,
    timeout_seconds: float | None = None,
    is_available: Callable[[], bool] | None = None,
) -> None:
    """Register (or clear, with ``None``) the deployment's goal classifier.

    ``is_available`` lets a deployment report its model as temporarily
    unavailable without unregistering the classifier.
    """
    global _classifier, _is_available, _timeout_seconds
    _classifier = classifier
    _is_available = is_available
    _timeout_seconds = timeout_seconds or DEFAULT_CLASSIFIER_TIMEOUT_SECONDS


def goal_classifier_available() -> bool:
    if _classifier is None:
        return False
    if _is_available is None:
        return True
    try:
        return bool(_is_available())
    except Exception:
        logger.warning("Starter goal classifier availability check failed", exc_info=True)
        return False


def _clean(text: str | None) -> str | None:
    return " ".join(text.split())[:240] or None if text else None


async def classify_goal_with_model(
    goal: str,
    *,
    intents: list[dict[str, Any]],
    datasets: list[dict[str, Any]] | None = None,
    user_id: int,
) -> GoalClassification | None:
    """Ask the registered classifier, returning ``None`` on any failure.

    ``intents`` lists the allowed ``{"key", "label", "summary"}`` choices and
    ``datasets`` the candidate ``{"key", "label", "kind", "technique",
    "description", "supports"}`` datasets. An answer naming an unknown intent,
    or a confidence outside ``[0, 1]``, is discarded so the caller falls back
    to the keyword plan. A dataset that was not offered, or that does not
    support the chosen intent, is dropped while the intent is kept.
    """
    classifier = _classifier
    if classifier is None or not goal_classifier_available():
        return None
    try:
        result = await asyncio.wait_for(
            classifier(goal=goal, intents=intents, datasets=list(datasets or []), user_id=user_id),
            timeout=_timeout_seconds,
        )
    except Exception:
        logger.warning("Starter goal classifier failed", exc_info=True)
        return None
    if not isinstance(result, GoalClassification):
        return None
    if result.intent not in {intent["key"] for intent in intents}:
        logger.warning("Starter goal classifier returned unknown intent=%r", result.intent)
        return None
    if not 0.0 <= float(result.confidence) <= 1.0:
        return None
    dataset_key, dataset_reason = result.dataset_key, _clean(result.dataset_reason)
    offered = {str(dataset.get("key")): dataset for dataset in datasets or []}
    candidate = offered.get(str(dataset_key)) if dataset_key is not None else None
    if candidate is None or (
        candidate.get("kind") != "experiment" and result.intent not in (candidate.get("supports") or ())
    ):
        if dataset_key is not None:
            logger.warning("Starter goal classifier returned an unoffered dataset")
        dataset_key, dataset_reason = None, None
    return GoalClassification(
        intent=result.intent,
        confidence=float(result.confidence),
        summary=_clean(result.summary),
        dataset_key=dataset_key,
        dataset_reason=dataset_reason,
    )
