from __future__ import annotations

import pytest
from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

import spectra_sherpa.app.db.session as db_session
from spectra_sherpa.app.contracts import (
    clear_extra_user_api_key_authenticator,
    set_extra_user_api_key_authenticator,
)
from spectra_sherpa.app.core import security
from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.main import create_app
from spectra_sherpa.app.models.user import User


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

    The injected authenticator mirrors the server's production path —
    hash the candidate with sha256 and compare against the stored
    digest (see ``spectrasherpa_server.security.verify_api_key_hash``).
    No dependency on OSS password-hashing primitives, which Phase 2 is
    deleting from OSS.
    """
    import hashlib
    import hmac

    original_mode = app_config.mode
    app_config.mode = "hybrid"
    try:
        # Point gateway DB access to the test engine
        test_sessionmaker = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(db_session, "async_session", test_sessionmaker)

        # Simulate a remote (non-loopback) client so gateway enforces auth
        monkeypatch.setattr(security, "get_client_host", lambda _req: "203.0.113.42")

        # Create a user and inject a server-style managed API-key authenticator.
        api_key = "sk_test_user_key_1234567890"
        user = User(username="gatewayuser")
        test_session.add(user)
        await test_session.commit()
        api_key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()

        async def _authenticate_user_api_key(candidate: str, _session: AsyncSession) -> int | None:
            candidate_hash = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
            if hmac.compare_digest(candidate_hash, api_key_hash):
                return user.id
            return None

        set_extra_user_api_key_authenticator(_authenticate_user_api_key)

        # No auth should be blocked in hybrid mode for remote clients
        resp = await client.get("/api/v1/experiments")
        assert resp.status_code == 401

        # User API key should pass the gateway middleware
        resp = await client.get("/api/v1/experiments", headers={"X-API-Key": api_key})
        assert resp.status_code == 200
    finally:
        clear_extra_user_api_key_authenticator()
        app_config.mode = original_mode


@pytest.mark.asyncio
async def test_gateway_allows_deployment_key_on_subscription_overlay_path(
    client,
    test_engine,
    monkeypatch,
):
    original_mode = app_config.mode
    app_config.mode = "enterprise"
    try:
        test_sessionmaker = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(db_session, "async_session", test_sessionmaker)
        monkeypatch.setattr(security, "get_client_host", lambda _req: "203.0.113.42")

        router = APIRouter()

        @router.get("/config/subscription")
        async def _subscription():
            return {"ok": True}

        app = create_app(
            extra_routers=[(router, {"prefix": "/api/v1", "tags": ["test"]})],
            include_server_routers=False,
        )

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/config/subscription", headers={"X-Deployment-Key": "dk_test"})

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
    finally:
        app_config.mode = original_mode


@pytest.mark.asyncio
async def test_gateway_allows_deployment_key_on_sherpa_route(
    client,
    test_engine,
    monkeypatch,
):
    original_mode = app_config.mode
    app_config.mode = "enterprise"
    try:
        test_sessionmaker = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(db_session, "async_session", test_sessionmaker)
        monkeypatch.setattr(security, "get_client_host", lambda _req: "203.0.113.42")

        router = APIRouter()

        @router.post("/sherpa/chat")
        async def _chat():
            return {"ok": True}

        app = create_app(
            extra_routers=[(router, {"prefix": "/api/v1", "tags": ["test"]})],
            include_server_routers=False,
        )

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.post("/api/v1/sherpa/chat", headers={"X-Deployment-Key": "dk_test"})

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
    finally:
        app_config.mode = original_mode


@pytest.mark.asyncio
async def test_gateway_allows_deployment_key_on_conversations_route(
    client,
    test_engine,
    monkeypatch,
):
    original_mode = app_config.mode
    app_config.mode = "enterprise"
    try:
        test_sessionmaker = sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(db_session, "async_session", test_sessionmaker)
        monkeypatch.setattr(security, "get_client_host", lambda _req: "203.0.113.42")

        router = APIRouter()

        @router.get("/conversations")
        async def _conversations():
            return [{"id": "c1"}]

        app = create_app(
            extra_routers=[(router, {"prefix": "/api/v1", "tags": ["test"]})],
            include_server_routers=False,
        )

        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            resp = await ac.get("/api/v1/conversations", headers={"X-Deployment-Key": "dk_test"})

        assert resp.status_code == 200
        assert resp.json() == [{"id": "c1"}]
    finally:
        app_config.mode = original_mode
