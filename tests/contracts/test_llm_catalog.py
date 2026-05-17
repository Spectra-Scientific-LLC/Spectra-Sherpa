"""LLM provider catalog contract.

The catalog made the two historical hard-coded ``PROVIDERS`` dicts
injectable. These tests are a behaviour LOCK: the OSS default
projections must remain byte-identical to the historical dicts so the
``/api/v1/config`` response is unchanged for OSS-only installs, and
injection must be reflected without touching OSS source.
"""

from __future__ import annotations

import pytest

from spectra_sherpa.app.contracts.llm_catalog import (
    LLMProviderMeta,
    get_llm_provider_catalog,
    provider_core_config_dicts,
    provider_route_catalog_dicts,
    reset_llm_provider_catalog,
    set_llm_provider_catalog,
)
from spectra_sherpa.app.core.config import AppConfig, AppMode

# Verbatim copies of the pre-contract inline dicts (the lock target).
HISTORICAL_CORE = {
    "openai": {
        "id": "openai",
        "name": "OpenAI",
        "default_model": "gpt-4o",
        "base_url": "https://api.openai.com/v1",
        "env_var": "OPENAI_API_KEY",
    },
    "anthropic": {
        "id": "anthropic",
        "name": "Anthropic",
        "default_model": "claude-sonnet-4-6",
        "base_url": "https://api.anthropic.com",
        "env_var": "ANTHROPIC_API_KEY",
    },
    "deepseek": {
        "id": "deepseek",
        "name": "DeepSeek",
        "default_model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
        "env_var": "DEEPSEEK_API_KEY",
    },
    "gemini": {
        "id": "gemini",
        "name": "Google Gemini",
        "default_model": "gemini-1.5-pro",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "env_var": "GEMINI_API_KEY",
    },
    "custom_llm": {
        "id": "custom_llm",
        "name": "Custom LLM",
        "default_model": "custom-model",
        "base_url": "",
        "env_var": "CUSTOM_LLM_API_KEY",
    },
}

HISTORICAL_ROUTE = {
    "openai": {
        "id": "openai",
        "name": "OpenAI",
        "default_model": "gpt-4o",
        "env_var": "OPENAI_API_KEY",
        "supports_streaming": True,
        "cost_per_million_input": 2.50,
        "cost_per_million_output": 10.00,
        "supports_vision": True,
    },
    "anthropic": {
        "id": "anthropic",
        "name": "Anthropic",
        "default_model": "claude-sonnet-4-6",
        "env_var": "ANTHROPIC_API_KEY",
        "supports_streaming": True,
        "cost_per_million_input": 3.00,
        "cost_per_million_output": 15.00,
        "supports_vision": True,
    },
    "deepseek": {
        "id": "deepseek",
        "name": "DeepSeek",
        "default_model": "deepseek-chat",
        "env_var": "DEEPSEEK_API_KEY",
        "supports_streaming": True,
        "cost_per_million_input": 0.27,
        "cost_per_million_output": 1.10,
        "supports_vision": False,
    },
    "gemini": {
        "id": "gemini",
        "name": "Google Gemini",
        "default_model": "gemini-1.5-pro",
        "env_var": "GEMINI_API_KEY",
        "supports_streaming": True,
        "cost_per_million_input": 1.25,
        "cost_per_million_output": 5.00,
        "supports_vision": True,
    },
    "custom_llm": {
        "id": "custom_llm",
        "name": "Custom LLM",
        "default_model": "custom-model",
        "env_var": "CUSTOM_LLM_API_KEY",
        "supports_streaming": True,
        "cost_per_million_input": 0.0,
        "cost_per_million_output": 0.0,
        "supports_vision": False,
    },
}


@pytest.fixture(autouse=True)
def _restore_catalog():
    yield
    reset_llm_provider_catalog()


def test_core_projection_byte_identical_to_history():
    assert provider_core_config_dicts() == HISTORICAL_CORE


def test_route_projection_byte_identical_to_history():
    assert provider_route_catalog_dicts() == HISTORICAL_ROUTE


def test_injection_is_reflected_then_reset_restores():
    custom = {
        "acme": LLMProviderMeta(
            id="acme",
            name="Acme",
            default_model="acme-1",
            env_var="ACME_API_KEY",
            base_url="https://api.acme.example",
        )
    }
    set_llm_provider_catalog(custom)
    assert set(get_llm_provider_catalog()) == {"acme"}
    # Both consumer projections reflect the injected catalog live.
    assert set(provider_core_config_dicts()) == {"acme"}
    assert provider_route_catalog_dicts()["acme"]["name"] == "Acme"

    reset_llm_provider_catalog()
    assert provider_core_config_dicts() == HISTORICAL_CORE


def test_get_returns_fresh_copy_not_shared_state():
    a = get_llm_provider_catalog()
    a.clear()
    assert set(get_llm_provider_catalog()) == set(HISTORICAL_CORE)


def test_appmode_is_str_compatible_and_canonical():
    assert AppMode.LOCAL == "local"
    assert AppMode.values() == ("local", "hybrid", "enterprise")
    # str-based enum keeps existing `app_config.mode == "local"` working.
    assert AppMode.HYBRID.value in AppMode.values()


def test_appconfig_accepts_injected_provider_from_env(monkeypatch):
    set_llm_provider_catalog(
        {
            "acme": LLMProviderMeta(
                id="acme",
                name="Acme",
                default_model="acme-1",
                env_var="ACME_API_KEY",
                base_url="https://api.acme.example",
            )
        }
    )
    monkeypatch.setenv("ACME_API_KEY", "test-acme-key")

    config = AppConfig.from_env()

    assert set(config.llms) == {"acme"}
    assert config.llms["acme"].provider == "acme"
    assert config.llms["acme"].is_configured


def test_client_safe_llms_reflect_catalog_injected_after_config_created(monkeypatch):
    config = AppConfig.from_env()
    assert "acme" not in config.llms

    set_llm_provider_catalog(
        {
            "acme": LLMProviderMeta(
                id="acme",
                name="Acme",
                default_model="acme-1",
                env_var="ACME_API_KEY",
                base_url="https://api.acme.example",
            )
        }
    )
    monkeypatch.setenv("ACME_API_KEY", "test-acme-key")

    safe = config.to_client_safe()

    assert set(safe["llms"]) == {"acme"}
    assert safe["llms"]["acme"] == {
        "provider": "acme",
        "model": "acme-1",
        "enabled": True,
    }
