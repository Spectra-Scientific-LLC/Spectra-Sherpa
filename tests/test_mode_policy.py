"""Unit tests for the ``mode_policy`` helpers.

The mode-policy compatibility review concluded that no new helpers are
needed for the OSS bypass migrations: most sites map to existing helpers,
and the remaining case stays as-is. This file backfills explicit unit-test
coverage for the helpers the migrations rely on, so each migration PR can
assert "behavior matches the helper" without re-deriving truth tables.

Coverage shape: each helper is exercised across all three documented
modes (``local``, ``hybrid``, ``enterprise``). Helpers that depend on
the ``auth_policy`` contract are exercised against both registered
flag values.
"""

from __future__ import annotations

import pytest

from spectra_sherpa.app.contracts import auth_policy
from spectra_sherpa.app.core import mode_policy
from spectra_sherpa.app.core.config import app_config

MODES = ("local", "hybrid", "enterprise")


@pytest.fixture
def set_mode(monkeypatch: pytest.MonkeyPatch):
    """Set ``app_config.mode`` for the duration of a test."""

    def _set(mode: str) -> None:
        monkeypatch.setattr(app_config, "mode", mode)

    return _set


@pytest.fixture(autouse=True)
def _reset_auth_policy_flags():
    auth_policy._reset_for_tests()
    yield
    auth_policy._reset_for_tests()


# ── Identity shortcuts ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "mode,expected",
    [("local", True), ("hybrid", False), ("enterprise", False)],
)
def test_is_local(set_mode, mode: str, expected: bool) -> None:
    set_mode(mode)
    assert mode_policy.is_local() is expected


@pytest.mark.parametrize(
    "mode,expected",
    [("local", False), ("hybrid", True), ("enterprise", False)],
)
def test_is_hybrid(set_mode, mode: str, expected: bool) -> None:
    set_mode(mode)
    assert mode_policy.is_hybrid() is expected


@pytest.mark.parametrize(
    "mode,expected",
    [("local", False), ("hybrid", False), ("enterprise", True)],
)
def test_is_enterprise(set_mode, mode: str, expected: bool) -> None:
    set_mode(mode)
    assert mode_policy.is_enterprise() is expected


@pytest.mark.parametrize(
    "mode,expected",
    [("local", False), ("hybrid", True), ("enterprise", True)],
)
def test_is_multi_user(set_mode, mode: str, expected: bool) -> None:
    """``is_multi_user`` is the negation of ``is_local`` for the documented modes.

    This is the recommended migration target for ``main.py:88`` — the
    positive form reads better than ``not is_local()``.
    """
    set_mode(mode)
    assert mode_policy.is_multi_user() is expected


@pytest.mark.parametrize("mode", MODES)
def test_modes_are_mutually_exclusive(set_mode, mode: str) -> None:
    """Exactly one of is_local / is_hybrid / is_enterprise is True per mode."""
    set_mode(mode)
    truths = [mode_policy.is_local(), mode_policy.is_hybrid(), mode_policy.is_enterprise()]
    assert sum(truths) == 1


# ── Loopback ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "host,expected",
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("::ffff:127.0.0.1", True),
        ("10.0.0.1", False),
        ("example.com", False),
        ("", False),
        (None, False),
    ],
)
def test_is_loopback(host, expected: bool) -> None:
    """Fail-closed default: unknown / empty host is NOT loopback."""
    assert mode_policy.is_loopback(host) is expected


# ── Auth requirements ─────────────────────────────────────────────────


def test_requires_http_auth_local_never(set_mode) -> None:
    set_mode("local")
    assert mode_policy.requires_http_auth("127.0.0.1") is False
    assert mode_policy.requires_http_auth("10.0.0.1") is False


