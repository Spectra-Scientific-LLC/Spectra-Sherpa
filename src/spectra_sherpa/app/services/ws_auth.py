"""
WebSocket authentication helpers.

WebSocket auth is intentionally narrower than HTTP auth:

- Local/hybrid loopback connections resolve an implicit local user
- Remote hybrid/enterprise connections must authenticate in the first
  WebSocket message via ``{"type": "authenticate", ...}``

Connection-time credentials in WS headers or query params are no longer
accepted. This keeps the runtime model simple and avoids token leakage via
URLs, server logs, and proxy metadata.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

from spectra_sherpa.app.api.deps import get_user_from_credentials
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
    for local mode or loopback hybrid connections.
    """
    if requires_auth:
        return None

    async with async_session() as session:
        return await get_user_from_credentials(session, client_host=client_host)


async def authenticate_ws_message(
    payload: dict,
    *,
    client_host: str,
    current_user: Any,
) -> Any:
    """Resolve a user from a first-message ``authenticate`` action.

    Returns the resolved user, or *current_user* unchanged if the message
    credentials don't resolve to anyone better.
    """
    auth_token = payload.get("token")
    auth_api_key = payload.get("api_key")
    ws_user = current_user

    if auth_token or auth_api_key:
        async with async_session() as session:
            if auth_token:
                token_user = await get_user_from_credentials(session, token=auth_token, client_host=client_host)
                if token_user is not None:
                    ws_user = token_user
            if auth_api_key:
                api_key_user = await get_user_from_credentials(session, api_key=auth_api_key, client_host=client_host)
                if api_key_user is not None:
                    ws_user = api_key_user

    return ws_user


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
