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


def test_from_env_hybrid_defaults_to_egress_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_mode_env(monkeypatch)
    monkeypatch.setenv("APP_MODE", "hybrid")

    cfg = AppConfig.from_env()

    assert cfg.mode == "hybrid"
    assert cfg.egress_enabled is True
    assert cfg.site_profile is None
    assert cfg.to_client_safe()["egressEnabled"] is True


def test_from_env_local_allows_explicit_egress_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_mode_env(monkeypatch)
    monkeypatch.setenv("APP_MODE", "local")
    monkeypatch.setenv("EGRESS_ENABLED", "true")

    cfg = AppConfig.from_env()

    assert cfg.mode == "local"
    assert cfg.egress_enabled is True


def test_from_env_hybrid_allows_explicit_egress_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_mode_env(monkeypatch)
    monkeypatch.setenv("APP_MODE", "hybrid")
    monkeypatch.setenv("EGRESS_ENABLED", "false")

    cfg = AppConfig.from_env()

    assert cfg.mode == "hybrid"
    assert cfg.egress_enabled is False


def test_from_env_hybrid_accepts_site_profile_without_changing_runtime_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_mode_env(monkeypatch)
    monkeypatch.setenv("APP_MODE", "hybrid")
    monkeypatch.setenv("SITE_PROFILE", "internal")

    cfg = AppConfig.from_env()
    safe = cfg.to_client_safe()

    assert cfg.mode == "hybrid"
    assert cfg.site_profile == "internal"
    assert safe["mode"] == "hybrid"
    assert safe["siteProfile"] == "internal"
    assert safe["demo"] is None  # Not a demo profile