def test_blocks_local_network_client_default(set_mode, monkeypatch: pytest.MonkeyPatch) -> None:
    set_mode("local")
    monkeypatch.delenv("SPECTRA_SHERPA_ALLOW_LOCAL_NETWORK", raising=False)
    monkeypatch.delenv("SPECTRASHERPA_ALLOW_LOCAL_NETWORK", raising=False)
    assert mode_policy.blocks_local_network_client("127.0.0.1") is False
    assert mode_policy.blocks_local_network_client("::1") is False
    assert mode_policy.blocks_local_network_client("10.0.0.1") is True
    assert mode_policy.blocks_local_network_client(None) is True


def test_blocks_local_network_client_allows_explicit_opt_in(set_mode, monkeypatch: pytest.MonkeyPatch) -> None:
    set_mode("local")
    monkeypatch.setenv("SPECTRA_SHERPA_ALLOW_LOCAL_NETWORK", "true")
    assert mode_policy.blocks_local_network_client("10.0.0.1") is False


@pytest.mark.parametrize("mode", ["hybrid", "enterprise"])
def test_blocks_local_network_client_only_applies_to_local(set_mode, mode: str) -> None:
    set_mode(mode)
    assert mode_policy.blocks_local_network_client("10.0.0.1") is False


def test_requires_http_auth_hybrid_loopback_exempt(set_mode) -> None:
    set_mode("hybrid")
    assert mode_policy.requires_http_auth("127.0.0.1") is False
    assert mode_policy.requires_http_auth("10.0.0.1") is True


def test_requires_http_auth_enterprise_always(set_mode) -> None:
    set_mode("enterprise")
    assert mode_policy.requires_http_auth("127.0.0.1") is True
    assert mode_policy.requires_http_auth("10.0.0.1") is True


def test_requires_ws_auth_mirrors_http_auth(set_mode) -> None:
    """Documented invariant: WS auth uses the same rules as HTTP auth."""
    for mode in MODES:
        set_mode(mode)
        for host in ("127.0.0.1", "10.0.0.1"):
            assert mode_policy.requires_ws_auth(host) is mode_policy.requires_http_auth(host)


# ── Registration (depends on auth_policy contract) ───────────────────


def test_allows_registration_false_in_local_regardless_of_flag(set_mode) -> None:
    set_mode("local")
    auth_policy.set_registration_enabled(True)
    assert mode_policy.allows_registration() is False


def test_allows_registration_requires_both_multi_user_and_flag(set_mode) -> None:
    set_mode("hybrid")
    auth_policy.set_registration_enabled(False)
    assert mode_policy.allows_registration() is False
    auth_policy.set_registration_enabled(True)
    assert mode_policy.allows_registration() is True


def test_allows_registration_in_enterprise_with_flag(set_mode) -> None:
    set_mode("enterprise")
    auth_policy.set_registration_enabled(True)
    assert mode_policy.allows_registration() is True


# ── Limits / egress ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "mode,expected",
    [("local", False), ("hybrid", True), ("enterprise", True)],
)
def test_has_rate_limits(set_mode, mode: str, expected: bool) -> None:
    set_mode(mode)
    assert mode_policy.has_rate_limits() is expected


@pytest.mark.parametrize(
    "mode,expected",
    [("local", True), ("hybrid", False), ("enterprise", False)],
)
def test_export_always_allowed(set_mode, mode: str, expected: bool) -> None:
    set_mode(mode)
    assert mode_policy.export_always_allowed() is expected


def test_cors_allow_all_is_always_false(set_mode) -> None:
    """CORS is restricted to localhost origins in *every* mode."""
    for mode in MODES:
        set_mode(mode)
        assert mode_policy.cors_allow_all() is False


# ── API key validation ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "mode,expected",
    [("local", True), ("hybrid", False), ("enterprise", False)],
)
def test_api_key_always_valid(set_mode, mode: str, expected: bool) -> None:
    set_mode(mode)
    assert mode_policy.api_key_always_valid() is expected
    assert mode_policy.system_api_key_always_accepted() is expected
