"""Native Anthropic Messages API transport using plain HTTP/SSE."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

from .base import ChatEndpointConfig, ChatRequest

logger = logging.getLogger(__name__)

ANTHROPIC_VERSION = "2023-06-01"
MAX_OUTPUT_CHARS = 32_000
MAX_TOKENS = 1_500


class AnthropicMessagesProvider:
    id = "anthropic"
    requires_key = True

    def request_url(self, endpoint_url: str) -> str:
        base_url = endpoint_url.strip().rstrip("/")
        if base_url.endswith("/v1/messages"):
            return base_url
        if base_url.endswith("/v1"):
            return base_url + "/messages"
        return base_url + "/v1/messages"

    @staticmethod
    def _headers(key: str) -> dict[str, str]:
        return {
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

    @staticmethod
    def _body(config: ChatEndpointConfig, request: ChatRequest, *, stream: bool) -> dict:
        body: dict = {
            "model": config.model,
            "max_tokens": request.max_tokens or MAX_TOKENS,
            "messages": [{"role": "user", "content": request.message}],
            "stream": stream,
        }
        system_prompts: list[str] = [request.system_prompt] if request.system_prompt else []
        if not request.verbose:
            count = max(1, request.max_paragraphs)
            noun = "paragraph" if count == 1 else "paragraphs"
            system_prompts.append(
                "You are a concise scientific assistant. "
                f"Keep every response to at most {count} short {noun}. "
                "Be direct and skip preamble or closing pleasantries."
            )
        workflow_context = (request.metadata or {}).get("workflow_context")
        if isinstance(workflow_context, dict) and isinstance(workflow_context.get("workflow_name"), str):
            system_prompts.append(f"The user is currently viewing the workflow: {workflow_context['workflow_name']}.")
        if system_prompts:
            body["system"] = "\n\n".join(system_prompts)
        return body

    @staticmethod
    def _text_delta(event: dict) -> str | None:
        """Return a text delta or surface an Anthropic SSE error safely."""
        if event.get("type") == "error":
            error = event.get("error")
            error_type = error.get("type", "unknown") if isinstance(error, dict) else "unknown"
            logger.warning("Anthropic endpoint sent streaming error type=%s", error_type)
            raise ValueError("Chat endpoint streaming error.")
        if event.get("type") != "content_block_delta":
            return None
        text = event.get("delta", {}).get("text")
        return text if isinstance(text, str) else None

    async def stream(self, config: ChatEndpointConfig, request: ChatRequest, request_url: str) -> AsyncIterator[str]:
        from spectra_sherpa.app.services.chat_exchange import observe_payload, observe_usage

        body = self._body(config, request, stream=True)
        observe_payload(body)
        async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
            async with client.stream(
                "POST",
                request_url,
                json=body,
                headers=self._headers(config.key),
            ) as response:
                if response.status_code != 200:
                    content = await response.aread()
                    logger.warning(
                        "Anthropic endpoint returned HTTP %d with %d response bytes",
                        response.status_code,
                        len(content),
                    )
                    raise ValueError(f"Chat endpoint error (HTTP {response.status_code})")
                output_chars = 0
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    observe_usage(event.get("usage"))
                    if isinstance(event.get("message"), dict):
                        observe_usage(event["message"].get("usage"))
                    text = self._text_delta(event)
                    if not text:
                        continue
                    output_chars += len(text)
                    if output_chars > MAX_OUTPUT_CHARS:
                        logger.warning("Anthropic endpoint response exceeded %d characters", MAX_OUTPUT_CHARS)
                        yield "\n\n[Response truncated by SpectraSherpa output limit.]"
                        return
                    yield text

    async def test_connection(self, config: ChatEndpointConfig, request_url: str) -> tuple[bool, str]:
        request = ChatRequest(message="Reply with OK.", verbose=True, max_paragraphs=1, metadata=None)
        try:
            async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
                response = await client.post(
                    request_url,
                    json=self._body(config, request, stream=False),
                    headers=self._headers(config.key),
                )
        except httpx.TimeoutException:
            return False, "Connection timed out."
        except httpx.ConnectError:
            return False, "Could not connect to the endpoint."
        except httpx.HTTPError as exc:
            logger.warning("Anthropic endpoint connection failed: %s", exc)
            return False, "Connection failed."
        if response.status_code in (401, 403):
            return False, "Authentication failed. Check the API key."
        if response.status_code >= 400:
            return False, f"Endpoint returned HTTP {response.status_code}."
        return True, "Connection successful."
