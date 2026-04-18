"""Mutable registry for the Sherpa AI service provider.

Kept separate from contracts/ai_provider.py so that the Protocol module
remains pure (types only, no mutable state). Server calls set_sherpa_advisor
at startup; OSS dispatch code calls get_sherpa_advisor.

This module is the Python injection seam defined in ADR-0001 SS5.1.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from spectra_sherpa.app.contracts.ai_provider import AIServiceProvider

logger = logging.getLogger(__name__)

_advisor: AIServiceProvider | None = None


class FeatureDisabledError(RuntimeError):
    """Raised when an advisor feature is invoked in the Disabled default."""


class DisabledAIProvider:
    """Default AIServiceProvider when no server is present. All methods disabled."""

    is_available: bool = False

    def has_feature(self, _feature: str) -> bool:
        return False

    async def sync_workflow(self, *_a: Any, **_k: Any) -> list[Any]:
        return []

    async def send_decision(self, *_a: Any, **_k: Any) -> bool:
        return False

    async def identify_peaks(self, *_a: Any, **_k: Any) -> dict[str, Any]:
        raise FeatureDisabledError("Sherpa advisor not available")

    async def generate_code(self, *_a: Any, **_k: Any) -> dict[str, Any]:
        raise FeatureDisabledError("Sherpa advisor not available")

    async def write_report(self, *_a: Any, **_k: Any) -> dict[str, Any]:
        raise FeatureDisabledError("Sherpa advisor not available")

    async def generate_data_story(self, *_a: Any, **_k: Any) -> AsyncIterator[dict[str, Any]]:
        raise FeatureDisabledError("Sherpa advisor not available")
        yield {}  # pragma: no cover

    async def stream_llm_chat(self, *_a: Any, **_k: Any) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "error", "detail": "Sherpa advisor not available"}

    async def chat_followup(self, *_a: Any, **_k: Any) -> AsyncIterator[str]:
        raise FeatureDisabledError("Sherpa advisor not available")
        yield ""  # pragma: no cover

    async def chat_with_tools(self, *_a: Any, **_k: Any) -> AsyncIterator[dict[str, Any]]:
        raise FeatureDisabledError("Sherpa advisor not available")
        yield {}  # pragma: no cover


def set_sherpa_advisor(advisor: AIServiceProvider) -> None:
    global _advisor
    _advisor = advisor
    logger.info("SherpaAdvisor: implementation injected by server")


def reset_sherpa_advisor() -> None:
    global _advisor
    _advisor = None
    logger.info("SherpaAdvisor: reset to Disabled default")


def get_sherpa_advisor() -> AIServiceProvider:
    return _advisor or DisabledAIProvider()
