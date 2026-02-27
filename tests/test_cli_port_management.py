from __future__ import annotations

import signal
import sys
import types
from pathlib import Path

import spectra_sherpa.cli as cli


def test_find_listening_pids_parses_lsof_and_skips_self(monkeypatch):
    fake_result = types.SimpleNamespace(returncode=0, stdout="123\n456\nabc\n")

    monkeypatch.setattr(cli.subprocess, "run", lambda *args, **kwargs: fake_result)
    monkeypatch.setattr(cli.os, "getpid", lambda: 456)

    assert cli._find_listening_pids(8000) == [123]


def test_clear_port_noop_when_not_in_use(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda _cmd: "/usr/bin/lsof")
    monkeypatch.setattr(cli, "_find_listening_pids", lambda _port: [])
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(cli.os, "kill", lambda pid, sig: killed.append((pid, sig)))

    ok = cli._clear_port(8000, grace_seconds=0.0, force_kill=True)

    assert ok is True
    assert killed == []


def test_clear_port_force_kills_when_pid_survives(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda _cmd: "/usr/bin/lsof")
    states = [[1001], [1001], []]

    def _fake_find(_port: int) -> list[int]:
        return states.pop(0) if states else []

    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(cli, "_find_listening_pids", _fake_find)
    monkeypatch.setattr(cli.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(cli.time, "sleep", lambda *_args, **_kwargs: None)

    ok = cli._clear_port(8000, grace_seconds=0.0, force_kill=True)

    assert ok is True
    assert killed == [(1001, signal.SIGTERM), (1001, signal.SIGKILL)]


def test_clear_port_returns_false_when_lsof_missing(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda _cmd: None)
    monkeypatch.setattr(cli, "_find_listening_pids", lambda _port: [9999])

    ok = cli._clear_port(8000, grace_seconds=0.0, force_kill=True)

    assert ok is False


def test_main_respects_kill_port_env(monkeypatch):
    """KILL_PORT_ON_START=true auto-clears a busy port in non-local mode."""
    monkeypatch.setattr(
        "spectra_sherpa._paths.get_env_file_search_paths",
        lambda: [Path("/does/not/exist")],
    )
    monkeypatch.setenv("KILL_PORT_ON_START", "true")
    monkeypatch.setenv("APP_MODE", "hybrid")

    # Simulate a stale process on the port
    monkeypatch.setattr(cli, "_find_listening_pids", lambda _port: [9999])

    calls: list[tuple[int, float, bool]] = []

    def _fake_clear(port: int, *, grace_seconds: float, force_kill: bool) -> bool:
        calls.append((port, grace_seconds, force_kill))
        return True

    monkeypatch.setattr(cli, "_clear_port", _fake_clear)
    monkeypatch.setattr(cli, "_open_browser", lambda *_args, **_kwargs: None)

    fake_uvicorn = types.SimpleNamespace(run=lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    cli.main(["--no-browser", "--port", "8123"])

    assert calls == [(8123, 2.0, True)]


def test_main_local_mode_auto_clears_port(monkeypatch):
    """Local mode auto-clears a busy port without KILL_PORT_ON_START."""
    monkeypatch.setattr(
        "spectra_sherpa._paths.get_env_file_search_paths",
        lambda: [Path("/does/not/exist")],
    )
    monkeypatch.delenv("KILL_PORT_ON_START", raising=False)
    monkeypatch.setenv("APP_MODE", "local")

    monkeypatch.setattr(cli, "_find_listening_pids", lambda _port: [9999])

    calls: list[tuple[int, float, bool]] = []

    def _fake_clear(port: int, *, grace_seconds: float, force_kill: bool) -> bool:
        calls.append((port, grace_seconds, force_kill))
        return True

    monkeypatch.setattr(cli, "_clear_port", _fake_clear)
    monkeypatch.setattr(cli, "_open_browser", lambda *_args, **_kwargs: None)

    fake_uvicorn = types.SimpleNamespace(run=lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    cli.main(["--no-browser", "--port", "8123"])

    assert calls == [(8123, 2.0, True)]


def test_main_nonlocal_fails_fast_on_busy_port(monkeypatch):
    """Non-local mode without KILL_PORT_ON_START exits immediately."""
    monkeypatch.setattr(
        "spectra_sherpa._paths.get_env_file_search_paths",
        lambda: [Path("/does/not/exist")],
    )
    monkeypatch.delenv("KILL_PORT_ON_START", raising=False)
    monkeypatch.setenv("APP_MODE", "hybrid")

    monkeypatch.setattr(cli, "_find_listening_pids", lambda _port: [9999])
    monkeypatch.setattr(cli, "_open_browser", lambda *_args, **_kwargs: None)

    fake_uvicorn = types.SimpleNamespace(run=lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    import pytest

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--no-browser", "--port", "8123"])

    assert exc_info.value.code == 1


def test_main_skips_clear_when_port_free(monkeypatch):
    """No port clearing when nothing is listening."""
    monkeypatch.setattr(
        "spectra_sherpa._paths.get_env_file_search_paths",
        lambda: [Path("/does/not/exist")],
    )
    monkeypatch.delenv("KILL_PORT_ON_START", raising=False)

    monkeypatch.setattr(cli, "_find_listening_pids", lambda _port: [])

    calls: list[tuple[int, float, bool]] = []
    monkeypatch.setattr(
        cli,
        "_clear_port",
        lambda port, *, grace_seconds, force_kill: calls.append((port, grace_seconds, force_kill)) or True,
    )
    monkeypatch.setattr(cli, "_open_browser", lambda *_args, **_kwargs: None)

    fake_uvicorn = types.SimpleNamespace(run=lambda *args, **kwargs: None)
    monkeypatch.setitem(sys.modules, "uvicorn", fake_uvicorn)

    cli.main(["--no-browser", "--port", "8123"])

    assert calls == []
