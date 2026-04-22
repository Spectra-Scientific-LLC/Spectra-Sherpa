import hashlib
import ipaddress
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Optional, cast

import bcrypt
import jwt
from fastapi import Depends, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import PyJWTError as JWTError

from spectra_sherpa.app.core.config import app_config, settings
from spectra_sherpa.app.core.mode_policy import (
    api_key_always_valid,
    export_always_allowed,
    requires_http_auth,
    system_api_key_always_accepted,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)

# Password hashing — using bcrypt directly (passlib is unmaintained, incompatible with bcrypt >= 4.1)

# ============================================================================
# API Key Validation Cache (for gateway middleware / websocket auth)
# ============================================================================
# Caches validated API keys to avoid expensive bcrypt verification on every request.
# Cache entries expire after API_KEY_CACHE_TTL seconds.

API_KEY_CACHE_TTL = 300  # 5 minutes
API_KEY_CACHE_MAX_SIZE = 1024  # Max cached entries (prevents unbounded memory growth)
_api_key_cache: dict[str, tuple[int, float]] = {}  # {key_hash: (user_id, expires_at)}
INVALID_API_KEY_CACHE_TTL = 60  # 1 minute
_invalid_api_key_cache: dict[str, float] = {}  # {key_hash: expires_at}


def llm_egress_defaults_enabled() -> bool:
    """Whether new users should default LLM chat/context egress to enabled."""
    return app_config.site_profile == "demo" or app_config.mode == "local"


def llm_egress_defaults_forced() -> bool:
    """Whether LLM chat/context egress is forced on regardless of user choice."""
    return app_config.site_profile == "demo"


