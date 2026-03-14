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

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx

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
        """Initialize advisor proxy with optional server-backed availability."""
        from spectra_sherpa.app.services.spectrasherpa import spectrasherpa_config

        self._features = set()
        self._config = spectrasherpa_config
        logger.debug("SherpaAdvisor initialized")

    @property
    def _base_url(self) -> str:
        base_url = self._config.api_base_url.rstrip("/")
        if not base_url.endswith("/api/v1"):
            base_url = f"{base_url}/api/v1"
        return base_url

    @property
    def _headers(self) -> dict[str, str]:
        api_key = self._config.api_key
        return {"X-Deployment-Key": api_key} if api_key else {}

    @staticmethod
    def _extract_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except (ValueError, httpx.ResponseNotRead):
            text = response.text.strip() if response.is_closed else ""
            return text or f"Server returned {response.status_code}"

        detail = payload.get("detail") if isinstance(payload, dict) else None
        if isinstance(detail, dict):
            message = detail.get("message")
            if isinstance(message, str) and message.strip():
                return message
            return json.dumps(detail)
        if isinstance(detail, str) and detail.strip():
            return detail
        return f"Server returned {response.status_code}"

    def _ensure_configured(self) -> None:
        if not self.is_available:
            raise RuntimeError("Sherpa server is not configured. Set SPECTRASHERPA_API_KEY.")

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._ensure_configured()

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.request(
                    method,
                    f"{self._base_url}{path}",
                    json=json_body,
                    headers=self._headers,
                )
        except httpx.ConnectError as exc:
            raise RuntimeError("Cannot connect to SpectraSherpa server") from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError("Sherpa request timed out") from exc

        if response.status_code in {401, 402, 403}:
            raise SubscriptionRequiredError(self._extract_detail(response))
        if response.status_code >= 400:
            raise RuntimeError(self._extract_detail(response))

        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Sherpa server returned an invalid response")
        return payload

    async def _stream_sse(
        self,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        self._ensure_configured()

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}{path}",
                    json=json_body,
                    headers=self._headers,
                ) as response:
                    if response.status_code in {401, 402, 403}:
                        await response.aread()
                        raise SubscriptionRequiredError(self._extract_detail(response))
                    if response.status_code >= 400:
                        await response.aread()
                        raise RuntimeError(self._extract_detail(response))

                    async for line in response.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        try:
                            event = json.loads(line[6:])
                        except json.JSONDecodeError:
                            continue
                        if isinstance(event, dict):
                            yield event
        except httpx.ConnectError as exc:
            raise RuntimeError("Cannot connect to SpectraSherpa server") from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError("Sherpa request timed out") from exc

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
            "response": (
                "Sherpa AI chat is not available in OSS mode. " "Activate hybrid mode to use AI-powered assistance."
            ),
            "available": False,
            "suggestions": [],
        }

    @property
    def is_available(self) -> bool:
        """Check if server-backed Sherpa features are configured."""
        return bool(self._config.api_key)

    async def sync_workflow(self, sync_msg: Any, *, tier: Any) -> list[Any]:
        """Proxy workflow sync to the Sherpa server."""
        from spectra_sherpa.app.schemas.sherpa import SherpaRecommendation

        body = sync_msg.model_dump(mode="json")
        body["tier"] = getattr(tier, "value", tier)
        payload = await self._request_json("POST", "/sherpa/sync", json_body=body)
        recommendations = payload.get("recommendations", [])
        if not isinstance(recommendations, list):
            return []
        return [SherpaRecommendation(**item) for item in recommendations if isinstance(item, dict)]

    async def send_decision(self, decision: Any) -> bool:
        """Proxy user decision acknowledgement to the Sherpa server."""
        payload = await self._request_json(
            "POST",
            "/sherpa/decide",
            json_body=decision.model_dump(mode="json"),
        )
        return bool(payload.get("success"))

    async def chat_followup(
        self,
        *,
        message: str,
        workflow_id: int | None = None,
        history: list[dict[str, str]] | None = None,
        workflow_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Stream follow-up Sherpa chat chunks from the server."""
        body = {
            "message": message,
            "workflow_id": workflow_id,
            "history": history or [],
            "workflow_context": workflow_context,
        }
        async for event in self._stream_sse("/sherpa/chat", json_body=body):
            event_type = event.get("type")
            if event_type == "chunk":
                yield str(event.get("text", ""))
            elif event_type == "error":
                raise RuntimeError(str(event.get("detail", "Sherpa chat failed.")))

    async def identify_peaks(self, *, wavenumbers: list[float], absorbance: list[float]) -> dict[str, Any]:
        """Proxy peak identification to the Sherpa server."""
        payload = await self._request_json(
            "POST",
            "/sherpa/identify-peaks",
            json_body={"wavenumbers": wavenumbers, "absorbance": absorbance},
        )
        response = payload.get("response", "")
        return {"response": response}

    async def generate_code(self, *, task_description: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Proxy code generation to the Sherpa server."""
        payload = await self._request_json(
            "POST",
            "/sherpa/generate-code",
            json_body={"task_description": task_description, "context": context},
        )
        response = payload.get("response", "")
        return {"response": response}

    async def write_report(self, *, experiment: dict[str, Any]) -> dict[str, Any]:
        """Proxy report generation to the Sherpa server."""
        payload = await self._request_json(
            "POST",
            "/sherpa/write-report",
            json_body={"experiment": experiment},
        )
        response = payload.get("response", "")
        return {"response": response, "report": response}

    async def chat_with_tools(
        self,
        *,
        message: str,
        history: list[dict[str, str]] | None = None,
        workflow_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream agentic Sherpa chat events from the server."""
        body = {
            "message": message,
            "history": history or [],
            "workflow_context": workflow_context,
        }
        async for event in self._stream_sse("/sherpa/chat-with-tools", json_body=body):
            yield event


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
