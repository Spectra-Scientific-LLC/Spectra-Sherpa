"""Minimal BYO chat client for OSS distributions.

This is a thin HTTP proxy to a user-configured chat endpoint. It does NOT
implement ``AIServiceProvider`` and does NOT import any vendor LLM SDKs.
No tools, no persistence, no agent loop.

Configuration (environment variables):
    CHAT_ENDPOINT_URL   Base URL of the OpenAI-compatible chat completions
                        endpoint (e.g. ``https://api.deepseek.com/v1``).
    CHAT_ENDPOINT_KEY   API key sent as ``Authorization: Bearer <key>``.
    CHAT_ENDPOINT_MODEL Model identifier (default: ``deepseek-chat``).
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator

import httpx

logger = logging.getLogger(__name__)

CHAT_ENDPOINT_URL = os.getenv("CHAT_ENDPOINT_URL", "")
CHAT_ENDPOINT_KEY = os.getenv("CHAT_ENDPOINT_KEY", "")
CHAT_ENDPOINT_MODEL = os.getenv("CHAT_ENDPOINT_MODEL", "deepseek-chat")


def is_configured() -> bool:
    """Return True when the BYO chat endpoint has both URL and key set."""
    return bool(CHAT_ENDPOINT_URL and CHAT_ENDPOINT_KEY)


async def stream_chat(message: str) -> AsyncIterator[str]:
    """Stream a single-turn chat completion from the configured endpoint.

    Yields text chunks as they arrive. Raises ``ValueError`` if the
    endpoint is not configured.
    """
    if not is_configured():
        raise ValueError(
            "BYO chat endpoint not configured. " "Set CHAT_ENDPOINT_URL and CHAT_ENDPOINT_KEY environment variables."
        )

    url = CHAT_ENDPOINT_URL.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {CHAT_ENDPOINT_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": CHAT_ENDPOINT_MODEL,
        "messages": [{"role": "user", "content": message}],
        "stream": True,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, json=body, headers=headers) as response:
            if response.status_code != 200:
                text = await response.aread()
                logger.warning("Chat endpoint returned %d: %s", response.status_code, text[:500])
                raise ValueError(f"Chat endpoint error (HTTP {response.status_code})")

            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    return

                import json

                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue

                delta = chunk.get("choices", [{}])[0].get("delta", {})
                text = delta.get("content")
                if text:
                    yield text
