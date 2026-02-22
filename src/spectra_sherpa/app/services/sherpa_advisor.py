"""
Sherpa AI Advisor Service Stub

This module provides a minimal stub implementation for the Sherpa AI Advisor service.
In OSS mode, Sherpa AI features are disabled. In hybrid/enterprise mode, this module
can be replaced by spectra-server with a full implementation that connects to the
SpectraSherpa cloud AI service.

The stub ensures that WebSocket handlers and LLM context checks don't crash when
the full Sherpa AI service is unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class SubscriptionRequiredError(Exception):
    """Raised when a feature requires a subscription that the user does not have.

    In OSS mode, this is a stub that is never raised. In hybrid/enterprise mode,
    spectra-server raises this when a user invokes a paid Sherpa feature without
    the required subscription plan.
    """

    def __init__(self, detail: str = "Subscription required"):
        self.detail = detail
        super().__init__(detail)


class SherpaAdvisor:
    """
    Stub implementation of Sherpa AI Advisor.

    In OSS mode, all features return False/disabled state.
    spectra-server can inject a full implementation that connects to cloud AI services.
    """

    def __init__(self):
        """Initialize stub advisor (OSS mode - features disabled)."""
        self._features = set()
        logger.debug("SherpaAdvisor initialized in stub mode (OSS)")

    def has_feature(self, feature: str) -> bool:
        """
        Check if a feature is available.

        Args:
            feature: Feature name (e.g., "full_dag_context", "code_generation")

        Returns:
            False in OSS mode (stub), True if feature is available in hybrid/enterprise
        """
        return feature in self._features

    def enable_feature(self, feature: str):
        """Enable a feature (for testing or hybrid mode injection)."""
        self._features.add(feature)
        logger.debug(f"SherpaAdvisor: enabled feature '{feature}'")

    def disable_feature(self, feature: str):
        """Disable a feature."""
        self._features.discard(feature)

    async def suggest_workflow(self, context: dict[str, Any]) -> dict[str, Any]:
        """
        Suggest a workflow based on context (OSS stub returns empty).

        In hybrid/enterprise mode, this would query the cloud AI service.
        """
        logger.debug("SherpaAdvisor.suggest_workflow called (stub mode - no suggestions)")
        return {
            "suggestions": [],
            "reasoning": "Sherpa AI is not available in OSS mode",
            "available": False,
        }

    async def analyze_results(self, results: dict[str, Any]) -> dict[str, Any]:
        """
        Analyze execution results (OSS stub returns empty).

        In hybrid/enterprise mode, this would query the cloud AI service for insights.
        """
        logger.debug("SherpaAdvisor.analyze_results called (stub mode - no analysis)")
        return {
            "insights": [],
            "recommendations": [],
            "available": False,
        }

    async def chat(self, message: str, history: list[dict], context: dict[str, Any]) -> dict[str, Any]:
        """
        Process a chat message (OSS stub returns unavailable message).

        In hybrid/enterprise mode, this would send the chat to the cloud AI service.
        """
        logger.debug(f"SherpaAdvisor.chat called with message: {message[:50]}... (stub mode)")
        return {
            "response": "Sherpa AI chat is not available in OSS mode. Activate hybrid mode to use AI-powered assistance.",
            "available": False,
            "suggestions": [],
        }

    def is_available(self) -> bool:
        """Check if Sherpa AI service is available."""
        return False  # Always False in OSS stub mode


# Global singleton instance
_advisor: SherpaAdvisor | None = None


def get_sherpa_advisor() -> SherpaAdvisor:
    """
    Get the global Sherpa AI Advisor instance.

    Returns:
        SherpaAdvisor stub in OSS mode, or full implementation if injected by spectra-server
    """
    global _advisor
    if _advisor is None:
        _advisor = SherpaAdvisor()
    return _advisor


def set_sherpa_advisor(advisor: SherpaAdvisor):
    """
    Inject a custom Sherpa AI Advisor implementation.

    Used by spectra-server to replace the OSS stub with a full cloud-connected implementation.

    Args:
        advisor: Custom SherpaAdvisor instance
    """
    global _advisor
    _advisor = advisor
    logger.info("SherpaAdvisor: custom implementation injected")


def reset_sherpa_advisor():
    """Reset to OSS stub mode (for testing)."""
    global _advisor
    _advisor = None
