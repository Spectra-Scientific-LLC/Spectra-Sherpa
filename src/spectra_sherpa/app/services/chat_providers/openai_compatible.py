"""OpenAI Chat Completions-compatible local-assistance transport."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator

import httpx

from .base import ChatEndpointConfig, ChatRequest

logger = logging.getLogger(__name__)

MAX_OUTPUT_CHARS = 32_000
MAX_TOKENS = 1_500


def _brief_system_prompt(max_paragraphs: int) -> str:
    count = max(1, max_paragraphs)
    noun = "paragraph" if count == 1 else "paragraphs"
    return (
        "You are a concise scientific assistant. "
        f"Keep every response to at most {count} short {noun}. "
        "Be direct and skip preamble or closing pleasantries."
    )


class OpenAICompatibleProvider:
    id = "openai_compatible"
    requires_key = True

    def request_url(self, endpoint_url: str) -> str:
        base_url = endpoint_url.strip().rstrip("/")
        return base_url if base_url.endswith("/chat/completions") else base_url + "/chat/completions"

    @staticmethod
    def _headers(key: str) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    @staticmethod
    def _messages(request: ChatRequest) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        if not request.verbose:
            messages.append({"role": "system", "content": _brief_system_prompt(request.max_paragraphs)})
        workflow_context = (request.metadata or {}).get("workflow_context")
        if isinstance(workflow_context, dict) and isinstance(workflow_context.get("workflow_name"), str):
            messages.append(
                {
                    "role": "system",
                    "content": f"The user is currently viewing the workflow: {workflow_context['workflow_name']}.",
                }
            )
        messages.append({"role": "user", "content": request.message})
        return messages

    async def stream(self, config: ChatEndpointConfig, request: ChatRequest, request_url: str) -> AsyncIterator[str]:
        body = {
            "model": config.model,
            "messages": self._messages(request),
            "stream": True,
            "max_tokens": request.max_tokens or MAX_TOKENS,
        }
        from spectra_sherpa.app.services.chat_exchange import observe_payload, observe_usage

        observe_payload(body)
        async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
            async with client.stream("POST", request_url, json=body, headers=self._headers(config.key)) as response:
                if response.status_code != 200:
                    content = await response.aread()
                    logger.warning(
                        "BYO chat endpoint returned HTTP %d with %d response bytes",
                        response.status_code,
                        len(content),
                    )
                    raise ValueError(f"Chat endpoint error (HTTP {response.status_code})")
                output_chars = 0
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    observe_usage(chunk.get("usage"))
                    choices = chunk.get("choices") or [{}]
                    text = choices[0].get("delta", {}).get("content")
                    if not text:
                        continue
                    output_chars += len(text)
                    if output_chars > MAX_OUTPUT_CHARS:
                        logger.warning("Chat endpoint response exceeded %d characters", MAX_OUTPUT_CHARS)
                        yield "\n\n[Response truncated by SpectraSherpa output limit.]"
                        return
                    yield text

    async def test_connection(self, config: ChatEndpointConfig, request_url: str) -> tuple[bool, str]:
        body = {
            "model": config.model,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "stream": False,
            "max_tokens": 8,
        }
        return await _post_test(request_url, body, self._headers(config.key))


class OllamaProvider(OpenAICompatibleProvider):
    """Ollama's documented OpenAI-compatibility endpoint without an API key."""

    id = "ollama"
    requires_key = False

    @staticmethod
    def _headers(_key: str) -> dict[str, str]:
        """Ollama is keyless; never forward a previously configured key."""
        return {"Content-Type": "application/json"}


async def _post_test(url: str, body: dict, headers: dict[str, str]) -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            response = await client.post(url, json=body, headers=headers)
    except httpx.TimeoutException:
        return False, "Connection timed out."
    except httpx.ConnectError:
        return False, "Could not connect to the endpoint."
    except httpx.HTTPError as exc:
        logger.warning("BYO chat endpoint connection failed: %s", exc)
        return False, "Connection failed."
    if response.status_code in (401, 403):
        return False, "Authentication failed. Check the API key."
    if response.status_code >= 400:
        return False, f"Endpoint returned HTTP {response.status_code}."
    return True, "Connection successful."
