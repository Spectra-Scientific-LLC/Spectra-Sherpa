"""Plain-HTTP transports for the local bring-your-own assistant.

These modules deliberately have no vendor SDK dependency.  They speak only
the public HTTP/SSE protocols needed by the local, single-turn chat surface.
"""

from .base import ChatEndpointConfig, ChatRequest
from .registry import get_chat_provider

__all__ = ["ChatEndpointConfig", "ChatRequest", "get_chat_provider"]
