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
from urllib.parse import urlparse, urlunparse

import httpx

logger = logging.getLogger(__name__)

MAX_INPUT_CHARS = 16_000
MAX_OUTPUT_CHARS = 32_000
MAX_TOKENS = 1_500

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


def validate_endpoint_url(endpoint_url: str) -> tuple[bool, str]:
    """Validate the configured OpenAI-compatible endpoint base URL."""
    ok, reason, _url = validated_chat_completions_url(endpoint_url)
    return ok, reason


def validated_chat_completions_url(endpoint_url: str) -> tuple[bool, str, str | None]:
    """Validate and canonicalize an OpenAI-compatible chat completions URL."""
    base_url = endpoint_url.strip().rstrip("/")
    if not base_url:
        return False, "API base URL is required.", None
    parsed = urlparse(base_url)
    path = parsed.path.rstrip("/") + "/chat/completions"
    request_url = urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))
    ok, reason = _is_safe_outbound_url(request_url)
    return (ok, reason, request_url if ok else None)


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
    if len(message) > MAX_INPUT_CHARS:
        raise ValueError("Chat message is too long.")

    config = get_config()
    url = config.url.rstrip("/") + "/chat/completions"
    ok, reason = _is_safe_outbound_url(url)
    if not ok:
        raise ValueError(reason)

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
        "max_tokens": MAX_TOKENS,
    }

    async with httpx.AsyncClient(timeout=120.0, trust_env=False) as client:
        async with client.stream("POST", url, json=body, headers=headers) as response:
            if response.status_code != 200:
                text = await response.aread()
                logger.warning(
                    "Chat endpoint returned HTTP %d with %d response bytes",
                    response.status_code,
                    len(text),
                )
                raise ValueError(f"Chat endpoint error (HTTP {response.status_code})")

            output_chars = 0
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
                    output_chars += len(text)
                    if output_chars > MAX_OUTPUT_CHARS:
                        logger.warning("Chat endpoint response exceeded %d characters", MAX_OUTPUT_CHARS)
                        yield "\n\n[Response truncated by SpectraSherpa output limit.]"
                        return
                    yield text


async def test_connection(
    endpoint_url: str,
    endpoint_key: str,
    model: str,
) -> tuple[bool, str]:
    """Validate an OpenAI-compatible BYO chat endpoint without saving it."""
    key = endpoint_key.strip()
    if not key:
        return False, "API key is required."

    ok, reason, url = validated_chat_completions_url(endpoint_url)
    if not ok or url is None:
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
        async with httpx.AsyncClient(timeout=15.0, trust_env=False) as client:
            # ``url`` is produced only by validated_chat_completions_url(),
            # which rejects non-http(s), private, loopback, link-local,
            # reserved, multicast, and unspecified addresses unless the
            # local-LLM escape hatch is explicitly enabled.
            # lgtm[py/full-ssrf]
            response = await client.post(url, json=body, headers=headers)
    except httpx.TimeoutException:
        return False, "Connection timed out."
    except httpx.ConnectError:
        return False, "Could not connect to the endpoint."
    except httpx.HTTPError as exc:
        # Log the full exception server-side so connectivity bugs stay
        # debuggable; the returned message is generic to avoid leaking
        # internal details (e.g. credential-bearing URLs in the request
        # exception's stringification) to the validator caller.
        logger.warning("BYO chat endpoint connection failed: %s", exc)
        return False, "Connection failed."

    if response.status_code in (401, 403):
        return False, "Authentication failed. Check the API key."
    if response.status_code >= 400:
        return False, f"Endpoint returned HTTP {response.status_code}."
    return True, "Connection successful."
