"""Deprecated import path. Use spectra_sherpa.app.contracts.ai_provider_registry."""

import warnings

from spectra_sherpa.app.contracts.ai_provider_registry import (  # noqa: F401
    DisabledAIProvider,
    FeatureDisabledError,
    get_sherpa_advisor,
    reset_sherpa_advisor,
    set_sherpa_advisor,
)

warnings.warn(
    "spectra_sherpa.app.services.sherpa_advisor is deprecated; "
    "import from spectra_sherpa.app.contracts.ai_provider_registry instead. "
    "This shim will be removed in 0.N+2.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "DisabledAIProvider",
    "FeatureDisabledError",
    "get_sherpa_advisor",
    "reset_sherpa_advisor",
    "set_sherpa_advisor",
]
