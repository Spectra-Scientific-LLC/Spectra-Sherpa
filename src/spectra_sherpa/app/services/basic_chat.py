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

import ipaddress
import logging
import os
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

CHAT_ENDPOINT_URL = os.getenv("CHAT_ENDPOINT_URL", "")
CHAT_ENDPOINT_KEY = os.getenv("CHAT_ENDPOINT_KEY", "")
CHAT_ENDPOINT_MODEL = os.getenv("CHAT_ENDPOINT_MODEL", "deepseek-chat")


@dataclass(frozen=True)
class ChatEndpointConfig:
    url: str
    key: str
    model: str


_ALLOW_PRIVATE_ENV = "SPECTRA_SHERPA_ALLOW_PRIVATE_LLM_ENDPOINTS"


def _is_safe_outbound_url(url: str) -> tuple[bool, str]:
    """Return ``(ok, reason)`` for a user-supplied outbound URL.

    Used to defend the BYO chat endpoint validator against SSRF when the
    server-side process makes the request: a user could otherwise pass
    ``http://169.254.169.254/`` (cloud metadata) or ``http://localhost``
    addresses and turn the validator into a confused deputy.

    The check rejects:
      - non-``http(s)`` schemes (``file://``, ``gopher://``, etc.)
      - hostnames that resolve into private/loopback/link-local /
        multicast / reserved / unspecified IP ranges

    Set ``SPECTRA_SHERPA_ALLOW_PRIVATE_LLM_ENDPOINTS=true`` to bypass the
    private-IP check; that is intended for OSS users running their own
    local LLM (e.g. Ollama on ``localhost:11434``) where the SSRF threat
    model does not apply.
    """
    try:
        parsed = urlparse(url)
    except Exception:  # pragma: no cover — defensive
        return False, "URL could not be parsed."
    if parsed.scheme not in ("http", "https"):
        return False, "Only http(s) URLs are allowed."
    host = parsed.hostname
    if not host:
        return False, "URL must include a host."

    if os.getenv(_ALLOW_PRIVATE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}:
        return True, ""

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False, "Hostname could not be resolved."

    for info in infos:
        addr_str = info[4][0]
        try:
            ip = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False, "Endpoint resolves to a private or restricted IP address."
    return True, ""


def get_config() -> ChatEndpointConfig:
    """Read BYO chat configuration at request time.

    The settings endpoint updates ``os.environ`` after writing ``.env``. Reading
    here avoids ``importlib.reload()`` races while streams are in flight.
    """
    return ChatEndpointConfig(
        url=os.getenv("CHAT_ENDPOINT_URL", CHAT_ENDPOINT_URL),
        key=os.getenv("CHAT_ENDPOINT_KEY", CHAT_ENDPOINT_KEY),
        model=os.getenv("CHAT_ENDPOINT_MODEL", CHAT_ENDPOINT_MODEL),
    )


def is_configured() -> bool:
    """Return True when the BYO chat endpoint has both URL and key set."""
    config = get_config()
    return bool(config.url and config.key)


def _brief_system_prompt(max_paragraphs: int) -> str:
    p = max(1, max_paragraphs)
    noun = "paragraph" if p == 1 else "paragraphs"
    return (
        "You are a concise scientific assistant. "
        f"Keep every response to at most {p} short {noun}. "
        "Be direct and skip preamble or closing pleasantries."
    )


async def stream_chat(
    message: str, *, verbose: bool = True, max_paragraphs: int = 2, metadata: dict | None = None
) -> AsyncIterator[str]:
    """Stream a single-turn chat completion from the configured endpoint.

    Yields text chunks as they arrive. Raises ``ValueError`` if the
    endpoint is not configured.
    """
    if not is_configured():
        raise ValueError(
            "BYO chat endpoint not configured. " "Set CHAT_ENDPOINT_URL and CHAT_ENDPOINT_KEY environment variables."
        )

    config = get_config()
    url = config.url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.key}",
        "Content-Type": "application/json",
    }
    messages: list[dict] = []
    if not verbose:
        messages.append({"role": "system", "content": _brief_system_prompt(max_paragraphs)})
    if metadata and "workflow_context" in metadata:
        wf_ctx = metadata["workflow_context"]
        if isinstance(wf_ctx, dict) and "workflow_name" in wf_ctx:
            wf_name = wf_ctx["workflow_name"]
            messages.append({"role": "system", "content": f"The user is currently viewing the workflow: {wf_name}."})
    messages.append({"role": "user", "content": message})
    body = {
        "model": config.model,
        "messages": messages,
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


async def test_connection(
    endpoint_url: str,
    endpoint_key: str,
    model: str,
) -> tuple[bool, str]:
    """Validate an OpenAI-compatible BYO chat endpoint without saving it."""
    url = endpoint_url.strip().rstrip("/") + "/chat/completions"
    key = endpoint_key.strip()
    if not endpoint_url.strip():
        return False, "API base URL is required."
    if not key:
        return False, "API key is required."

    ok, reason = _is_safe_outbound_url(url)
    if not ok:
        return False, reason

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model.strip() or "deepseek-chat",
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "stream": False,
        "max_tokens": 8,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=body, headers=headers)
    except httpx.TimeoutException:
        return False, "Connection timed out."
    except httpx.ConnectError:
        return False, "Could not connect to the endpoint."
    except httpx.HTTPError as exc:
        return False, f"Connection failed: {exc}"

    if response.status_code in (401, 403):
        return False, "Authentication failed. Check the API key."
    if response.status_code >= 400:
        return False, f"Endpoint returned HTTP {response.status_code}."
    return True, "Connection successful."
