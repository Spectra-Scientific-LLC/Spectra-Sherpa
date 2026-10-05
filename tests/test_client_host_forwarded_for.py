"""Regression tests for ``get_client_host`` X-Forwarded-For handling.

The gateway uses the resolved client IP for security decisions — loopback
auth exemptions (hybrid mode) and the per-IP login rate limiter. A remote
caller must not be able to forge that IP by injecting an ``X-Forwarded-For``
value, so the resolver takes the right-most address that is not itself a
trusted proxy, never the spoofable left-most entry.
"""

from __future__ import annotations

import ipaddress
from types import SimpleNamespace

import pytest

from spectra_sherpa.app.core import security


def _make_request(*, peer: str, xff: str | None):
    headers = {}
    if xff is not None:
        headers["x-forwarded-for"] = xff
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


@pytest.fixture
def trusted_proxy(monkeypatch):
    """Trust the 172.28.0.0/16 Docker bridge network, like the prod compose."""
    monkeypatch.setattr(security, "_TRUST_PROXY", True)
    monkeypatch.setattr(
        security,
        "_TRUSTED_PROXY_CIDRS",
        (ipaddress.ip_network("172.28.0.0/16"),),
    )


class TestGetClientHostForwardedFor:
    def test_spoofed_leftmost_loopback_is_ignored(self, trusted_proxy):
        # Attacker prepends 127.0.0.1; real hops (their IP + the internal
        # proxy) are appended to the right by Caddy/nginx.
        request = _make_request(
            peer="172.28.0.6",
            xff="127.0.0.1, 9.9.9.9, 172.28.0.5",
        )
        assert security.get_client_host(request) == "9.9.9.9"

    def test_real_client_behind_single_trusted_proxy(self, trusted_proxy):
        request = _make_request(peer="172.28.0.6", xff="203.0.113.7, 172.28.0.5")
        assert security.get_client_host(request) == "203.0.113.7"

    def test_untrusted_direct_peer_ignores_forwarded_header(self, trusted_proxy):
        # Direct peer is not a trusted proxy — the header is not honored at all.
        request = _make_request(peer="203.0.113.9", xff="127.0.0.1")
        assert security.get_client_host(request) == "203.0.113.9"

    def test_trust_proxy_disabled_ignores_forwarded_header(self, monkeypatch):
        monkeypatch.setattr(security, "_TRUST_PROXY", False)
        request = _make_request(peer="172.28.0.6", xff="127.0.0.1")
        assert security.get_client_host(request) == "172.28.0.6"

    def test_all_hops_trusted_falls_back_to_direct_peer(self, trusted_proxy):
        # No untrusted address in the chain — fall back to the (trusted) peer
        # rather than returning an attacker-controllable value.
        request = _make_request(peer="172.28.0.6", xff="172.28.0.4, 172.28.0.5")
        assert security.get_client_host(request) == "172.28.0.6"

    def test_malformed_hop_right_of_client_stops_scan(self, trusted_proxy):
        # A garbage entry to the RIGHT of the real client breaks the trusted
        # chain; we fall back to the direct peer instead of scanning past it.
        request = _make_request(peer="172.28.0.6", xff="9.9.9.9, not-an-ip")
        assert security.get_client_host(request) == "172.28.0.6"

    def test_garbage_left_of_trusted_chain_never_reached(self, trusted_proxy):
        request = _make_request(peer="172.28.0.6", xff="not-an-ip, 9.9.9.9, 172.28.0.5")
        assert security.get_client_host(request) == "9.9.9.9"

    def test_no_forwarded_header_uses_direct_peer(self, trusted_proxy):
        request = _make_request(peer="172.28.0.6", xff=None)
        assert security.get_client_host(request) == "172.28.0.6"
