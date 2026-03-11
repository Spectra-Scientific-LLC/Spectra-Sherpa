from __future__ import annotations

from typing import TYPE_CHECKING, AsyncGenerator, Optional

if TYPE_CHECKING:
    from spectra_sherpa.app.models.experiment import Experiment
    from spectra_sherpa.app.models.project import Project
    from spectra_sherpa.app.models.workflow import Workflow

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader
from jwt.exceptions import PyJWTError as JWTError
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app import schemas
from spectra_sherpa.app.core import security
from spectra_sherpa.app.core.config import app_config, settings
from spectra_sherpa.app.core.mode_policy import is_hybrid, is_local, is_loopback

logger = __import__("logging").getLogger(__name__)
from spectra_sherpa.app.db.session import async_session
from spectra_sherpa.app.models.user import User


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
    if is_local():
        return await _get_or_create_local_user(session)

    # If system-key auth is disabled, ignore APP_API_KEY for dependency auth.
    # This preserves hybrid loopback fallback behavior when stale keys are present
    # in local storage, while gateway auth still blocks non-loopback requests.
    if api_key == settings.api_key and not security.is_system_api_key_auth_enabled():
        api_key = None
    has_credentials = bool(api_key or token)

    # 1. API Key Auth (Machine-to-Machine / Cloud Node)
    if api_key:
        # Fast path: global system key
        if api_key == settings.api_key:
            if not security.is_system_api_key_auth_enabled():
                return None
            # Map to a real DB user instead of a synthetic superuser so auth
            # honors actual account state/permissions in non-local modes.
            result = await session.execute(select(User).where(User.is_active.is_(True)).order_by(User.id).limit(1))
            return result.scalar_one_or_none()

        # Check cache first (avoids expensive bcrypt on every request)
        cached_user_id = security._get_cached_user_id(api_key)
        if cached_user_id is not None:
            result = await session.execute(
                select(User).where(User.id == cached_user_id, User.is_active.is_(True))
            )
            user = result.scalar_one_or_none()
            if user:
                return user

        # Cache miss — do expensive bcrypt verification against active users only.
        # We iterate rather than query by hash because bcrypt salts are random.
        result = await session.execute(
            select(User).where(User.api_key_hash.isnot(None), User.is_active.is_(True))
        )
        for user in result.scalars():
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
    if is_hybrid() and not has_credentials:
        if client_host is not None and not is_loopback(client_host):
            logger.warning(
                "Hybrid mode: rejected credential-free request from non-loopback host %r",
                client_host,
            )
            return None
        logger.debug(
            "Hybrid mode: granting implicit local identity to loopback client %r",
            client_host,
        )
        return await _get_or_create_local_user(session)

    return None


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
    token: Optional[str] = Depends(security.get_bearer_token_optional),
    api_key: Optional[str] = Depends(api_key_header),
) -> User:
    """FastAPI dependency that returns the authenticated user or raises 401."""
    user = await _resolve_user(
        session,
        api_key=api_key,
        token=token,
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


def demo_guard(capability: str):
    """Factory for demo mode route guards. Checks the Demo Contract."""

    def _guard():
        if app_config.site_profile == "demo":
            contract = app_config.demo_contract
            if capability in contract.disabled_capabilities:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="This feature is not available in demo mode.",
                )

    return _guard


def check_demo_capability(capability: str) -> None:
    """Callable guard for use inside handler bodies (not as a Depends).

    Use this when the block is conditional on request data — e.g. only
    when ``initial_data`` is non-empty — rather than on every request
    to the endpoint.
    """
    if app_config.site_profile == "demo":
        contract = app_config.demo_contract
        if capability in contract.disabled_capabilities:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This feature is not available in demo mode.",
            )


# ── Shared entity loading helpers ─────────────────────────────────────
# Use these in route handlers to replace inline load-or-404 boilerplate.


async def require_workflow(
    workflow_id: int,
    user_id: int,
    session: AsyncSession,
    *,
    options: list | None = None,
) -> "Workflow":
    """Load a workflow owned by *user_id*, or raise 404.

    Parameters
    ----------
    options
        SQLAlchemy loader options (e.g. ``selectinload(Workflow.nodes)``).
    """
    from spectra_sherpa.app.models.workflow import Workflow

    query = select(Workflow).where(Workflow.id == workflow_id, Workflow.user_id == user_id)
    if options:
        query = query.options(*options)
    result = await session.execute(query)
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


async def require_project(
    project_id: int,
    user_id: int,
    session: AsyncSession,
) -> "Project":
    """Load a project owned by *user_id*, or raise 404."""
    from spectra_sherpa.app.models.project import Project

    result = await session.execute(select(Project).where(Project.id == project_id, Project.user_id == user_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def require_experiment(
    experiment_id: int,
    user_id: int,
    session: AsyncSession,
) -> "Experiment":
    """Load an experiment owned by *user_id*, or raise 404."""
    from spectra_sherpa.app.models.experiment import Experiment

    result = await session.execute(
        select(Experiment).where(Experiment.id == experiment_id, Experiment.user_id == user_id)
    )
    experiment = result.scalar_one_or_none()
    if experiment is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return experiment


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
