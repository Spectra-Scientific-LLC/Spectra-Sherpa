from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any

import httpx

from spectra_sherpa.app.services.ai_provider_errors import (
    SherpaAuthorizationError,
    SubscriptionRequiredError,
)

logger = logging.getLogger(__name__)


class DeploymentAIProvider:
    """Remote deployment-key-backed AI provider for OSS hybrid clients."""

    UNARY_TIMEOUT = httpx.Timeout(connect=30.0, read=120.0, write=30.0, pool=30.0)
    STREAM_TIMEOUT = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)

    def __init__(self):
        from spectra_sherpa.app.services.spectrasherpa import spectrasherpa_config

        self._features: set[str] = set()
        self._config = spectrasherpa_config
        self._client: httpx.AsyncClient | None = None
        logger.debug("DeploymentAIProvider initialized")

    def _get_client(self, *, streaming: bool = False) -> httpx.AsyncClient:
        if streaming:
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

    @property
    def is_available(self) -> bool:
        return bool(self._config.api_key)

    def has_feature(self, feature: str) -> bool:
        return feature in self._features

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
                                if event is not None:
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

    async def stream_llm_chat(
        self,
        *,
        message: str,
        conversation_id: str | None = None,
        workflow_context: dict[str, Any] | None = None,
        local_user_id: int | None = None,
        project_id: int | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        body = {
            "message": message,
            "conversation_id": conversation_id,
            "workflow_context": workflow_context,
            "local_user_id": local_user_id,
            "project_id": project_id,
        }
        async for event in self._stream_sse("/sherpa/chat", json_body=body):
            yield event
            if event.get("type") in ("done", "error"):
                return

    async def sync_workflow(self, sync_msg: Any, *, tier: Any) -> list[Any]:
        from spectra_sherpa.app.schemas.sherpa import SherpaRecommendation

        body = sync_msg.model_dump(mode="json")
        body["tier"] = getattr(tier, "value", tier)
        payload = await self._request_json("POST", "/sherpa/sync", json_body=body)
        recommendations = payload.get("recommendations", [])
        if not isinstance(recommendations, list):
            return []
        return [SherpaRecommendation(**item) for item in recommendations if isinstance(item, dict)]

    async def send_decision(self, decision: Any) -> bool:
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
        payload = await self._request_json(
            "POST",
            "/sherpa/identify-peaks",
            json_body={"wavenumbers": wavenumbers, "absorbance": absorbance},
        )
        return {"response": payload.get("response", "")}

    async def generate_code(self, *, task_description: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = await self._request_json(
            "POST",
            "/sherpa/generate-code",
            json_body={"task_description": task_description, "context": context},
        )
        return {"response": payload.get("response", "")}

    async def write_report(self, *, experiment: dict[str, Any]) -> dict[str, Any]:
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
        payload = await self._request_json(
            "POST",
            "/sherpa/data-story",
            json_body={
                "dataset_info": dataset_info,
                "additional_context": additional_context,
            },
        )
        return {"response": payload.get("response", "")}

    async def chat_with_tools(
        self,
        *,
        message: str,
        history: list[dict[str, str]] | None = None,
        workflow_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
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
