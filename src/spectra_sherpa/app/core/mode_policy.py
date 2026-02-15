"""
Centralized mode policy for local / hybrid / enterprise behavior.

All runtime decisions that branch on ``app_config.mode`` should be expressed
as calls into this module.  This keeps the mode semantics in one place so
that:

- Tests can verify policy without importing every module.
- Adding a new mode requires changes in **one** file.
- The future repo split can delete unwanted policies mechanically.

Boot-time validation (startup.py, logging.py) may still read ``app_config``
directly for one-shot checks that don't affect request handling.
"""

from __future__ import annotations

from app.core.config import app_config


# ── Identity shortcuts ───────────────────────────────────────────

def is_local() -> bool:
    """True when running in single-user desktop mode."""
    return app_config.mode == "local"


def is_hybrid() -> bool:
    """True when running in hybrid (local + optional cloud) mode."""
    return app_config.mode == "hybrid"


def is_enterprise() -> bool:
    """True when running in enterprise / SaaS mode (JWT auth, rate-limits, PostgreSQL required)."""
    return app_config.mode == "enterprise"


def is_demo() -> bool:
    """Deprecated: use is_enterprise(). Kept as alias for one release cycle."""
    return is_enterprise()


def is_multi_user() -> bool:
    """True when the mode requires user management (hybrid or enterprise)."""
    return app_config.mode != "local"


# ── Authentication ───────────────────────────────────────────────

def requires_http_auth(client_host: str | None) -> bool:
    """Whether an HTTP request from *client_host* must carry credentials.

    - Local mode: never requires auth.
    - Hybrid mode: loopback clients are exempt; remote clients need auth.
    - Enterprise mode: all clients need auth.
    """
    if app_config.mode == "local":
        return False
    if app_config.mode == "hybrid":
        from app.core.security import _is_loopback
        return not _is_loopback(client_host)
    # enterprise (and any future mode): always require auth
    return True


def requires_ws_auth(client_host: str | None) -> bool:
    """Whether a WebSocket connection from *client_host* must carry credentials.

    Same rules as HTTP auth.
    """
    return requires_http_auth(client_host)


def allows_registration() -> bool:
    """Whether user self-registration is open.

    Disabled in local mode (single implicit user).
    """
    return app_config.mode != "local"


def allows_admin() -> bool:
    """Whether admin endpoints are accessible.

    Disabled in local mode (no user management needed).
    """
    return app_config.mode != "local"


# ── API key validation ───────────────────────────────────────────

def api_key_always_valid() -> bool:
    """In local mode, all API keys are accepted without database check."""
    return app_config.mode == "local"


def system_api_key_always_accepted() -> bool:
    """In local mode, the system API key is always accepted."""
    return app_config.mode == "local"


# ── Egress & exports ────────────────────────────────────────────

def export_always_allowed() -> bool:
    """In local mode, data exports are always permitted (single-user)."""
    return app_config.mode == "local"


def cors_allow_all() -> bool:
    """In local mode, all CORS origins are permitted (desktop convenience)."""
    return app_config.mode == "local"


# ── Limits ───────────────────────────────────────────────────────

def has_rate_limits() -> bool:
    """True when rate limiting / session expiry enforcement is active."""
    return app_config.mode in ("hybrid", "enterprise")


def token_ttl_minutes() -> int:
    """Default JWT token lifetime in minutes.

    - Local: 8 days (desktop convenience, single-user).
    - Non-local: 60 minutes (security for multi-user).
    """
    if app_config.mode == "local":
        return 60 * 24 * 8  # 11520
    return 60
