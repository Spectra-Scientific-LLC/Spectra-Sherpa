"""Extension contracts for the SpectraSherpa platform.

This package exposes the stable OSS-owned integration surface that
commercial extensions (``spectra-server``) consume.  Keep this namespace
limited to cross-repo contracts such as actor protocols, injected
resolvers, and capability names.

Transport-specific vocabularies like WebSocket actions/events live in
their own dedicated modules to avoid name collisions with feature flags.
"""

from spectra_sherpa.app.contracts.actors import CurrentActor
from spectra_sherpa.app.contracts.ai_provider import AIServiceProvider
from spectra_sherpa.app.contracts.auth_resolver import (
    ExtraUserAPIKeyAuthenticator,
    clear_extra_user_api_key_authenticator,
    get_extra_user_api_key_authenticator,
    set_extra_user_api_key_authenticator,
)
from spectra_sherpa.app.contracts.capabilities import (
    CHAT_ASSISTANT,
    SHERPA_ADVISOR,
    SHERPA_AGENTIC_TOOLS,
    SHERPA_CODE_GEN,
    SHERPA_DATA_STORY,
    SHERPA_FULL_CONTEXT,
    SHERPA_PEAK_ID,
    SHERPA_WRITE_REPORT,
)
from spectra_sherpa.app.contracts.config_overlay import (
    ConfigOverlayProvider,
    get_config_overlay_provider,
    set_config_overlay_provider,
)
from spectra_sherpa.app.contracts.demo_policy import (
    DemoPolicy,
    DemoPolicyProvider,
    get_demo_policy,
    set_demo_policy_provider,
)
from spectra_sherpa.app.contracts.key_resolver import (
    ExtraKeyResolver,
    get_extra_key_resolver,
    set_extra_key_resolver,
)

__all__ = [
    "AIServiceProvider",
    "clear_extra_user_api_key_authenticator",
    "CurrentActor",
    "ExtraUserAPIKeyAuthenticator",
    "ExtraKeyResolver",
    "get_extra_user_api_key_authenticator",
    "get_extra_key_resolver",
    "set_extra_user_api_key_authenticator",
    "set_extra_key_resolver",
    "ConfigOverlayProvider",
    "get_config_overlay_provider",
    "set_config_overlay_provider",
    "CHAT_ASSISTANT",
    "SHERPA_ADVISOR",
    "SHERPA_AGENTIC_TOOLS",
    "SHERPA_CODE_GEN",
    "SHERPA_DATA_STORY",
    "SHERPA_FULL_CONTEXT",
    "SHERPA_PEAK_ID",
    "SHERPA_WRITE_REPORT",
    "DemoPolicy",
    "DemoPolicyProvider",
    "get_demo_policy",
    "set_demo_policy_provider",
]
