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
from collections.abc import AsyncGenerator, AsyncIterator
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


class SherpaAuthorizationError(Exception):
    """Raised when the Sherpa deployment key is invalid, revoked, or unauthorized."""

    def __init__(self, detail: str = "Sherpa authorization failed"):
        self.detail = detail
        super().__init__(detail)


class SherpaAdvisor:
    """
    Stub implementation of Sherpa AI Advisor.

    In OSS mode, all features return False/disabled state.
    spectra-server can inject a full implementation that connects to cloud AI services.
    """

    # Shared timeout configs — keep connect/write snappy, allow generous read
    # for LLM generation latency (first-token wait + long completions).
    UNARY_TIMEOUT = httpx.Timeout(connect=30.0, read=120.0, write=30.0, pool=30.0)
    STREAM_TIMEOUT = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)

    def __init__(self):
        """Initialize advisor proxy with optional server-backed availability."""
        from spectra_sherpa.app.services.spectrasherpa import spectrasherpa_config

        self._features: set[str] = set()
        self._config = spectrasherpa_config
        # Shared httpx client for connection reuse (TLS session, keep-alive)
        self._client: httpx.AsyncClient | None = None
        logger.debug("SherpaAdvisor initialized")

    def _get_client(self, *, streaming: bool = False) -> httpx.AsyncClient:
        """Return a shared httpx client, creating one if needed.

        The client is long-lived for connection reuse.  Streaming requests
        use a separate per-call client because httpx streaming holds a
        connection for the entire generator lifetime.
        """
        if streaming:
            # Streaming calls need their own client — the connection is held
            # open for the duration of the async generator.
            return httpx.AsyncClient(timeout=self.STREAM_TIMEOUT)
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.UNARY_TIMEOUT)
        return self._client

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

    @classmethod
    def _raise_for_status(cls, response: httpx.Response) -> None:
        detail = cls._extract_detail(response)
        if response.status_code == 402:
            raise SubscriptionRequiredError(detail)
        if response.status_code in {401, 403}:
            raise SherpaAuthorizationError(detail)
        if response.status_code >= 400:
            raise RuntimeError(detail)

    @staticmethod
    def _parse_sse_data_line(line: str) -> str | None:
        if not line.startswith("data:"):
            return None
        payload = line[5:]
        return payload[1:] if payload.startswith(" ") else payload

    @staticmethod
    def _decode_sse_event(data_lines: list[str]) -> dict[str, Any] | None:
        if not data_lines:
            return None
        raw_payload = "\n".join(data_lines)
        try:
            event = json.loads(raw_payload)
        except json.JSONDecodeError:
            return None
        return event if isinstance(event, dict) else None

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
            client = self._get_client(streaming=False)
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

        self._raise_for_status(response)

        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Sherpa server returned an invalid response")
        return payload

    async def _stream_sse(
        self,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        self._ensure_configured()

        try:
            async with self._get_client(streaming=True) as client:
                async with client.stream(
                    "POST",
                    f"{self._base_url}{path}",
                    json=json_body,
                    headers=self._headers,
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        self._raise_for_status(response)

                    line_stream = response.aiter_lines()
                    data_lines: list[str] = []
                    try:
                        async for line in line_stream:
                            if line.startswith(":"):
                                continue

                            if line == "":
                                event = self._decode_sse_event(data_lines)
                                data_lines.clear()
                                if event is None:
                                    continue
                                yield event
                                continue

                            data_line = self._parse_sse_data_line(line)
                            if data_line is not None:
                                data_lines.append(data_line)

                        trailing_event = self._decode_sse_event(data_lines)
                        if trailing_event is not None:
                            yield trailing_event
                    finally:
                        aclose = getattr(line_stream, "aclose", None)
                        if callable(aclose):
                            await aclose()
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
        stream = self._stream_sse("/sherpa/chat", json_body=body)
        try:
            async for event in stream:
                event_type = event.get("type")
                if event_type == "chunk":
                    yield str(event.get("text", ""))
                elif event_type == "done":
                    return
                elif event_type == "error":
                    raise RuntimeError(str(event.get("detail", "Sherpa chat failed.")))
        finally:
            await stream.aclose()

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

    async def generate_data_story(
        self,
        *,
        dataset_info: dict[str, Any],
        additional_context: str | None = None,
    ) -> dict[str, Any]:
        """Proxy data story generation to the Sherpa server."""
        payload = await self._request_json(
            "POST",
            "/sherpa/data-story",
            json_body={
                "dataset_info": dataset_info,
                "additional_context": additional_context,
            },
        )
        response = payload.get("response", "")
        return {"response": response}

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
        stream = self._stream_sse("/sherpa/chat-with-tools", json_body=body)
        try:
            async for event in stream:
                if event.get("type") == "done":
                    return
                yield event
        finally:
            await stream.aclose()


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
