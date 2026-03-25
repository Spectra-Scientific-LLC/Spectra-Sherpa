from __future__ import annotations

from typing import Any

from spectra_sherpa.app.services.rate_limiter import RateLimiter


def llm_rate_limit_key(user: Any) -> str:
    """Return the persistent limiter key for a user-scoped LLM quota."""
    return f"user_{user.id}" if user and getattr(user, "id", None) else "anonymous"


def has_llm_rate_limit_bypass(user: Any) -> bool:
    """Superusers bypass paid Sherpa/LLM quotas."""
    return bool(user and getattr(user, "is_superuser", False))


def allow_llm_request(limiter: RateLimiter, user: Any) -> bool:
    """Check quota consumption for a user, honoring admin bypass."""
    if has_llm_rate_limit_bypass(user):
        return True
    return limiter.allow(llm_rate_limit_key(user))