def _hash_api_key(api_key: str) -> str:
    """Create a fast hash of API key for cache lookup."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def _get_cached_user_id(api_key: str) -> Optional[int]:
    """Check if API key is in cache and not expired."""
    key_hash = _hash_api_key(api_key)
    if key_hash in _api_key_cache:
        user_id, expires_at = _api_key_cache[key_hash]
        if time.time() < expires_at:
            return user_id
        # Expired - remove from cache
        del _api_key_cache[key_hash]
    return None


def _evict_expired_cache_entries() -> None:
    """Remove expired entries from both caches to reclaim memory."""
    now = time.time()
    expired_valid = [k for k, (_, exp) in _api_key_cache.items() if now >= exp]
    for k in expired_valid:
        del _api_key_cache[k]
    expired_invalid = [k for k, exp in _invalid_api_key_cache.items() if now >= exp]
    for k in expired_invalid:
        del _invalid_api_key_cache[k]


def _cache_api_key(api_key: str, user_id: int) -> None:
    """Cache a validated API key."""
    if len(_api_key_cache) >= API_KEY_CACHE_MAX_SIZE:
        _evict_expired_cache_entries()
        # If still at capacity after eviction, drop oldest entry
        if len(_api_key_cache) >= API_KEY_CACHE_MAX_SIZE:
            oldest = min(_api_key_cache, key=lambda k: _api_key_cache[k][1])
            del _api_key_cache[oldest]
    key_hash = _hash_api_key(api_key)
    _api_key_cache[key_hash] = (user_id, time.time() + API_KEY_CACHE_TTL)
    _invalid_api_key_cache.pop(key_hash, None)


def _is_cached_invalid_api_key(api_key: str) -> bool:
    """Return True when this key recently failed validation."""
    key_hash = _hash_api_key(api_key)
    expires_at = _invalid_api_key_cache.get(key_hash)
    if expires_at is None:
        return False
    if time.time() < expires_at:
        return True
    del _invalid_api_key_cache[key_hash]
    return False


def _cache_invalid_api_key(api_key: str) -> None:
    """Cache an invalid key briefly to reduce repeated bcrypt scans."""
    if len(_invalid_api_key_cache) >= API_KEY_CACHE_MAX_SIZE:
        _evict_expired_cache_entries()
        if len(_invalid_api_key_cache) >= API_KEY_CACHE_MAX_SIZE:
            oldest = min(_invalid_api_key_cache, key=lambda k: _invalid_api_key_cache[k])
            del _invalid_api_key_cache[oldest]
    key_hash = _hash_api_key(api_key)
    _invalid_api_key_cache[key_hash] = time.time() + INVALID_API_KEY_CACHE_TTL


def invalidate_gateway_api_key_cache(api_key: Optional[str] = None) -> None:
    """Invalidate gateway API key caches (both valid and invalid entries)."""
    global _api_key_cache, _invalid_api_key_cache
    if api_key:
        key_hash = _hash_api_key(api_key)
        _api_key_cache.pop(key_hash, None)
        _invalid_api_key_cache.pop(key_hash, None)
        return
    _api_key_cache = {}
    _invalid_api_key_cache = {}


# HTTP Bearer token extraction for Authorization header parsing.
# We intentionally avoid OAuth2 password flow metadata in OSS OpenAPI because
# login/register endpoints are provided only by the server distribution.
http_bearer_optional = HTTPBearer(auto_error=False)


def extract_bearer_token(
    credentials: Optional[HTTPAuthorizationCredentials],
) -> Optional[str]:
    """Return the raw token from a Bearer auth header."""
    if credentials is None:
        return None
    if credentials.scheme.lower() != "bearer":
        return None
    return credentials.credentials or None


async def get_bearer_token_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer_optional),
) -> Optional[str]:
    """FastAPI dependency that returns an optional Bearer token string."""
    return extract_bearer_token(credentials)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    return bool(
        bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    )


def get_password_hash(password: str) -> str:
    """Generate a password hash."""
    hashed = bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    )
    return str(hashed.decode("utf-8"))


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=15)

    to_encode.update({"exp": expire, "iat": now})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return cast(str, encoded_jwt)


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT access token."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return cast(dict[Any, Any], payload)
    except JWTError:
        return None


def is_valid_bearer_token(token: Optional[str]) -> bool:
    """Fast JWT validity check used by gateway middleware and WebSocket auth."""
    if not token:
        return False
    return decode_access_token(token) is not None


async def is_valid_api_key(api_key: Optional[str]) -> bool:
    """
    Validate an API key for WebSocket and middleware authentication.

    Checks:
    1. Global system API key (settings.api_key)
    2. Local mode bypass (no key required)
    3. User-specific API keys stored in database

    Note: This path includes database validation so the gateway can accept
    user API keys before route-level dependencies run.
    """
    # Local mode: always valid (no auth required)
    if api_key_always_valid():
        return True

    if not api_key:
        return False

    # Check global system key
    if api_key == settings.api_key and is_system_api_key_auth_enabled():
        return True

    if _is_cached_invalid_api_key(api_key):
        return False

    # Check server-managed user API keys in database
    try:
        from sqlalchemy import select

        from spectra_sherpa.app.contracts.auth_resolver import get_extra_user_api_key_authenticator
        from spectra_sherpa.app.db.session import async_session
        from spectra_sherpa.app.models.user import User

        async with async_session() as session:
            # Check cache first
            cached_user_id = _get_cached_user_id(api_key)
            if cached_user_id is not None:
                result = await session.execute(select(User).where(User.id == cached_user_id))
                user = result.scalar_one_or_none()
                if user and getattr(user, "is_active", True):
                    return True

            authenticator = get_extra_user_api_key_authenticator()
            if authenticator is not None:
                authenticated_user_id = await authenticator(api_key, session)
                if authenticated_user_id is not None:
                    _cache_api_key(api_key, authenticated_user_id)
                    return True
    except Exception:
        # Fail closed if database lookup fails
        logger.warning("API key validation failed due to database error", exc_info=True)

    _cache_invalid_api_key(api_key)
    return False


def is_system_api_key_auth_enabled() -> bool:
    """Return whether APP_API_KEY is accepted for request authentication."""
    if system_api_key_always_accepted():
        return True
    return os.getenv("ALLOW_SYSTEM_API_KEY_AUTH", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


# Trust X-Forwarded-For when behind a reverse proxy (Docker, nginx, Caddy).
# Only enable when you control the proxy — otherwise clients can spoof their IP.
_TRUST_PROXY = os.getenv("TRUST_PROXY", "").strip().lower() in {"1", "true", "yes"}
_TRUSTED_PROXY_CIDRS_ENV = os.getenv("TRUSTED_PROXY_CIDRS", "").strip()


def _parse_trusted_proxy_cidrs(raw: str) -> tuple[ipaddress._BaseNetwork, ...]:
    # Safe default: only trust loopback proxy peers when CIDRs are not specified.
    values = ["127.0.0.1/32", "::1/128"] if not raw else [value.strip() for value in raw.split(",") if value.strip()]
    networks: list[ipaddress._BaseNetwork] = []
    for value in values:
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    return tuple(networks)


_TRUSTED_PROXY_CIDRS = _parse_trusted_proxy_cidrs(_TRUSTED_PROXY_CIDRS_ENV)


def _normalize_ip(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1 : candidate.index("]")]
    elif candidate.count(":") == 1 and "." in candidate:
        # IPv4 with port in forwarded headers, e.g. "203.0.113.7:12345"
        candidate = candidate.rsplit(":", 1)[0]
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return None
    return candidate


def _is_trusted_proxy_peer(host: str | None) -> bool:
    normalized = _normalize_ip(host)
    if not normalized:
        return False
    ip = ipaddress.ip_address(normalized)
    return any(ip in network for network in _TRUSTED_PROXY_CIDRS)


def get_client_host(request_or_ws) -> str | None:
    """Extract the real client IP, respecting X-Forwarded-For when trusted.

    X-Forwarded-For is only honored when TRUST_PROXY is enabled and the
    immediate peer is inside TRUSTED_PROXY_CIDRS.
    """
    client = getattr(request_or_ws, "client", None)
    direct_host = client.host if client else None

    if _TRUST_PROXY and _is_trusted_proxy_peer(direct_host):
        forwarded = getattr(request_or_ws, "headers", {}).get("x-forwarded-for")
        if forwarded:
            # X-Forwarded-For: client, proxy1, proxy2 — leftmost is original
            forwarded_client = _normalize_ip(forwarded.split(",")[0].strip())
            if forwarded_client:
                return forwarded_client
    return direct_host


async def api_key_middleware(request: Request, call_next) -> Response:
    """
    Middleware to validate API keys for all requests.

    In Local mode, all requests are allowed (single-user desktop).
    In Hybrid mode, loopback requests are allowed; non-loopback clients
    must provide valid credentials (JWT or API key).
    In Enterprise mode, all non-public requests must be authenticated.

    This middleware enforces authentication at the gateway level - requests
    without valid credentials are rejected with 401.
    """
    from fastapi.responses import JSONResponse

    from spectra_sherpa.app.contracts.public_path_provider import get_public_paths

    # Skip auth check for public paths. Core list lives in the contract;
    # server-side extensions (e.g. /api/v1/auth/login, /api/v1/auth/register)
    # are appended via register_public_paths() at startup.
    public_paths = get_public_paths()

    path = request.url.path

    # Allow static frontend and SPA routes through without auth.
    # The SPA catchall serves index.html for any non-API path — these
    # contain no sensitive data. Actual data is protected by /api/ auth.
    is_frontend_path = not path.startswith("/api/") and not path.startswith("/ws")
    if path in public_paths or is_frontend_path or path.startswith("/docs") or path.startswith("/redoc"):
        return await call_next(request)  # type: ignore[no-any-return]

    # Mode-based auth bypass: local always passes, hybrid loopback passes.
    if not requires_http_auth(get_client_host(request)):
        return await call_next(request)  # type: ignore[no-any-return]

    # Server-backed Sherpa routes authenticate with X-Deployment-Key at the
    # route/dependency layer. Do not block them at the generic gateway layer.
    deployment_key = request.headers.get("X-Deployment-Key")
    if deployment_key and (
        path == "/api/v1/config/subscription"
        or path.startswith("/api/v1/conversations")
        or path.startswith("/api/v1/sherpa/")
    ):
        return await call_next(request)  # type: ignore[no-any-return]

    # Check for API key or Bearer token
    api_key = request.headers.get("X-API-Key")
    auth_header = request.headers.get("Authorization")

    is_authenticated = False

    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if is_valid_bearer_token(token):
            is_authenticated = True

    if not is_authenticated and api_key and await is_valid_api_key(api_key):
        is_authenticated = True

    # In non-local modes, REQUIRE authentication - reject unauthenticated requests
    if not is_authenticated:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Authentication required"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await call_next(request)  # type: ignore[no-any-return]


def is_egress_enabled() -> bool:
    """
    Check if network egress is globally enabled.

    In local mode, egress is disabled by default unless explicitly enabled.
    In hybrid/enterprise modes, egress is enabled by default.

    IMPORTANT: In hybrid mode, if we're degraded (SpectraSherpa unreachable),
    egress is disabled to enforce local-only behavior during fallback.

    Returns:
        True if egress is allowed, False otherwise
    """
    # Check if we're in degraded mode (hybrid fallback to local)
    if app_config.mode == "hybrid":
        try:
            from spectra_sherpa.app.services.network_health import get_network_health_service

            health_service = get_network_health_service()
            if health_service.is_degraded:
                # In degraded mode, disable egress to enforce local-only behavior
                return False
        except Exception:
            # If we can't check health, default to config setting
            logger.debug("Network health check failed, using config default", exc_info=True)

    return app_config.egress_enabled


async def check_egress_permission(
    user: Any,
    permission: str,
    data_type: str | None = None,
    destination: str | None = None,
    session: "AsyncSession | None" = None,
    *,
    skip_global_check: bool = False,
) -> bool:
    """
    Check if a user has permission for a specific egress operation.

    Args:
        user: The user to check permissions for (can be None for system operations)
        permission: The permission to check. Valid values:
            - "allow_llm_chat": Can call AI chat features at all
            - "allow_llm_context": Can send data to LLM providers
            - "allow_nist_queries": Can query NIST WebBook
            - "allow_spectrasherpa_sync": Can sync to SpectraSherpa cloud
            - "allow_export": Can export data to external files
        data_type: Optional fine-grained data type (e.g. "spectra", "models")
        destination: Optional fine-grained destination (e.g. "llm_context", "export")
        session: AsyncSession required when data_type + destination are provided
        skip_global_check: When True, skip the global is_egress_enabled() check.
            Used for user-initiated actions (e.g. BYOK LLM chat) where the user
            explicitly consented by providing their own API key and message.

    Returns:
        True if the permission is granted, False otherwise

    Egress permissions are checked in this order:
    1. Global egress flag (if disabled, all egress is blocked — unless skip_global_check)
    2. Fine-grained DataEgressPermission (when data_type + destination + session provided)
    3. User's egress_defaults settings (from UserEgressDefaults model)
    4. Apply sensible defaults for users without egress_defaults configured
    """
    # First check global egress flag (skippable for user-initiated actions)
    if not skip_global_check and not is_egress_enabled():
        return False

    # If no user context, allow (system operation in hybrid/enterprise mode)
    if user is None:
        return True

    # Fine-grained permission check when a specific egress tuple is provided.
    if (
        data_type is not None
        and destination is not None
        and session is not None
        and getattr(user, "id", None) is not None
    ):
        try:
            from sqlalchemy import select

            from spectra_sherpa.app.models.data_egress import DataEgressPermission

            result = await session.execute(
                select(DataEgressPermission).where(
                    DataEgressPermission.user_id == user.id,
                    DataEgressPermission.data_type == data_type,
                    DataEgressPermission.destination == destination,
                )
            )
            permission_row = result.scalar_one_or_none()
            if permission_row is not None:
                return bool(permission_row.allowed)
        except Exception:
            # Fall back to coarse defaults if fine-grained lookup isn't available.
            logger.debug("Fine-grained egress permission lookup failed", exc_info=True)

    # Check user's egress_defaults relationship for the permission.
    # Wrapped in try/except because the user object may be detached from its
    # original session (e.g. WS handler), causing a lazy-load error.
    try:
        if hasattr(user, "egress_defaults") and user.egress_defaults is not None:
            egress_defaults = user.egress_defaults
            if hasattr(egress_defaults, permission):
                return getattr(egress_defaults, permission, False)
    except Exception:
        # Relationship access failed (DetachedInstanceError, etc.).  If we have a
        # session and user id, query UserEgressDefaults directly so we never
        # silently fall through to permissive hardcoded defaults.
        logger.debug("Egress defaults relationship access failed, trying DB fallback", exc_info=True)
        if session is not None and getattr(user, "id", None) is not None:
            try:
                from sqlalchemy import select

                from spectra_sherpa.app.models.data_egress import UserEgressDefaults

                row = (
                    await session.execute(select(UserEgressDefaults).where(UserEgressDefaults.user_id == user.id))
                ).scalar_one_or_none()
                if row is not None and hasattr(row, permission):
                    return getattr(row, permission, False)
            except Exception:
                logger.debug(
                    "UserEgressDefaults DB fallback failed for user %s",
                    getattr(user, "id", "?"),
                )

    # No explicit permission set - apply sensible defaults.
    # These are intentionally conservative: new users are created with
    # allow_spectrasherpa_sync=False, so the default here must match.
    # Local & demo modes: LLM chat/context default to True so users can
    # use their own API keys immediately without extra configuration.
    _llm_default = llm_egress_defaults_enabled()
    DEFAULT_PERMISSIONS = {
        "allow_llm_chat": _llm_default,  # On by default in local & demo
        "allow_llm_context": _llm_default,  # On by default in local & demo
        "allow_nist_queries": False,  # Explicit opt-in required
        "allow_export": False,  # Explicit opt-in required
        "allow_spectrasherpa_sync": False,  # Set via DB row; demo startup forces it on
    }
    return DEFAULT_PERMISSIONS.get(permission, False)


async def check_export_allowed(
    user: Any,
    session: "AsyncSession | None" = None,
) -> bool:
    """
    Check if a user is allowed to export/download data to their browser.

    Unlike ``check_egress_permission``, this does **not** gate on the
    global ``egress_enabled`` flag because file exports to the user's
    browser are local operations, not network egress.

    In local mode (single user) exports are always allowed.
    In multi-user modes (hybrid, enterprise), the admin can restrict exports
    via the user's ``allow_export`` egress default.
    """
    if export_always_allowed():
        return True

    if user is None:
        return True

    try:
        if hasattr(user, "egress_defaults") and user.egress_defaults is not None:
            return getattr(user.egress_defaults, "allow_export", True)
    except Exception:
        logger.debug("Export permission relationship access failed, trying DB fallback", exc_info=True)
        if session is not None and getattr(user, "id", None) is not None:
            try:
                from sqlalchemy import select

                from spectra_sherpa.app.models.data_egress import UserEgressDefaults

                row = (
                    await session.execute(select(UserEgressDefaults).where(UserEgressDefaults.user_id == user.id))
                ).scalar_one_or_none()
                if row is not None:
                    return getattr(row, "allow_export", True)
            except Exception:
                logger.debug(
                    "Export permission DB fallback failed for user %s", getattr(user, "id", "?"), exc_info=True
                )

    return True  # default: allow exports
