"""Shared local-assistance transport types."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ChatEndpointConfig:
    """A user-controlled local-assistance endpoint, never a managed service."""

    provider: str
    url: str
    key: str
    model: str
    allow_private_endpoint: bool = False


@dataclass(frozen=True)
class ChatRequest:
    message: str
    verbose: bool
    max_paragraphs: int
    metadata: dict | None
    system_prompt: str | None = None
    max_tokens: int | None = None


class ChatProvider(Protocol):
    """Protocol implemented by a supported plain-HTTP provider family."""

    id: str
    requires_key: bool

    def request_url(self, endpoint_url: str) -> str:
        """Canonical request URL from the configured provider base URL."""

    def stream(self, config: ChatEndpointConfig, request: ChatRequest, request_url: str) -> AsyncIterator[str]:
        """Yield provider text deltas from an SSE response."""

    async def test_connection(self, config: ChatEndpointConfig, request_url: str) -> tuple[bool, str]:
        """Perform a minimal, non-streaming provider-specific validation request."""
