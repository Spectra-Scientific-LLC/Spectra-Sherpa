from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

import app.db.session as db_session
from app.core import security
from app.core.config import app_config
from app.models.user import User


@pytest.mark.asyncio
async def test_gateway_accepts_user_api_key(
    client,
    test_session,
    test_engine,
    monkeypatch,
):
    """
    Ensure the gateway middleware accepts a user API key in non-local mode.

    The test client connects via ASGI transport from 127.0.0.1, which is
    considered loopback and exempt from auth in hybrid mode.  We patch
    ``get_client_host`` to simulate a remote client so the gateway actually
    enforces authentication.
    """
    original_mode = app_config.mode
    app_config.mode = "hybrid"
    try:
        # Point gateway DB access to the test engine
        test_sessionmaker = sessionmaker(
            test_engine, class_=AsyncSession, expire_on_commit=False
        )
        monkeypatch.setattr(db_session, "async_session", test_sessionmaker)

        # Simulate a remote (non-loopback) client so gateway enforces auth
        monkeypatch.setattr(
            security, "get_client_host", lambda _req: "203.0.113.42"
        )

        # Create a user with an API key hash
        api_key = "sk_test_user_key_1234567890"
        api_key_hash = security.get_password_hash(api_key)
        user = User(
            username="gatewayuser",
            password_hash="testhash",
            api_key_hash=api_key_hash,
        )
        test_session.add(user)
        await test_session.commit()

        # No auth should be blocked in hybrid mode for remote clients
        resp = await client.get("/api/v1/experiments")
        assert resp.status_code == 401

        # User API key should pass the gateway middleware
        resp = await client.get(
            "/api/v1/experiments", headers={"X-API-Key": api_key}
        )
        assert resp.status_code == 200
    finally:
        app_config.mode = original_mode
