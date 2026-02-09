from __future__ import annotations

from typing import AsyncGenerator, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from jose import JWTError
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas
from app.core import security
from app.core.config import app_config, settings
from app.db.session import async_session
from app.models.user import User


def invalidate_api_key_cache(api_key: Optional[str] = None) -> None:
    """Invalidate API key cache (delegates to security module's canonical cache)."""
    security.invalidate_gateway_api_key_cache(api_key)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session


api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


_local_user_cache: Optional[User] = None


async def _get_or_create_local_user(session: AsyncSession) -> User:
    """Return the implicit local-mode user, creating it on first call.

    The user object is cached in-memory so subsequent requests skip
    the database entirely.  ``session.merge()`` re-attaches the cached
    instance to the current session to avoid DetachedInstanceError.
    """
    global _local_user_cache
    if _local_user_cache is not None:
        return await session.merge(_local_user_cache)
    result = await session.execute(select(User).order_by(User.id).limit(1))
    user = result.scalar_one_or_none()
    if not user:
        user = User(username="local", password_hash="local")
        session.add(user)
        await session.commit()
        await session.refresh(user)
    _local_user_cache = user
    return user


async def _resolve_user(
    session: AsyncSession,
    api_key: Optional[str] = None,
    token: Optional[str] = None,
    client_host: Optional[str] = None,
) -> Optional[User]:
    """
    Core authentication logic shared by get_current_user and get_user_from_credentials.

    Returns the authenticated User or None if credentials are invalid.
    """
    # 0. Local mode: implicit user identity (single-user, no login needed)
    from app.core.mode_policy import is_local
    if is_local():
        return await _get_or_create_local_user(session)

    has_credentials = bool(api_key or token)
    # If system-key auth is disabled, ignore APP_API_KEY for dependency auth.
    # This preserves hybrid loopback fallback behavior when stale keys are present
    # in local storage, while gateway auth still blocks non-loopback requests.
    if api_key == settings.api_key and not security.is_system_api_key_auth_enabled():
        api_key = None
        has_credentials = bool(token)

    # 1. API Key Auth (Machine-to-Machine / Cloud Node)
    if api_key:
        # Fast path: global system key
        if api_key == settings.api_key:
            if not security.is_system_api_key_auth_enabled():
                return None
            # Map to a real DB user instead of a synthetic superuser so auth
            # honors actual account state/permissions in non-local modes.
            result = await session.execute(
                select(User).where(User.is_active.is_(True)).order_by(User.id).limit(1)
            )
            return result.scalar_one_or_none()

        # Check cache first (avoids expensive bcrypt on every request)
        cached_user_id = security._get_cached_user_id(api_key)
        if cached_user_id is not None:
            result = await session.execute(select(User).where(User.id == cached_user_id))
            user = result.scalar_one_or_none()
            if user and getattr(user, "is_active", True):
                return user

        # Cache miss - do expensive bcrypt verification
        # We need to iterate over users with API keys and verify each one
        # because bcrypt hashes include random salts
        result = await session.execute(
            select(User).where(User.api_key_hash.isnot(None))
        )
        users_with_keys = result.scalars().all()

        for user in users_with_keys:
            if hasattr(user, "is_active") and not user.is_active:
                continue
            if security.verify_password(api_key, user.api_key_hash):
                security._cache_api_key(api_key, user.id)
                return user

    # 2. JWT Auth (User Login)
    if token:
        try:
            payload = security.decode_access_token(token)
            if payload:
                token_data = schemas.TokenPayload(**payload)
                result = await session.execute(select(User).where(User.id == int(token_data.sub)))
                user = result.scalar_one_or_none()
                if user:
                    return user
        except (JWTError, ValidationError):
            pass

    # 3. Hybrid fallback: allow implicit local identity only when no
    # credentials were provided AND the client is loopback (defense-in-depth;
    # gateway middleware already enforces this, but we double-check here).
    from app.core.mode_policy import is_hybrid
    if is_hybrid() and not has_credentials:
        if client_host is not None and not security._is_loopback(client_host):
            return None
        return await _get_or_create_local_user(session)

    return None


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
    token: Optional[str] = Depends(security.oauth2_scheme_optional),
    api_key: Optional[str] = Depends(api_key_header),
) -> User:
    """FastAPI dependency that returns the authenticated user or raises 401."""
    user = await _resolve_user(
        session, api_key=api_key, token=token,
        client_host=security.get_client_host(request),
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if hasattr(user, "is_active") and not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account disabled",
        )
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    # is_active check is enforced in get_current_user; this is a pass-through alias.
    return current_user


async def get_user_from_credentials(
    session: AsyncSession,
    api_key: Optional[str] = None,
    token: Optional[str] = None,
    client_host: Optional[str] = None,
) -> Optional[User]:
    """
    Resolve user from API key or JWT token (for WebSocket auth).

    This is a non-Depends version of get_current_user for use in
    WebSocket handlers where FastAPI dependency injection isn't available.

    Returns None if credentials are invalid (doesn't raise HTTPException).
    """
    return await _resolve_user(session, api_key=api_key, token=token, client_host=client_host)
