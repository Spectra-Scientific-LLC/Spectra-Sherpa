from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.test_mode_matrix import _make_config


@pytest.mark.asyncio
async def test_local_config_chat_assistant_depends_only_on_byo_endpoint(monkeypatch):
    from spectra_sherpa.app.api.v1.routes import config as config_routes
    from spectra_sherpa.app.services import basic_chat

    monkeypatch.setattr(config_routes, "app_config", _make_config(mode="local"))

    async def _provider_available(*args, **kwargs):
        return True

    monkeypatch.setattr(
        config_routes,
        "_check_provider_availability",
        _provider_available,
    )
    monkeypatch.setattr(basic_chat, "is_configured", lambda: False)

    response = await config_routes.get_config(session=MagicMock(), current_user=None)

    assert response["features"]["chatAssistant"] is False
    assert all(not entry["enabled"] for entry in response["llms"].values())


@pytest.mark.asyncio
async def test_local_config_enables_chat_assistant_when_byo_endpoint_is_configured(monkeypatch):
    from spectra_sherpa.app.api.v1.routes import config as config_routes
    from spectra_sherpa.app.services import basic_chat

    monkeypatch.setattr(config_routes, "app_config", _make_config(mode="local"))

    async def _provider_unavailable(*args, **kwargs):
        return False

    monkeypatch.setattr(
        config_routes,
        "_check_provider_availability",
        _provider_unavailable,
    )
    monkeypatch.setattr(basic_chat, "is_configured", lambda: True)

    response = await config_routes.get_config(session=MagicMock(), current_user=None)

    assert response["features"]["chatAssistant"] is True
    assert all(not entry["enabled"] for entry in response["llms"].values())
