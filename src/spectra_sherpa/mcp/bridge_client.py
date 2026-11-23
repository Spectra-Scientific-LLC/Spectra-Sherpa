"""Bounded loopback HTTP client for an already authorized Workbench connection."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from spectra_sherpa.mcp.refusals import REFUSALS, refusal_text

MAX_REQUEST_BYTES = 8192
MAX_RESPONSE_BYTES = 64 * 1024


async def _refusal_code(response) -> str:
    """Map a refused call to a fixed refusal code; never echo the server's text."""
    if response.status_code in (401, 403):
        return "access_denied"
    if response.status_code == 408:
        return "timeout"
    if response.status_code == 429:
        return "busy"
    try:
        raw = await response.aread()
        detail = json.loads(raw[:4096]).get("detail") if len(raw) <= 4096 else None
    except (ValueError, UnicodeError, AttributeError):
        detail = None
    return detail if isinstance(detail, str) and detail in REFUSALS else "inspection_failed"


class BridgeUnavailable(ValueError):
    """Fixed public error, never the server response or credential-bearing URL."""


@dataclass(frozen=True)
class Connection:
    base_url: str
    project_id: int
    client_id: str
    credential: str = field(repr=False)

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Workbench URL must be an HTTP loopback IP origin")
        try:
            port = parsed.port
            valid_client = str(UUID(self.client_id)) == self.client_id
        except (ValueError, TypeError, AttributeError) as exc:
            raise ValueError("Invalid inspection connection") from exc
        if port == 0 or not valid_client or type(self.project_id) is not int or self.project_id < 1:
            raise ValueError("Invalid inspection connection")
        if not re.fullmatch(r"ssmcp_[A-Za-z0-9_-]{43}", self.credential):
            raise ValueError("Invalid inspection credential")

    @property
    def call_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/v1/inspection/{self.project_id}/{self.client_id}/call"


async def inspect(connection: Connection, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
    # Transport-level selection is defense in depth; Workbench admission remains
    # authoritative and independently rejects unregistered or disallowed calls.
    from spectra_sherpa.app.services.inspection_bridge import OPERATIONS

    if operation not in OPERATIONS:
        raise BridgeUnavailable(refusal_text("unsupported_operation"))
    try:
        payload = json.dumps({"operation": operation, "arguments": arguments}, allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError) as exc:
        raise BridgeUnavailable(refusal_text("invalid_arguments")) from exc
    if len(payload) > MAX_REQUEST_BYTES:
        raise BridgeUnavailable(refusal_text("request_limit"))
    try:
        # Never send the credential to an environment proxy or follow redirects.
        async with (
            asyncio.timeout(30),
            httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=25) as client,
        ):
            async with client.stream(
                "POST",
                connection.call_url,
                content=payload,
                headers={"Authorization": f"Bearer {connection.credential}", "Content-Type": "application/json"},
            ) as response:
                if response.status_code != 200:
                    raise BridgeUnavailable(refusal_text(await _refusal_code(response)))
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise BridgeUnavailable(refusal_text("response_limit"))
                    body.extend(chunk)
    except (httpx.HTTPError, TimeoutError) as exc:
        raise BridgeUnavailable(refusal_text("unavailable")) from exc
    try:
        result = json.loads(body)
    except (ValueError, UnicodeError) as exc:
        raise BridgeUnavailable(refusal_text("invalid_response")) from exc
    if not isinstance(result, dict):
        raise BridgeUnavailable(refusal_text("invalid_response"))
    return result
