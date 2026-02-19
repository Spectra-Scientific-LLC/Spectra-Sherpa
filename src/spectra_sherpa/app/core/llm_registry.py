"""
LLM Provider Registry - Single Source of Truth

Centralized registry for all supported LLM providers.
Defines configurations, capabilities, and metadata for each provider.
"""

from typing import Literal, TypedDict


class ProviderMetadata(TypedDict):
    """Complete provider configuration"""

    id: str  # Provider identifier
    name: str  # Human-readable name
    default_model: str  # Default model to use
    base_url: str  # API endpoint
    env_var: str  # Environment variable name
    client_type: Literal["openai", "anthropic"]  # SDK type to use
    supports_streaming: bool  # Streaming capability
    cost_per_million_input: float  # Cost in USD per million input tokens
    cost_per_million_output: float  # Cost in USD per million output tokens
    max_tokens: int  # Maximum context window
    supports_vision: bool  # Image input support
    supports_function_calling: bool  # Tool use support


# Complete provider registry
PROVIDERS: dict[str, ProviderMetadata] = {
    "openai": {
        "id": "openai",
        "name": "OpenAI",
        "default_model": "gpt-4o",
        "base_url": "https://api.openai.com/v1",
        "env_var": "OPENAI_API_KEY",
        "client_type": "openai",
        "supports_streaming": True,
        "cost_per_million_input": 2.50,
        "cost_per_million_output": 10.00,
        "max_tokens": 128000,
        "supports_vision": True,
        "supports_function_calling": True,
    },
    "anthropic": {
        "id": "anthropic",
        "name": "Anthropic (Claude)",
        "default_model": "claude-sonnet-4-5-20250929",
        "base_url": "https://api.anthropic.com",
        "env_var": "ANTHROPIC_API_KEY",
        "client_type": "anthropic",
        "supports_streaming": True,
        "cost_per_million_input": 3.00,
        "cost_per_million_output": 15.00,
        "max_tokens": 200000,
        "supports_vision": True,
        "supports_function_calling": True,
    },
    "deepseek": {
        "id": "deepseek",
        "name": "DeepSeek",
        "default_model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "env_var": "DEEPSEEK_API_KEY",
        "client_type": "openai",  # OpenAI-compatible API
        "supports_streaming": True,
        "cost_per_million_input": 0.27,
        "cost_per_million_output": 1.10,
        "max_tokens": 64000,
        "supports_vision": False,
        "supports_function_calling": True,
    },
    "gemini": {
        "id": "gemini",
        "name": "Google Gemini",
        "default_model": "gemini-1.5-pro",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "env_var": "GEMINI_API_KEY",
        "client_type": "openai",  # OpenAI-compatible API
        "supports_streaming": True,
        "cost_per_million_input": 1.25,
        "cost_per_million_output": 5.00,
        "max_tokens": 2000000,
        "supports_vision": True,
        "supports_function_calling": True,
    },
    "custom_llm": {
        "id": "custom_llm",
        "name": "Custom LLM (OpenAI-compatible)",
        "default_model": "custom-model",
        "base_url": "",  # Must be provided by user via LLM config.
        "env_var": "CUSTOM_LLM_API_KEY",
        "client_type": "openai",
        "supports_streaming": True,
        "cost_per_million_input": 0.0,
        "cost_per_million_output": 0.0,
        "max_tokens": 128000,
        "supports_vision": False,
        "supports_function_calling": True,
    },
}


def get_provider(provider_id: str) -> ProviderMetadata:
    """
    Get provider metadata by ID.

    Args:
        provider_id: Provider identifier (e.g., 'openai', 'anthropic')

    Returns:
        Provider metadata dictionary

    Raises:
        ValueError: If provider_id is not recognized
    """
    if provider_id not in PROVIDERS:
        available = ", ".join(PROVIDERS.keys())
        raise ValueError(f"Unknown provider: {provider_id}. " f"Available providers: {available}")
    return PROVIDERS[provider_id]


def list_providers() -> list[str]:
    """
    Get list of all supported provider IDs.

    Returns:
        List of provider identifiers
    """
    return list(PROVIDERS.keys())


def get_default_provider() -> str:
    """
    Get default provider ID from environment or fallback to DeepSeek.

    Returns:
        Default provider identifier
    """
    import os

    provider = os.getenv("LLM_PROVIDER", "deepseek")

    # Validate that the provider exists
    if provider not in PROVIDERS:
        import logging

        logging.getLogger(__name__).warning(f"Invalid LLM_PROVIDER={provider}, falling back to deepseek")
        return "deepseek"

    return provider
