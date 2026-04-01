"""
WebSocket authentication helpers.

Extracts the auth resolution logic from ``main.websocket_endpoint`` into
small, testable functions with explicit precedence rules.

Credential transport precedence (highest → lowest):
1. First-message ``authenticate`` action  ← canonical path (browser-safe)
2. ``Authorization`` header / ``X-API-Key`` header  ← CLI/SDK/proxy clients
3. Query params ``?token=...&api_key=...``  ← deprecated, will warn

Identity mode (determined by ``mode_policy``):
- Local/hybrid loopback → implicit user (no credentials required)
- Remote hybrid/enterprise → explicit credentials required
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

from spectra_sherpa.app.api.deps import get_user_from_credentials
from spectra_sherpa.app.core.security import (
    is_valid_api_key,
    is_valid_bearer_token,
)
from spectra_sherpa.app.db.session import async_session

logger = logging.getLogger(__name__)


async def resolve_initial_ws_user(
    websocket: WebSocket,
    *,
    client_host: str,
    requires_auth: bool,
) -> tuple[Any, bool]:
    """Resolve a user from connection-time credentials (headers / query params).

    Returns ``(user, has_credentials)`` where *user* may be ``None`` if no
    valid credentials were found.

    Precedence:
    - Bearer token (header or query param)
    - API key (header or query param)
    - Implicit loopback identity (local/hybrid only)
    """
    api_key = websocket.headers.get("x-api-key") or websocket.query_params.get("api_key")
    auth_header = websocket.headers.get("authorization", "")
    token = auth_header[7:] if auth_header.startswith("Bearer ") else websocket.query_params.get("token")
    has_credentials = bool(token or api_key)

    # Deprecation warning for query-param credentials
    if websocket.query_params.get("token") or websocket.query_params.get("api_key"):
        logger.warning(
            "WebSocket credentials via query params are deprecated and will be "
            "removed in a future release. Use the first-message 'authenticate' "
            "action instead. client=%s",
            client_host,
        )

    # Validate provided credentials in auth-required mode
    if requires_auth and has_credentials:
        token_valid = bool(token) and is_valid_bearer_token(token)
        api_key_valid = bool(api_key) and await is_valid_api_key(api_key)
        if not (token_valid or api_key_valid):
            return None, True  # Credentials present but invalid

    # Resolve user from credentials
    ws_user = None
    async with async_session() as session:
        if token:
            ws_user = await get_user_from_credentials(session, token=token, client_host=client_host)
        if ws_user is None and api_key:
            ws_user = await get_user_from_credentials(session, api_key=api_key, client_host=client_host)
        if ws_user is None and not has_credentials:
            ws_user = await get_user_from_credentials(session, client_host=client_host)

    # Stale credentials on loopback: fall back to implicit identity
    if has_credentials and ws_user is None and not requires_auth:
        logger.debug("Stale WS credentials on loopback — falling back to implicit identity")
        async with async_session() as session:
            ws_user = await get_user_from_credentials(session, client_host=client_host)

    return ws_user, has_credentials


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
                ws_user = await get_user_from_credentials(session, token=auth_token, client_host=client_host) or ws_user
            if ws_user is None and auth_api_key:
                ws_user = (
                    await get_user_from_credentials(session, api_key=auth_api_key, client_host=client_host) or ws_user
                )

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
