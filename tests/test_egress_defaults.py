from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from spectra_sherpa.app.models.data_egress import UserEgressDefaults


@pytest.mark.asyncio
async def test_update_egress_defaults_clears_context_when_chat_disabled(
    auth_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import spectra_sherpa.app.core.config as config_mod

    monkeypatch.setattr(config_mod.app_config, "site_profile", None, raising=False)

    response = await auth_client.put(
        "/api/v1/egress/defaults",
        json={
            "allow_llm_chat": False,
            "allow_llm_context": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["allow_llm_chat"] is False
    assert body["allow_llm_context"] is False


@pytest.mark.asyncio
async def test_update_egress_defaults_forces_llm_chat_on_in_demo(
    auth_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import spectra_sherpa.app.core.config as config_mod

    monkeypatch.setattr(config_mod.app_config, "site_profile", "demo", raising=False)

    response = await auth_client.put(
        "/api/v1/egress/defaults",
        json={
            "allow_llm_chat": False,
            "allow_llm_context": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["allow_llm_chat"] is True
    assert body["allow_llm_context"] is True


@pytest.mark.asyncio
async def test_ensure_egress_defaults_normalizes_demo_rows(
    test_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import spectra_sherpa.app.core.config as config_mod
    import spectra_sherpa.app.core.startup as startup_mod

    defaults = UserEgressDefaults(
        user_id=test_user.id,
        allow_llm_chat=False,
        allow_llm_context=False,
    )
    test_session.add(defaults)
    await test_session.commit()

    @asynccontextmanager
    async def _session_ctx():
        yield test_session

    monkeypatch.setattr(config_mod.app_config, "site_profile", "demo", raising=False)
    monkeypatch.setattr(startup_mod, "async_session", lambda: _session_ctx())

    await startup_mod.ensure_egress_defaults()

    refreshed = await test_session.scalar(select(UserEgressDefaults).where(UserEgressDefaults.user_id == test_user.id))
    assert refreshed is not None
    assert refreshed.allow_llm_chat is True
    assert refreshed.allow_llm_context is True


@pytest.mark.asyncio
async def test_ensure_egress_defaults_normalizes_invalid_non_demo_rows(
    test_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import spectra_sherpa.app.core.config as config_mod
    import spectra_sherpa.app.core.startup as startup_mod

    defaults = UserEgressDefaults(
        user_id=test_user.id,
        allow_llm_chat=False,
        allow_llm_context=True,
    )
    test_session.add(defaults)
    await test_session.commit()

    @asynccontextmanager
    async def _session_ctx():
        yield test_session

    monkeypatch.setattr(config_mod.app_config, "site_profile", None, raising=False)
    monkeypatch.setattr(startup_mod, "async_session", lambda: _session_ctx())

    await startup_mod.ensure_egress_defaults()

    refreshed = await test_session.scalar(select(UserEgressDefaults).where(UserEgressDefaults.user_id == test_user.id))
    assert refreshed is not None
    assert refreshed.allow_llm_chat is False
    assert refreshed.allow_llm_context is False
