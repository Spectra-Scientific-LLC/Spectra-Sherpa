from __future__ import annotations

import pytest

from spectra_sherpa.app.core.config import AppConfig


def _clear_mode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "APP_MODE",
        "EGRESS_ENABLED",
        "SITE_PROFILE",
        "ENTERPRISE_PASSWORD",
        "DEMO_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)


def test_from_env_local_defaults_to_egress_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_mode_env(monkeypatch)
    monkeypatch.setenv("APP_MODE", "local")

    cfg = AppConfig.from_env()

    assert cfg.mode == "local"
    assert cfg.egress_enabled is False
    assert cfg.site_profile is None
    assert cfg.to_client_safe()["egressEnabled"] is False


def test_from_env_local_allows_explicit_egress_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_mode_env(monkeypatch)
    monkeypatch.setenv("APP_MODE", "local")
    monkeypatch.setenv("EGRESS_ENABLED", "true")

    cfg = AppConfig.from_env()

    assert cfg.mode == "local"
    assert cfg.egress_enabled is True


def test_from_env_rejects_unsupported_app_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_mode_env(monkeypatch)
    monkeypatch.setenv("APP_MODE", "demo")

    with pytest.raises(ValueError, match="Unsupported APP_MODE"):
        AppConfig.from_env()


def test_oss_rejects_uninstalled_product_mode(monkeypatch):
    from spectra_sherpa.app.contracts import runtime_mode

    monkeypatch.setattr(runtime_mode, "_policies", {})
    monkeypatch.setenv("APP_MODE", "hybrid")
    with pytest.raises(ValueError, match="owning product"):
        AppConfig.from_env()
