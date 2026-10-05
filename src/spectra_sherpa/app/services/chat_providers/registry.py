"""Supported local-assistance provider families."""

from __future__ import annotations

from .anthropic import AnthropicMessagesProvider
from .base import ChatProvider
from .openai_compatible import OllamaProvider, OpenAICompatibleProvider

_PROVIDERS: dict[str, ChatProvider] = {
    "openai_compatible": OpenAICompatibleProvider(),
    "anthropic": AnthropicMessagesProvider(),
    "ollama": OllamaProvider(),
}


def get_chat_provider(provider_id: str) -> ChatProvider:
    """Return a known local-assistance provider or a stable config error."""
    try:
        return _PROVIDERS[provider_id]
    except KeyError as exc:
        raise ValueError("Unsupported chat provider.") from exc
