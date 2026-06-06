"""Tests for Tier-2 CodeQL hardening: SSRF guard, ReDoS-tightened regex."""

from __future__ import annotations

import socket

import pytest

from spectra_sherpa.app.lib.io import FILENAME_PATTERN, _extract_label_from_filename
from spectra_sherpa.app.services import basic_chat

# ---------------------------------------------------------------------------
# SSRF guard for the BYO chat endpoint validator
# ---------------------------------------------------------------------------


class TestIsSafeOutboundUrl:
    """``_is_safe_outbound_url`` defends against SSRF on user-supplied URLs."""

    def test_rejects_non_http_scheme(self):
        ok, _ = basic_chat._is_safe_outbound_url("file:///etc/passwd")
        assert ok is False
        ok, _ = basic_chat._is_safe_outbound_url("gopher://example.com/")
        assert ok is False

    def test_rejects_missing_host(self):
        ok, _ = basic_chat._is_safe_outbound_url("http://")
        assert ok is False

    def test_rejects_loopback_resolution(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: [(None, None, None, None, ("127.0.0.1", 0))])
        ok, reason = basic_chat._is_safe_outbound_url("https://evil.example.com/chat")
        assert ok is False
        assert "private" in reason.lower() or "restricted" in reason.lower()

    def test_rejects_aws_metadata_link_local(self, monkeypatch):
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            lambda *_a, **_k: [(None, None, None, None, ("169.254.169.254", 0))],
        )
        ok, _ = basic_chat._is_safe_outbound_url("http://attacker.example/chat")
        assert ok is False

    def test_rejects_private_rfc1918(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: [(None, None, None, None, ("10.0.0.5", 0))])
        ok, _ = basic_chat._is_safe_outbound_url("https://internal.corp/chat")
        assert ok is False

    def test_rejects_dns_failure(self, monkeypatch):
        def _raise(*_a, **_k):
            raise socket.gaierror("nope")

        monkeypatch.setattr(socket, "getaddrinfo", _raise)
        ok, reason = basic_chat._is_safe_outbound_url("https://does-not-resolve.invalid/chat")
        assert ok is False
        assert "resolve" in reason.lower()

    def test_allows_public_ip(self, monkeypatch):
        # 1.1.1.1 is a public Anycast resolver; treat it as a stand-in
        # for "real public LLM provider IP" without relying on live DNS.
        monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: [(None, None, None, None, ("1.1.1.1", 0))])
        ok, reason = basic_chat._is_safe_outbound_url("https://api.example.com/v1/chat/completions")
        assert ok is True
        assert reason == ""

    def test_env_opt_out_bypasses_private_check(self, monkeypatch):
        # Self-hosted-LLM users (e.g. Ollama on 127.0.0.1) opt in.
        monkeypatch.setenv("SPECTRA_SHERPA_ALLOW_PRIVATE_LLM_ENDPOINTS", "true")

        def _should_not_be_called(*_a, **_k):  # pragma: no cover — guard
            raise AssertionError("DNS lookup should be skipped when bypass is set")

        monkeypatch.setattr(socket, "getaddrinfo", _should_not_be_called)
        ok, _ = basic_chat._is_safe_outbound_url("http://localhost:11434/v1/chat/completions")
        assert ok is True


@pytest.mark.asyncio
class TestTestConnectionBlocksSSRF:
    async def test_validator_refuses_loopback_endpoint(self, monkeypatch):
        monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: [(None, None, None, None, ("127.0.0.1", 0))])
        ok, reason = await basic_chat.test_connection(
            endpoint_url="https://attacker.example",
            endpoint_key="sk-test",
            model="deepseek-chat",
        )
        assert ok is False
        assert "private" in reason.lower() or "restricted" in reason.lower()

    async def test_stream_chat_revalidates_saved_endpoint_at_runtime(self, monkeypatch):
        monkeypatch.setenv("CHAT_ENDPOINT_URL", "https://attacker.example/v1")
        monkeypatch.setenv("CHAT_ENDPOINT_KEY", "sk-test")
        monkeypatch.setenv("CHAT_ENDPOINT_MODEL", "deepseek-chat")
        monkeypatch.setattr(socket, "getaddrinfo", lambda *_a, **_k: [(None, None, None, None, ("127.0.0.1", 0))])

        with pytest.raises(ValueError) as exc_info:
            async for _chunk in basic_chat.stream_chat("hello"):
                pass

        assert "private" in str(exc_info.value).lower() or "restricted" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Tightened FILENAME_PATTERN (eliminates polynomial backtracking)
# ---------------------------------------------------------------------------


class TestFilenamePattern:
    @pytest.mark.parametrize(
        "filename,expected_label",
        [
            ("ABC.CSV", "ABC"),
            ("ABC123.CSV", "ABC123"),
            ("ABC_foo.CSV", "ABC"),
            ("ABC-foo.CSV", "ABC"),
            ("ABC foo.CSV", "ABC"),
            ("xyz.csv", "XYZ"),  # case-insensitive via IGNORECASE
        ],
    )
    def test_matches_expected_label(self, filename, expected_label):
        match = FILENAME_PATTERN.match(filename)
        assert match is not None, f"{filename!r} should match"
        assert match.group("label").upper() == expected_label

    @pytest.mark.parametrize(
        "filename",
        [
            "ABC.txt",  # wrong extension
            "_LEADING.CSV",  # no label before separator
            "",  # empty
        ],
    )
    def test_rejects_non_matching_filenames(self, filename):
        assert FILENAME_PATTERN.match(filename) is None

    def test_pathological_input_does_not_hang(self):
        # 10k-char non-matching input — must return quickly (no
        # polynomial backtracking).  Worst case the engine retries
        # linearly along the label prefix; the tightened regex keeps
        # this O(n) instead of O(n^2).
        pathological = "A" * 10_000 + ".txt"
        # No assertion on time; just assert it completes promptly via the
        # default test timeout.  If the previous form regressed, this
        # would lock up.
        assert FILENAME_PATTERN.match(pathological) is None

    def test_extract_label_helper_still_returns_normalised_label(self):
        # End-to-end sanity check through the public helper.
        assert _extract_label_from_filename("SAMPLE123.CSV") == "SAMPLE123"
