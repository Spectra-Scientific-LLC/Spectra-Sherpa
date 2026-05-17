"""Pluggable LLM provider catalog owned by the commercial server.

OSS ships a static default catalog so a local install can report
provider availability via ``/api/v1/config`` without the server. The
commercial server owns provider *selection policy* — which providers are
offered, their pricing, and default models. Before this contract, that
policy was duplicated in two hard-coded ``PROVIDERS`` dicts
(``core/config.py`` and ``api/v1/routes/config.py``); any server-side
provider-policy change forced an OSS-visible edit to those dicts, so the
public tree churned every time the proprietary catalog moved.

This contract makes the catalog injectable. A server extension calls
:func:`set_llm_provider_catalog` once at startup; OSS reads it via
:func:`get_llm_provider_catalog`. The OSS default is unchanged from the
historical hard-coded values, so behaviour and the ``/config`` response
are byte-identical until a server replaces the catalog.

Typical usage (server extension startup)::

    from spectra_sherpa.app.contracts.llm_catalog import (
        LLMProviderMeta,
        set_llm_provider_catalog,
    )

    set_llm_provider_catalog(
        {"acme": LLMProviderMeta(id="acme", name="Acme", ...)}
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMProviderMeta:
    """One LLM provider's selection-policy metadata.

    This is the stable OSS-facing shape. The server may add providers or
    change pricing/models by injecting a replacement catalog; the OSS
    consumers only ever read these attributes, so the server can evolve
    behind this contract without the OSS tree changing.
    """

    id: str
    name: str
    default_model: str
    env_var: str
    base_url: str = ""
    supports_streaming: bool = True
    supports_vision: bool = False
    cost_per_million_input: float = 0.0
    cost_per_million_output: float = 0.0


# Canonical OSS default. Values reproduce EXACTLY the two historical
# hard-coded PROVIDERS dicts (core/config.py + api/v1/routes/config.py)
# so the /config response stays byte-identical until a server injects a
# replacement. Do not "tidy" these values — they are a behaviour lock.
_OSS_DEFAULT_CATALOG: dict[str, LLMProviderMeta] = {
    "openai": LLMProviderMeta(
        id="openai",
        name="OpenAI",
        default_model="gpt-4o",
        env_var="OPENAI_API_KEY",
        base_url="https://api.openai.com/v1",
        supports_streaming=True,
        supports_vision=True,
        cost_per_million_input=2.50,
        cost_per_million_output=10.00,
    ),
    "anthropic": LLMProviderMeta(
        id="anthropic",
        name="Anthropic",
        default_model="claude-sonnet-4-6",
        env_var="ANTHROPIC_API_KEY",
        base_url="https://api.anthropic.com",
        supports_streaming=True,
        supports_vision=True,
        cost_per_million_input=3.00,
        cost_per_million_output=15.00,
    ),
    "deepseek": LLMProviderMeta(
        id="deepseek",
        name="DeepSeek",
        default_model="deepseek-chat",
        env_var="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com",
        supports_streaming=True,
        supports_vision=False,
        cost_per_million_input=0.27,
        cost_per_million_output=1.10,
    ),
    "gemini": LLMProviderMeta(
        id="gemini",
        name="Google Gemini",
        default_model="gemini-1.5-pro",
        env_var="GEMINI_API_KEY",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        supports_streaming=True,
        supports_vision=True,
        cost_per_million_input=1.25,
        cost_per_million_output=5.00,
    ),
    "custom_llm": LLMProviderMeta(
        id="custom_llm",
        name="Custom LLM",
        default_model="custom-model",
        env_var="CUSTOM_LLM_API_KEY",
        base_url="",
        supports_streaming=True,
        supports_vision=False,
        cost_per_million_input=0.0,
        cost_per_million_output=0.0,
    ),
}

_catalog: dict[str, LLMProviderMeta] | None = None


def set_llm_provider_catalog(catalog: dict[str, LLMProviderMeta]) -> None:
    """Replace the provider catalog. Intended to be called once at
    server startup. OSS reads the current value on every request."""
    global _catalog
    _catalog = dict(catalog)
    logger.info("LLM provider catalog injected (%d providers)", len(_catalog))


def reset_llm_provider_catalog() -> None:
    """Restore the OSS default catalog (test/teardown helper)."""
    global _catalog
    _catalog = None


def get_llm_provider_catalog() -> dict[str, LLMProviderMeta]:
    """Current catalog: the server-injected one if set, else the OSS
    default. Returns a fresh dict; callers must not mutate the metas."""
    return dict(_catalog) if _catalog is not None else dict(_OSS_DEFAULT_CATALOG)


# --- Legacy-shape projections -------------------------------------------------
# The two historical consumers expect plain dicts with specific keys.
# These projections reproduce those exact shapes so the consumers stay
# one-line changes and the serialized output is unchanged.


def provider_core_config_dicts() -> dict[str, dict[str, object]]:
    """Shape consumed by ``core/config.py`` AppConfig.from_env()."""
    return {
        pid: {
            "id": m.id,
            "name": m.name,
            "default_model": m.default_model,
            "base_url": m.base_url,
            "env_var": m.env_var,
        }
        for pid, m in get_llm_provider_catalog().items()
    }


def provider_route_catalog_dicts() -> dict[str, dict[str, object]]:
    """Shape consumed by ``api/v1/routes/config.py``."""
    return {
        pid: {
            "id": m.id,
            "name": m.name,
            "default_model": m.default_model,
            "env_var": m.env_var,
            "supports_streaming": m.supports_streaming,
            "cost_per_million_input": m.cost_per_million_input,
            "cost_per_million_output": m.cost_per_million_output,
            "supports_vision": m.supports_vision,
        }
        for pid, m in get_llm_provider_catalog().items()
    }
