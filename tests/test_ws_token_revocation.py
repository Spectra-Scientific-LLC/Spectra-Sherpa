"""DEP-01 regression: WebSocket bearer-token validation matches HTTP policy.

These tests exercise the OSS side of the validator contract without the
full server stack. Server-side validator implementation is covered by
``packages/spectra-server/tests/test_enterprise_enforcement.py``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from spectra_sherpa.app.api import deps
from spectra_sherpa.app.contracts.auth_resolver import (
    clear_extra_bearer_token_resolver,
    clear_extra_bearer_token_validator,
    set_extra_bearer_token_resolver,
    set_extra_bearer_token_validator,
)
from spectra_sherpa.app.core.config import app_config
from spectra_sherpa.app.models.user import User
from spectra_sherpa.app.services.ws_auth import (
    authenticate_ws_message,
    revalidate_ws_token,
    validate_ws_token,
)


class _FakeSession:
    def __init__(self, user: User | None):
        self._user = user

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, stmt):
        class _Result:
            def scalar_one_or_none(self_inner):
                # Honor ``WHERE ... User.is_active IS true`` so that inactive
                # users are not resolved even when a validator accepts the token.
                if (
                    self._user is not None
                    and not self._user.is_active
                    and "is_active" in str(getattr(stmt, "whereclause", "")).lower()
                ):
                    return None
                return self._user

            def one_or_none(self_inner):
                return (self._user,)

        # ``deps._resolve_user`` uses ``scalar_one_or_none`` for user lookups.
        return _Result()


@pytest.fixture(autouse=True)
def _managed_mode():
    original_mode = app_config.mode
    app_config.mode = "enterprise"
    clear_extra_bearer_token_validator()
    clear_extra_bearer_token_resolver()
    yield
    app_config.mode = original_mode
    clear_extra_bearer_token_validator()
    clear_extra_bearer_token_resolver()


@pytest.mark.asyncio
async def test_resolve_user_prefers_validator_and_rejects_invalid_token():
    """When a validator is injected, an invalid bearer token does not resolve."""
    user = User(id=42, username="test", is_active=True)

    async def _validator(_token: str) -> dict | None:
        return None

    set_extra_bearer_token_validator(_validator)

    resolved = await deps._resolve_user(
        _FakeSession(user),
        token="revoked-jwt",
        client_host="10.0.0.1",
    )
    assert resolved is None


@pytest.mark.asyncio
async def test_resolve_user_accepts_valid_token_from_validator():
    """A validator returning a valid payload lets the user resolve."""
    user = User(id=42, username="test", is_active=True)

    async def _validator(token: str) -> dict | None:
        if token == "valid-jwt":
            return {"sub": "42"}
        return None

    set_extra_bearer_token_validator(_validator)

    resolved = await deps._resolve_user(
        _FakeSession(user),
        token="valid-jwt",
        client_host="10.0.0.1",
    )
    assert resolved is user


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"token": "invalid"}, {"api_key": "revoked"}])
async def test_failed_remote_reauthentication_cannot_rescue_cached_user(monkeypatch, payload):
    monkeypatch.setattr("spectra_sherpa.app.services.ws_auth.async_session", lambda: _FakeSession(None))
    assert (
        await authenticate_ws_message(
            payload, client_host="10.0.0.1", current_user=SimpleNamespace(id=7, is_active=True)
        )
        is None
    )


@pytest.mark.asyncio
async def test_resolve_user_falls_back_to_subject_resolver_when_no_validator():
    """Legacy deployments without the validator contract still resolve by sub."""
    user = User(id=42, username="test", is_active=True)

    async def _resolver(token: str) -> int | None:
        if token == "legacy-jwt":
            return 42
        return None

    set_extra_bearer_token_resolver(_resolver)

    resolved = await deps._resolve_user(
        _FakeSession(user),
        token="legacy-jwt",
        client_host="10.0.0.1",
    )
    assert resolved is user


@pytest.mark.asyncio
async def test_resolve_user_rejects_inactive_user_even_with_valid_token():
    """The validator may pass, but the local user record still gates access."""
    inactive_user = User(id=42, username="test", is_active=False)

    async def _validator(_token: str) -> dict | None:
        return {"sub": "42"}

    set_extra_bearer_token_validator(_validator)

    resolved = await deps._resolve_user(
        _FakeSession(inactive_user),
        token="valid-jwt",
        client_host="10.0.0.1",
    )
    assert resolved is None


@pytest.mark.asyncio
async def test_validate_ws_token_uses_injected_validator():
    async def _validator(token: str) -> dict | None:
        if token == "ok":
            return {"sub": "1"}
        return None

    set_extra_bearer_token_validator(_validator)
    assert await validate_ws_token("ok") == {"sub": "1"}
    assert await validate_ws_token("bad") is None


@pytest.mark.asyncio
async def test_validate_ws_token_returns_none_without_validator():
    """Pure OSS local mode has no validator; the helper returns None."""
    assert await validate_ws_token("any-token") is None


@pytest.mark.asyncio
async def test_revalidate_ws_token_reflects_validator_state():
    calls: list[str] = []

    async def _validator(token: str) -> dict | None:
        calls.append(token)
        if len(calls) == 1:
            return {"sub": "1"}
        return None

    set_extra_bearer_token_validator(_validator)
    assert await revalidate_ws_token("jwt-1") is True
    assert await revalidate_ws_token("jwt-1") is False
    # No stored token means there is nothing managed to revalidate.
    assert await revalidate_ws_token(None) is True


@pytest.mark.asyncio
async def test_authenticate_ws_message_valid_token_resolves_user(monkeypatch):
    user = SimpleNamespace(id=7, is_active=True)
    monkeypatch.setattr(
        "spectra_sherpa.app.services.ws_auth.async_session",
        lambda: _FakeSession(user),
    )

    async def _resolve_user(_session, api_key=None, token=None, client_host=None):
        if token == "jwt-1":
            return user
        return None

    monkeypatch.setattr(
        "spectra_sherpa.app.services.ws_auth.get_user_from_credentials",
        _resolve_user,
    )

    resolved = await authenticate_ws_message(
        {"token": "jwt-1"},
        client_host="10.0.0.1",
        current_user=None,
    )
    assert resolved is user


@pytest.mark.asyncio
async def test_token_subject_must_match_retained_identity():
    async def validator(_token):
        return {"sub": "7"}

    set_extra_bearer_token_validator(validator)
    assert await revalidate_ws_token("jwt", user_id=7)
    assert not await revalidate_ws_token("jwt", user_id=8)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"token": "jwt", "api_key": "key"}])
async def test_ambiguous_authentication_does_not_retain_old_user(payload):
    assert await authenticate_ws_message(payload, client_host="10.0.0.1", current_user=SimpleNamespace(id=7)) is None
