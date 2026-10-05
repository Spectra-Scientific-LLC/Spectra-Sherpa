from __future__ import annotations

import errno
import socket
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

import spectra_sherpa.cli as cli


@pytest.fixture
def isolated_cli(monkeypatch):
    monkeypatch.setattr("spectra_sherpa._paths.get_env_file_search_paths", lambda: [Path("/does/not/exist")])
    monkeypatch.delenv("KILL_PORT_ON_START", raising=False)
    monkeypatch.delenv("SPECTRA_SHERPA_PRESERVE_PORT", raising=False)
    run, browser = Mock(), Mock()
    signal = Mock(side_effect=AssertionError("startup must never signal another process"))
    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=run))
    monkeypatch.setattr(cli, "_open_browser", browser)
    monkeypatch.setattr(cli.os, "kill", signal)
    return run, browser, signal


@pytest.mark.parametrize("mode", ["local", "extension_test", "enterprise"])
@pytest.mark.parametrize("legacy_cleanup", [False, True])
def test_busy_listener_survives_startup(isolated_cli, monkeypatch, capsys, mode, legacy_cleanup):
    """Use a real listener, with no lsof/PID-discovery dependency or actual signal."""
    monkeypatch.setenv("APP_MODE", mode)
    if legacy_cleanup:
        monkeypatch.setenv("KILL_PORT_ON_START", "true")
        monkeypatch.setenv("KILL_PORT_FORCE", "true")
        monkeypatch.setenv("KILL_PORT_GRACE_SECONDS", "0")
    run, browser, signal = isolated_cli
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(SystemExit) as exc:
            cli.main(["--host", "127.0.0.1", "--port", str(port)])
        assert exc.value.code == 1
        with socket.create_connection(("127.0.0.1", port), timeout=1) as client:
            connection, _ = listener.accept()
            with connection:
                connection.sendall(b"still-alive")
                assert client.recv(32) == b"still-alive"
    run.assert_not_called()
    browser.assert_not_called()
    signal.assert_not_called()
    output = capsys.readouterr().out
    assert "Existing processes are left untouched" in output
    assert "--port <PORT>" in output
    if legacy_cleanup:
        assert "no longer supported" in output


def test_desktop_busy_port_is_preserved(isolated_cli, monkeypatch):
    monkeypatch.setenv("APP_MODE", "local")
    monkeypatch.setenv("SPECTRA_SHERPA_PRESERVE_PORT", "true")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        with pytest.raises(SystemExit):
            cli.main(["--host", "127.0.0.1", "--port", str(listener.getsockname()[1])])
    isolated_cli[2].assert_not_called()


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0", "::1"])
def test_free_or_ephemeral_port_reaches_uvicorn(isolated_cli, monkeypatch, host):
    if host == "::1":
        try:
            with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe:
                probe.bind((host, 0))
        except OSError as exc:
            if exc.errno in {errno.EAFNOSUPPORT, errno.EPROTONOSUPPORT, errno.EADDRNOTAVAIL}:
                pytest.skip(f"IPv6 loopback is unavailable at runtime: {exc}")
            raise
    monkeypatch.setenv("APP_MODE", "local")
    cli.main(["--host", host, "--port", "0", "--no-browser"])
    assert isolated_cli[0].call_args.kwargs["port"] == 0
    assert isolated_cli[0].call_args.kwargs["host"] == host
    isolated_cli[2].assert_not_called()


def test_bind_race_never_falls_back_to_killing(isolated_cli, monkeypatch):
    monkeypatch.setenv("APP_MODE", "local")
    isolated_cli[0].side_effect = OSError("address already in use after preflight")
    with pytest.raises(OSError, match="after preflight"):
        cli.main(["--host", "127.0.0.1", "--port", "0", "--no-browser"])
    isolated_cli[2].assert_not_called()


@pytest.mark.parametrize("error", [errno.EAFNOSUPPORT, errno.EPROTONOSUPPORT])
@pytest.mark.parametrize("failure_at", ["create", "bind"])
def test_unavailable_ipv6_does_not_refuse_ipv4(isolated_cli, monkeypatch, capsys, error, failure_at):
    monkeypatch.setenv("APP_MODE", "local")
    monkeypatch.setattr(
        cli.socket,
        "getaddrinfo",
        Mock(
            return_value=[
                (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::1", 0, 0, 0)),
                (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0)),
            ]
        ),
    )
    ipv4, ipv6 = MagicMock(), MagicMock()
    failure = OSError(error, "IPv6 unavailable")
    ipv6.__enter__.return_value.bind.side_effect = failure
    factory = Mock(side_effect=[failure if failure_at == "create" else ipv6, ipv4])
    monkeypatch.setattr(cli.socket, "socket", factory)
    cli.main(["--host", "localhost", "--port", "0", "--no-browser"])
    ipv4.__enter__.return_value.bind.assert_called_once_with(("127.0.0.1", 0))
    isolated_cli[0].assert_called_once()
    isolated_cli[2].assert_not_called()
    assert "Stop the service" not in capsys.readouterr().out


@pytest.mark.parametrize("error", [errno.EADDRINUSE, errno.EACCES])
def test_bind_conflicts_still_refuse(isolated_cli, monkeypatch, error):
    probe = MagicMock()
    probe.__enter__.return_value.bind.side_effect = OSError(error, "bind refused")
    monkeypatch.setattr(cli.socket, "socket", Mock(return_value=probe))
    with pytest.raises(SystemExit) as exc:
        cli.main(["--host", "127.0.0.1", "--port", "0", "--no-browser"])
    assert exc.value.code == 1
    isolated_cli[0].assert_not_called()
    isolated_cli[2].assert_not_called()


@pytest.mark.parametrize("error", [errno.EADDRNOTAVAIL, errno.EINVAL])
def test_nonconflict_errors_are_left_to_uvicorn(isolated_cli, monkeypatch, capsys, error):
    monkeypatch.setenv("APP_MODE", "local")
    monkeypatch.setattr(cli.socket, "socket", Mock(side_effect=OSError(error, "not a busy port")))
    cli.main(["--host", "127.0.0.1", "--port", "0", "--no-browser"])
    isolated_cli[0].assert_called_once()
    isolated_cli[2].assert_not_called()
    output = capsys.readouterr().out
    assert "Uvicorn will attempt startup" in output
    assert "Stop the service" not in output


@pytest.mark.parametrize("error", [errno.EAFNOSUPPORT, errno.EPROTONOSUPPORT])
def test_all_unsupported_families_refuse_with_accurate_diagnosis(isolated_cli, monkeypatch, capsys, error):
    monkeypatch.setattr(
        cli.socket,
        "getaddrinfo",
        Mock(
            return_value=[
                (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::1", 0, 0, 0)),
                (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0)),
            ]
        ),
    )
    factory = Mock(side_effect=OSError(error, "unsupported family"))
    monkeypatch.setattr(cli.socket, "socket", factory)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--host", "localhost", "--port", "0"])
    assert exc.value.code == 1
    assert factory.call_count == 2
    for spy in isolated_cli:
        spy.assert_not_called()
    output = capsys.readouterr().out
    assert "No supported address family" in output
    assert "Stop the service" not in output
    assert "--port <PORT>" not in output


@pytest.fixture(autouse=True)
def explicit_test_runtime_policy(monkeypatch):
    from spectra_sherpa.app.contracts import runtime_mode

    monkeypatch.setattr(runtime_mode, "_policies", {})
    runtime_mode.register_runtime_mode(
        runtime_mode.RuntimeModePolicy(name="extension_test", implicit_loopback_identity=True)
    )
