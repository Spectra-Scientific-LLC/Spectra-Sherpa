from datetime import datetime, timedelta
import hashlib
import time
from typing import Any, Optional, TYPE_CHECKING

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from passlib.context import CryptContext

from app.core.config import app_config, settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.models.user import User

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ============================================================================
# API Key Validation Cache (for gateway middleware / websocket auth)
# ============================================================================
# Caches validated API keys to avoid expensive bcrypt verification on every request.
# Cache entries expire after API_KEY_CACHE_TTL seconds.

API_KEY_CACHE_TTL = 300  # 5 minutes
_api_key_cache: dict[str, tuple[int, float]] = {}  # {key_hash: (user_id, expires_at)}


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


def _cache_api_key(api_key: str, user_id: int) -> None:
    """Cache a validated API key."""
    key_hash = _hash_api_key(api_key)
    _api_key_cache[key_hash] = (user_id, time.time() + API_KEY_CACHE_TTL)

# OAuth2 scheme - use relative URL for tokenUrl
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Generate a password hash."""
    return pwd_context.hash(password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create a JWT access token."""
    to_encode = data.copy()
    now = datetime.utcnow()
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=15)

    to_encode.update({"exp": expire, "iat": now})
    encoded_jwt = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """Decode and validate a JWT access token."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        return payload
    except JWTError:
        return None


async def is_valid_api_key(api_key: Optional[str]) -> bool:
    """
    Validate an API key for WebSocket and middleware authentication.

    Checks:
    1. Global system API key (settings.api_key)
    2. Local mode bypass (no key required)
    3. User-specific API keys stored in database
    4. JWT tokens passed as api_key

    Note: This path includes database validation so the gateway can accept
    user API keys before route-level dependencies run.
    """
    # Local mode: always valid (no auth required)
    if app_config.mode == "local":
        return True

    if not api_key:
        return False

    # Check global system key
    if api_key == settings.api_key:
        return True

    # For JWT tokens passed as api_key, try to decode
    payload = decode_access_token(api_key)
    if payload:
        return True

    # Check user-specific API keys in database
    try:
        from sqlalchemy import select
        from app.db.session import async_session
        from app.models.user import User

        async with async_session() as session:
            # Check cache first
            cached_user_id = _get_cached_user_id(api_key)
            if cached_user_id is not None:
                result = await session.execute(
                    select(User).where(User.id == cached_user_id)
                )
                user = result.scalar_one_or_none()
                if user:
                    return True

            # Cache miss - expensive bcrypt verification
            result = await session.execute(
                select(User).where(User.api_key_hash.isnot(None))
            )
            users_with_keys = result.scalars().all()
            for user in users_with_keys:
                if verify_password(api_key, user.api_key_hash):
                    _cache_api_key(api_key, user.id)
                    return True
    except Exception:
        # Fail closed if database lookup fails
        pass

    return False


async def api_key_middleware(request: Request, call_next) -> Response:
    """
    Middleware to validate API keys for all requests.

    In Local mode, all requests are allowed.
    In Hybrid/Demo mode, requests must have valid authentication.

    This middleware enforces authentication at the gateway level - requests
    without valid credentials are rejected with 401.
    """
    from fastapi.responses import JSONResponse

    # Skip auth check for public paths
    public_paths = [
        "/",
        "/health",
        "/api/v1/health",
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/config",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/openapi.json",
    ]

    path = request.url.path
    if (path in public_paths
            or path.startswith("/docs")
            or path.startswith("/redoc")
            or path.startswith("/assets/")
            or path == "/favicon.ico"):
        return await call_next(request)

    # Local and hybrid modes: bypass auth (single-user on local machine).
    # Only demo mode (multi-user cloud) enforces gateway auth.
    if app_config.mode in ("local", "hybrid"):
        return await call_next(request)

    # Check for API key or Bearer token
    api_key = request.headers.get("X-API-Key")
    auth_header = request.headers.get("Authorization")

    is_authenticated = False

    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if await is_valid_api_key(token):
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

    return await call_next(request)


def is_egress_enabled() -> bool:
    """
    Check if network egress is globally enabled.

    In local mode, egress is disabled by default unless explicitly enabled.
    In hybrid/demo modes, egress is enabled by default.

    IMPORTANT: In hybrid mode, if we're degraded (SpectraSherpa unreachable),
    egress is disabled to enforce local-only behavior during fallback.

    Returns:
        True if egress is allowed, False otherwise
    """
    # Check if we're in degraded mode (hybrid fallback to local)
    if app_config.mode == "hybrid":
        try:
            from app.services.network_health import get_network_health_service
            health_service = get_network_health_service()
            if health_service.is_degraded:
                # In degraded mode, disable egress to enforce local-only behavior
                return False
        except Exception:
            # If we can't check health, default to config setting
            pass

    return app_config.egress_enabled


async def check_egress_permission(
    user: Any,
    permission: str,
    data_type: str | None = None,
    destination: str | None = None,
    session: "AsyncSession | None" = None,
) -> bool:
    """
    Check if a user has permission for a specific egress operation.

    Args:
        user: The user to check permissions for (can be None for system operations)
        permission: The permission to check. Valid values:
            - "allow_llm_context": Can send data to LLM providers
            - "allow_nist_queries": Can query NIST WebBook
            - "allow_spectrasherpa_sync": Can sync to SpectraSherpa cloud
            - "allow_export": Can export data to external files
        data_type: Optional fine-grained data type (e.g. "spectra", "models")
        destination: Optional fine-grained destination (e.g. "llm_context", "export")
        session: AsyncSession required when data_type + destination are provided

    Returns:
        True if the permission is granted, False otherwise

    Egress permissions are checked in this order:
    1. Global egress flag (if disabled, all egress is blocked)
    2. Fine-grained DataEgressPermission (when data_type + destination + session provided)
    3. User's egress_defaults settings (from UserEgressDefaults model)
    4. Apply sensible defaults for users without egress_defaults configured
    """
    # First check global egress flag
    if not is_egress_enabled():
        return False

    # If no user context, allow (system operation in hybrid/demo mode)
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
            from app.models.data_egress import DataEgressPermission

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
            pass

    # Check user's egress_defaults relationship for the permission
    # The egress_defaults is a relationship to UserEgressDefaults
    if hasattr(user, 'egress_defaults') and user.egress_defaults is not None:
        egress_defaults = user.egress_defaults
        if hasattr(egress_defaults, permission):
            return getattr(egress_defaults, permission, False)

    # No explicit permission set - apply sensible defaults
    # These match the defaults we create for new users in auth.py/admin.py
    # This ensures existing users and system users work correctly
    DEFAULT_PERMISSIONS = {
        "allow_llm_context": True,      # Allow LLM by default
        "allow_nist_queries": True,     # Allow NIST by default
        "allow_export": True,           # Allow export by default
        "allow_spectrasherpa_sync": False,  # Opt-in for cloud sync
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
    In multi-user modes (hybrid, demo), the admin can restrict exports
    via the user's ``allow_export`` egress default.
    """
    if app_config.mode == "local":
        return True

    if user is None:
        return True

    if hasattr(user, "egress_defaults") and user.egress_defaults is not None:
        return getattr(user.egress_defaults, "allow_export", True)

    return True  # default: allow exports
