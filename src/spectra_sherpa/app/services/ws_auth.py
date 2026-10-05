"""
WebSocket authentication helpers.

WebSocket auth is intentionally narrower than HTTP auth:

- Local or explicitly exempted loopback connections resolve an implicit local user
- Managed connections must authenticate in the first
  WebSocket message via ``{"type": "authenticate", ...}``

Connection-time credentials in WS headers or query params are no longer
accepted. This keeps the runtime model simple and avoids token leakage via
URLs, server logs, and proxy metadata.

**Why this file exists in the OSS repo:**  The runtime authentication
paths are exercised only when a commercial server extension is installed. In a pure OSS
local deployment, ``requires_auth`` is always False and the implicit user
is resolved immediately — the ``authenticate`` message path is never
reached. The code lives here so that all three modes are tested together
and server extensions can register behavior without forking.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket, status

from spectra_sherpa.app.api.deps import get_user_from_credentials, invalidate_api_key_cache
from spectra_sherpa.app.contracts.auth_resolver import get_extra_bearer_token_validator
from spectra_sherpa.app.db.session import async_session

logger = logging.getLogger(__name__)


async def resolve_initial_ws_user(
    websocket: WebSocket,
    *,
    client_host: str,
    requires_auth: bool,
) -> Any:
    """Resolve the initial WebSocket user.

    Connection-time credential transport has been removed. The only initial
    identity that may exist before the message loop is the implicit local user
    for local mode or explicitly exempted loopback connections.
    """
    if requires_auth:
        return None

    async with async_session() as session:
        return await get_user_from_credentials(session, client_host=client_host)


async def validate_ws_token(token: str) -> dict | None:
    """Validate a raw bearer token using the server-injected validator.

    Returns the decoded payload if the token passes enterprise session policy
    (expiry, revocation, active account), or ``None`` if it does not. In pure
    OSS local mode no validator is injected and this returns ``None``.
    """
    validator = get_extra_bearer_token_validator()
    if validator is None:
        return None
    return await validator(token)


async def revalidate_ws_token(token: str | None, *, user_id: int | None = None) -> bool:
    """Revalidate a stored bearer token before an action or protected delivery.

    Returns ``True`` if the token is still valid or if no managed validator
    is injected (pure OSS local mode has no session-revocation policy). A
    token that fails an injected validator is treated as invalid, which lets
    an already-open WebSocket connection be promptly closed after password
    rotation, revocation, or account deactivation.
    """
    if token is None:
        return True
    validator = get_extra_bearer_token_validator()
    if validator is None:
        return True
    try:
        payload = await validator(token)
        return payload is not None and (user_id is None or str(payload.get("sub")) == str(user_id))
    except Exception:
        # An unavailable session authority must not leave retained subscriptions
        # authorized. Never include the credential in the diagnostic.
        logger.warning("WebSocket session authority failed")
        return False


async def _revalidate_ws_credentials(websocket: WebSocket) -> bool:
    user_id = getattr(websocket.state, "ws_auth_user_id", None)
    api_key = getattr(websocket.state, "ws_auth_api_key", None)
    if api_key is None:
        return await revalidate_ws_token(getattr(websocket.state, "ws_auth_token", None), user_id=user_id)
    try:
        # Do not let a cached key-to-user mapping outlive key revocation.
        invalidate_api_key_cache(api_key)
        async with async_session() as session:
            user = await get_user_from_credentials(session, api_key=api_key, client_host="remote")
        return user is not None and user.is_active and user.id == user_id
    except Exception:
        logger.warning("WebSocket API key authority failed")
        return False


async def require_live_ws_session(websocket: WebSocket) -> bool:
    """Retire an invalid managed session before an action or event delivery."""
    from spectra_sherpa.app.services.websocket_manager import ws_manager

    if getattr(websocket.state, "ws_session_invalidated", False):
        return False
    if await _revalidate_ws_credentials(websocket):
        return True
    websocket.state.ws_session_invalidated = True
    # Remove every subscription before closing, including those on other channels.
    await ws_manager.disconnect(websocket)
    try:
        await websocket.send_json({"type": "error", "detail": "Session invalidated"})
    finally:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
    return False


async def authenticate_ws_message(
    payload: dict,
    *,
    client_host: str,
    current_user: Any,
) -> Any:
    """Resolve a user from a first-message ``authenticate`` action.

    Reject mixed or invalid credentials. A retained identity must never rescue
    failed authentication or be paired with a different credential's authority.
    """
    auth_token = payload.get("token")
    auth_api_key = payload.get("api_key")
    if auth_token and auth_api_key:
        return None
    async with async_session() as session:
        # A credential-free frame may resolve implicit local identity anew, but
        # must never turn a retained remote identity into an unvalidated session.
        return await get_user_from_credentials(session, token=auth_token, api_key=auth_api_key, client_host=client_host)


def require_authenticated_action(
    *,
    requires_auth: bool,
    ws_user: Any,
) -> bool:
    """Return True if this action should be rejected (unauthenticated enterprise)."""
    return requires_auth and ws_user is None


async def stamp_last_active(user: Any) -> None:
    """Update last_active timestamp (fire-and-forget)."""
    if user is None or getattr(user, "id", None) is None:
        return
    try:
        async with async_session() as session:
            from sqlalchemy import func as _sa_func
            from sqlalchemy import update as _sa_update

            from spectra_sherpa.app.models.user import User as _UserModel

            await session.execute(
                _sa_update(_UserModel).where(_UserModel.id == user.id).values(last_active=_sa_func.now())
            )
            await session.commit()
    except Exception:
        pass  # Non-critical
