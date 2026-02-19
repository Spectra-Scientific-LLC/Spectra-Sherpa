"""
Per-user demo limits enforcement.

When ``SITE_PROFILE=demo``, the Demo Contract defines caps on:
- workflow executions per session  (``max_executions_per_session``)
- Sherpa interactions per session  (``max_sherpa_interactions``)

This module provides a thin API around two file-backed ``RateLimiter``
instances (one for each quota).  The sliding window equals
``session_expiry_hours`` (default 24 h) so the cap resets roughly once
per login cycle.

Both the HTTP middleware (``RateLimitMiddleware``) and the WebSocket
dispatcher call into these helpers so enforcement is consistent across
REST and WS paths.
"""

from __future__ import annotations

import logging
from typing import Optional

from spectra_sherpa.app.core.config import app_config, settings
from spectra_sherpa.app.services.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# Lazy singletons — created on first access so module import is cheap.
_execution_limiter: Optional[RateLimiter] = None
_sherpa_limiter: Optional[RateLimiter] = None


def _session_window_sec() -> int:
    """Sliding-window duration for demo limits (seconds)."""
    hours = app_config.session_expiry_hours or 24
    return hours * 3600


def _ensure_limiters() -> tuple[RateLimiter, RateLimiter]:
    """Create the demo rate limiters on first use."""
    global _execution_limiter, _sherpa_limiter

    if _execution_limiter is None:
        contract = app_config.demo_contract
        window = _session_window_sec()
        _execution_limiter = RateLimiter(
            max_calls=contract.max_executions_per_session,
            period_sec=window,
            state_path=settings.data_dir / "demo_execution_limits.json",
        )
        _sherpa_limiter = RateLimiter(
            max_calls=contract.max_sherpa_interactions,
            period_sec=window,
            state_path=settings.data_dir / "demo_sherpa_limits.json",
        )

    return _execution_limiter, _sherpa_limiter


def _user_key(user_id: int | None) -> str:
    if user_id is not None:
        return f"user:{user_id}"
    return "anonymous"


# -- Public API ----------------------------------------------------------------


def is_demo_limited() -> bool:
    """True when demo limits should be enforced (site_profile == demo)."""
    return app_config.site_profile == "demo"


def check_demo_execution(user_id: int | None) -> tuple[bool, int]:
    """Consume one execution token.

    Returns ``(allowed, remaining)``.
    """
    if not is_demo_limited():
        return True, -1

    limiter, _ = _ensure_limiters()
    key = _user_key(user_id)
    allowed = limiter.allow(key)
    remaining = limiter.remaining(key)
    return allowed, remaining


def check_demo_sherpa(user_id: int | None) -> tuple[bool, int]:
    """Consume one Sherpa interaction token.

    Returns ``(allowed, remaining)``.
    """
    if not is_demo_limited():
        return True, -1

    _, limiter = _ensure_limiters()
    key = _user_key(user_id)
    allowed = limiter.allow(key)
    remaining = limiter.remaining(key)
    return allowed, remaining


def demo_execution_remaining(user_id: int | None) -> int:
    """How many executions remain (read-only, no consumption)."""
    if not is_demo_limited():
        return -1
    limiter, _ = _ensure_limiters()
    return limiter.remaining(_user_key(user_id))


def demo_sherpa_remaining(user_id: int | None) -> int:
    """How many Sherpa interactions remain (read-only, no consumption)."""
    if not is_demo_limited():
        return -1
    _, limiter = _ensure_limiters()
    return limiter.remaining(_user_key(user_id))


def demo_limit_error_detail(kind: str, remaining: int) -> dict:
    """Build a structured 429/error payload for demo limit exhaustion."""
    contract = app_config.demo_contract
    if kind == "execution":
        limit = contract.max_executions_per_session
        msg = f"Demo execution limit reached ({limit} per session)."
    else:
        limit = contract.max_sherpa_interactions
        msg = f"Demo Sherpa interaction limit reached ({limit} per session)."
    return {
        "message": msg,
        "upgrade_url": contract.upgrade_url,
        "available_plans": contract.available_plans,
        "limit": limit,
        "remaining": 0,
    }


def reset_limiters() -> None:
    """Reset lazy singletons (for tests)."""
    global _execution_limiter, _sherpa_limiter
    _execution_limiter = None
    _sherpa_limiter = None
